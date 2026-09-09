# 下载吞吐与媒体会话自愈

面向运维和排障：说明 2026-09-08 这轮修复解决了什么、怎么验证、出问题时看哪里。

## 背景：两个会互相引爆的故障

### 1. 入队开销随任务规模平方级增长

`enqueue_download` 每往下载队列里加一个文件，都会调用 `snapshot_node(node)`；
而 `snapshot_node` 会遍历该任务下**所有**已知文件，逐个调用 `upsert_file` 落库。
于是往一个已有 N 个文件的任务里再加一个文件，成本是 O(N)；整批入队就是 O(N²)。

这段工作跑在线程池里但持有 GIL，实测在 1 核服务器上：

- 队列里约 190 个文件时，单条入队耗时约 19 秒；
- 一次 200 条的入队阶段占满 48 分钟，期间下载线程一个文件都没处理。

### 2. 媒体会话假死后永不恢复

Pyrogram 的 `Client.get_file` 对内部异常是 `except Exception: log.exception(e)`，
吞掉之后返回一个**空文件**。而 `client.media_sessions[dc_id]` 里的会话是永久缓存的，
一旦某个会话坏掉，后续每个文件都会下成 0 字节，重试三次全失败，进程不重启就好不了。

两个故障是有因果关系的：故障 1 长时间霸占事件循环，会饿死 pyrogram 自己的网络协程，
把媒体会话拖进假死状态，进而引爆故障 2。

## 修复内容

| 位置 | 改动 |
| --- | --- |
| `module/task_state.py` | `snapshot_node(..., sync_files=False)`：只写任务本身，不再全量回写文件 |
| `module/task_state.py` | `TaskSnapshot.clone()` 取代 `copy.deepcopy`，去掉快照复制的通用递归开销 |
| `module/task_state.py` | 新增 `terminal_safe_task_updates()`：终态任务不会被文件级进度重新拉回运行态 |
| `module/download_queue.py` | 入队改用 `sync_files=False` + 终态保护 |
| `module/download_lifecycle.py` | 下载阶段的三处状态转换补上终态保护（此前只有上传阶段有） |
| `module/progress_persistence.py` | 进度落盘补上终态保护 |
| `module/download_transfer.py` | 新增 `EmptyDownloadError` 与媒体会话自愈 |

### 媒体会话自愈的触发条件

定义在 `module/download_transfer.py`：

- `EMPTY_DOWNLOAD_RESET_THRESHOLD = 6` — 连续 6 次下载返回空文件就重建媒体会话。
  任意一次成功下载都会把计数清零，所以健康状态下不可能误触发。
- `MEDIA_SESSION_RESET_COOLDOWN = 60.0` — 两次重建之间至少间隔 60 秒。
- `MEDIA_SESSION_STOP_TIMEOUT = 10.0` — 停止单个旧会话的超时，防止被卡死的会话拖住。

重建时不去抢 pyrogram 的 `media_sessions_lock`（会话卡死时抢锁会把自己也挂住），
直接清空 `client.media_sessions` 字典，`get_session` 之后会按需重建。

## 怎么验证

```bash
python3 -m pytest tests/module/test_task_state.py \
                  tests/module/test_download_queue_enqueue.py \
                  tests/module/test_download_lifecycle.py \
                  tests/module/test_progress_persistence.py \
                  tests/module/test_media_session_recovery.py -q
```

关键用例：

- `test_enqueue_cost_does_not_grow_with_task_size` — 一次入队只做 1 次文件级写入，
  与任务里已有多少文件无关。这是防止故障 1 复发的硬契约。
- `test_download_phase_does_not_reopen_a_terminal_task` /
  `test_failed_download_on_a_terminal_task_is_still_recorded` /
  `test_enqueue_into_terminal_task_does_not_raise` /
  `test_progress_writes_do_not_reopen_a_terminal_task` — 复现并挡住
  `invalid_task_transition: 'completed_with_errors' -> 'downloading'`。
  这四条覆盖四条独立的写入路径：入队、下载阶段、异常记录、进度落盘。
  任何新增的 `transition_file` 调用都必须走 `terminal_safe_task_updates`，
  用 `grep -rn 'task_updates={"status"' module/` 可以查是否有漏网的硬写法。
- `test_repeated_empty_downloads_rebuild_media_sessions` — 端到端验证连续空文件
  会真的把媒体会话清掉。

## 排障入口

**下载变慢时**，先看入队是不是又在霸占进程：

```bash
grep "add_download_task: enqueued" log/tdl.log | cut -c1-16 | uniq -c | tail -20
```

正常应该是每分钟几十到上百条。如果掉到每分钟个位数，说明入队又退化了。

**下载全失败时**，看是不是空文件：

```bash
grep -c "size mismatch: 0 !=" log/tdl.log
grep "媒体会话" log/tdl.log | tail
```

出现 `连续 N 次下载返回空文件，判定媒体会话假死，正在重建...` 说明自愈生效了。
如果重建之后仍然持续空文件，那就不是会话问题，需要查账号或网络。

**看进程到底卡在哪**（服务器上已装 py-spy）：

```bash
py-spy dump --pid $(pgrep -f media_downloader.py)
```

如果多个 `asyncio_*` 线程都停在 `task_state.py` 里，说明状态存储又成了瓶颈。


---

# 磁盘配额闸门的三个死锁（2026-09-09）

上面那轮修复上线后，线上又出现两次「整个进程静默、日志一行不写」的停滞：

| 时段（服务器时间） | 时长 | 结束方式 |
| --- | --- | --- |
| 09-08 12:38 → 18:38 | 正好 6 小时 | 批次超时兜底，自行恢复 |
| 09-08 19:09 → 09-09 00:54 | 5 小时 45 分 | 人工重启 |

停滞期间磁盘还有 10 GB 空闲，跟真实磁盘占用无关。`web_tasks.sqlite3` 里
有 6 个任务停在 `error='waiting_for_disk_space'`，说明它们卡在
`DiskSpaceAdmission.acquire()` 里没出来。

## 三个缺陷

### 1. 严格 FIFO 会自锁

`acquire()` 原本要求 `self._waiting[0] == key` 才放行。队首一旦放不下，
后面所有包（哪怕只要 100 MB）都得跟着等。而磁盘空间只有靠下载完成才会释放
—— 没有人能下载，空间就永远不会出现。这是个自己解不开的死循环。

现在改成：**自己放得下，且（是队首 或 队首此刻放不下）** 就放行。
队首仍然享有优先权，只有在它确实排不上时才允许小包先走。
并发等待者数量由批次调度信号量限制（默认 4 个），队首不会被长期饿死。

### 2. 无限等待，没有逃生口

`on_package_started` 里有个事前检查，本意就是拦住「永远放不下」的包
（代码注释写着 "would otherwise hold a download slot forever"），
但它比的是**单文件窗口**，而 `acquire()` 实际申请的是**整包窗口**
（`worker 数 × 最大单文件`）。两个数不是一回事，所以检查放行的包
仍然可能永远排不上队。

现在 `acquire()` 自己兜底：请求量持续超过「所有预留都释放后的空间上限」
达到 `DEFAULT_CAPACITY_TIMEOUT_SEC`（默认 600 秒）就抛
`DiskCapacityExceededError`。给宽限期是因为空间可能被外部清理释放，
不能一发现放不下就判死。调用方接住这个异常，只让该包失败，队列继续走。

### 3. 等待者杀不掉（最致命的一个）

原实现用 `asyncio.wait_for(self._condition.wait(), timeout=...)` 做轮询。
这个组合是坏的：

- `wait_for` 会把 `Condition.wait()` 包进另一个 Task，而 `asyncio.Lock`
  不记录持有者，锁的归属会错乱；
- `Condition.wait()` 在 `finally` 里循环重抢锁并**吞掉** `CancelledError`；
- `wait_for` 超时到期时，会把外部传进来的取消**转成 `TimeoutError`**，
  调用方一旦吞掉这个超时，取消就永远丢了。

结果就是等待者既拿不到空间也杀不掉，批次 6 小时超时发出的取消根本不起作用，
只能重启进程。关停时留下的
`RuntimeError: cannot notify on un-acquired lock` 就是锁状态已经错乱的证据。

现在改成 `asyncio.Lock` + 裸 future：等待期间**不持任何锁**，
超时由 `loop.call_later` 直接兑现 future，**不使用 `asyncio.wait_for`**。

> 硬约束：这个模块里不要再引入 `asyncio.wait_for(cond.wait())`，
> 也不要在等待时持锁。两条都踩过，代价是线上两次 6 小时静默。

### 附带修好的预留泄漏

`acquire()` 的异常清理分支原本不退还 `_reserved_bytes`。一旦异常发生在
登记预留之后，这笔额度就永久占着直到进程重启，让后续每个包都更难排上队。
现在的不变量是：**acquire 要么返回一个 DiskReservation，要么什么都不留下。**

## 怎么验证

```bash
python3 -m pytest tests/module/test_download_admission.py -q
```

九条用例，每条都验证过「改回旧写法就会失败」：

- `test_a_blocked_head_does_not_stall_smaller_packages` — 缺陷 1
- `test_head_still_wins_when_it_fits` — 插队不能破坏先来后到
- `test_request_beyond_disk_capacity_fails_after_grace_period` — 缺陷 2
- `test_capacity_grace_period_resets_when_space_appears` — 宽限期内空间回来就正常放行
- `test_a_waiting_acquire_can_actually_be_cancelled` — 缺陷 3
- `test_cancelled_acquire_leaves_no_reservation_behind` /
  `test_failure_after_registration_releases_the_reservation` — 预留泄漏

用例里凡是可能卡住的等待者都注入了可控时钟，失败时走容量超时干净退出，
不会把测试进程挂死。

## 排障入口

**又出现「日志一行不写」的静默时**，先看是不是卡在配额闸门：

```bash
./.venv/bin/python - <<'EOF'
import sqlite3
db = sqlite3.connect("web_tasks.sqlite3")
for r in db.execute("select task_id,status,error from tasks where error!='' order by updated_at desc limit 10"):
    print(r)
EOF
```

出现 `waiting_for_disk_space` 就是卡在 `acquire()`。再用
`py-spy dump --pid $(pgrep -f media_downloader.py)` 确认调用栈里有
`download_admission`。正常情况下这个等待最多 600 秒就会自行了断。
