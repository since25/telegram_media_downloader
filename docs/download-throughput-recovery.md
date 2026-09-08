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
| `module/download_lifecycle.py` | 下载阶段的两处状态转换补上终态保护（此前只有上传阶段有） |
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
                  tests/module/test_media_session_recovery.py -q
```

关键用例：

- `test_enqueue_cost_does_not_grow_with_task_size` — 一次入队只做 1 次文件级写入，
  与任务里已有多少文件无关。这是防止故障 1 复发的硬契约。
- `test_download_phase_does_not_reopen_a_terminal_task` /
  `test_enqueue_into_terminal_task_does_not_raise` — 复现并挡住
  `invalid_task_transition: 'completed_with_errors' -> 'downloading'`。
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
