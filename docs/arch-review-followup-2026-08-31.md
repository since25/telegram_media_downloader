# 2026-07-07 架构评审整改 —— 主线现状核对

**核对日期**：2026-08-31
**核对基准**：`master` @ `f36b828`（Hermes MCP 控制层，已部署生产）
**被核对对象**：分支 `arch-review-remediation` 的提交 `b57ee12`（2026-07-07，80 个文件），对应文档 `docs/architecture-review-2026-07-07.md`

## 一、结论

那份整改**从未合并进主线**。但主线在随后的 194 个提交里已经独立修好了其中 10 条，3 条修了一半，7 条仍然是活的。

分支上的补丁**没有一个能直接套用** —— 主线期间重构出了 `download_entry.py`、`download_lifecycle.py`、`transfer_progress.py`、`config_persistence.py` 等一批新模块，整改要照结论重写，不能 merge。

本轮已修复其中 2 条用户可感知的功能故障（见第四节），其余 5 条待排期。

## 二、已在主线独立修复（10 条，无需处理）

| 编号 | 原问题 | 主线现状 |
|---|---|---|
| P0-1 | watchdog 心跳分裂脑，超 10 分钟的下载被系统性误杀 | 已修：统一到 `module/transfer_progress.py` 的 `TransferProgressTracker`，单一心跳来源 |
| P0-2 | `download_task` 宽 except 破坏 finish 计数，非 bot 运行永久挂起 | 已修：`module/download_lifecycle.py:387-394` 异常分支写入终态并调 `node.stat` |
| P0-3 | web `/get_download_list` 每次调用 NameError 500 | 已修：`module/web.py:1712` 正确调用 `get_download_result()` |
| P0-5 | rclone 路径/文件名进 `shell=True`，认证后可任意命令执行 | 已修：`module/cloud_drive.py:90,202` 改用 `create_subprocess_exec` + 参数列表 |
| P0-6 | pyrogram fork 跟随分支头，安装结果不可复现 | 已修：`requirements.txt:2` 锁到 commit `51a100c5` + sha256 校验 |
| P0-7 | aligo 上传分支必然 TypeError | 已修：`module/app.py:820-827` 改用 `functools.partial` |
| P1-12 | FloodWait 立即判失败，限流期整批任务连环失败 | 已修：`module/download_transfer.py:363-368` 按服务器给的时间等待后重试 |
| P1-13 | 无法区分 watchdog 卡死取消与外部取消 | 已修：`TransferProgressTracker.mark_stalled/consume_stalled` |
| P2-16 | 登录无限速，弱密码可在线爆破 | 已修：`module/web.py:82` `LoginAttemptLimiter`，按来源 IP 失败计数 + 退避 |
| P2-17a | session `secret_key` 是硬编码常量 `"tdl"` | 已修：`module/web.py:70` 改用 `secrets.token_urlsafe(32)` |

## 三、部分修复（3 条）

| 编号 | 已解决的部分 | 仍然存在的部分 |
|---|---|---|
| P1-9 | 配置原子写已就位：`module/config_persistence.py` 用 `mkstemp` + `fsync` + `os.replace`，`module/app.py:456` 有 `_config_lock` | 仍在直接遍历下载线程正在改的活字典（`module/app.py:975`），边下载边保存设置仍可能 `dictionary changed size during iteration` |
| P1-14 | 预扫描命名错乱的竞态已用 `naming_snapshot` 修好 | `package_plan` / `package_media_items` / `last_progress_report` 三个字段仍未在 `TaskNode.__init__` 声明，靠 4 处外部赋值（代码卫生，不影响功能） |
| P2-15 | 浏览器端 AES 假加密已去掉，`module/templates/login.html` 现在直接提交密码 —— **安全问题实际已解** | 576K 的 `module/static/aes/crypto-js-master/` 目录和 `utils/crypto.py` 的 `AesBase64` 仍作为死代码留在仓库里，已无任何引用 |

## 四、本轮已修复（2 条）

见 `progress.md` 2026-08-31 条目。

| 编号 | 原问题 | 修复 |
|---|---|---|
| P0-4 | bot 配置持久化整体失效：`update_config` dump 到字面量文件 `d`，启动却从 `config_path` 读；`/add_filter` 写进黑洞属性 `_bot.app.down` | `module/bot.py:255` 改写 `self.config_path`；`module/bot.py:766` 改写 `_bot.download_filter`（`assign_config` 实际加载、`update_config` 实际持久化的字段） |
| P0-8 | `download_comments` 两个 `except: return` 静默吞掉扫描失败，绕过外层清理，TaskNode 永久泄漏在活跃注册表 | `module/download_entry.py` 删除内层 try/except，让失败落到已有的 `report_bot_status` + `remove_active_task_node` 分支 |

回归测试：`tests/module/test_bot_commands.py`（2 个）、`tests/module/test_download_comments_errors.py`（2 个）。

## 五、待排期（5 条）

按建议优先级排列。

### 1. 频道进度可能串台（原 P1-11，数据正确性）

`module/app.py:963` 起的 `_update_config_locked` 仍用递增的位置序号 `idx` 把频道的"已读到哪条"写回配置，假设字典遍历顺序与两份 YAML 的列表顺序永远一致。`assign_config` 会跳过缺 `chat_id` 的条目、折叠重复 `chat_id`，web 设置又会在运行时追加频道 —— 一旦失步，A 频道的进度会静默写进 B 频道，表现为消息被跳过或整体重下，无任何报错。

**改法**：照搬 `module/web.py` 已有的模式，构建 `chat_id → entry` 映射后按 `chat_id` 匹配写入，缺失时追加。

### 2. 断电/强杀丢整轮进度（原 P1-10，数据安全）

`module/download_runtime.py:224` 的 `update_config()` 在关停路径里，进度只在正常退出时落盘。`kill -9`、OOM、断电会丢掉整轮的 `last_read_message_id` 和 `ids_to_retry`；bot 模式下可能是几天的状态。

**改法**：在每完成一个频道后调用一次 `update_config`。前置条件是 P1-9 的原子写（已就位）。不要加定时器 —— 会在字典正被改的时刻写盘。

### 3. 保存设置时可能崩溃（原 P1-9 剩余部分，数据安全）

见第三节。`module/app.py:975` 迭代前加 `list(...)` 快照即可。

### 4. 长期运行内存单增（原 P2-18）

`module/bot.py` 的待确认工作流字典存着完整扫描结果（预扫描上限 5000 条消息），只在用户确认/取消时清理。`module/bot.py:867` 写了 `created_at` 但没有任何地方读取，没有清扫逻辑。

**改法**：在既有的 3 秒 `update_reply_message` 循环里清扫超过 30-60 分钟的条目。

### 5. 卫生项（原 P2-17b、P2-19、P2-15 剩余部分）

- `module/web.py:73` 的 `SESSION_COOKIE_SAMESITE` 仍是 `"Lax"`，未改 `"Strict"`。
- `module/comment_workflow.py:46-49` 的命名策略 A/B/D 在生产不可达（两个回调 handler 都只接受 RECOMMENDED），`build_naming_previews` / `build_package_naming_previews` 零非测试调用者。
- `module/static/aes/crypto-js-master/` 和 `utils/crypto.py` 的死代码。

## 六、核对方法与局限

本清单基于**静态代码核对**（定位 + 读实现），不是运行时实测。

- 标"仍然是活的"的条目都定位到了具体文件与行号，判断可靠。
- 标"已修复"的条目核对的是代码结构是否正确，**没有为每条构造复现场景验证**。若需更硬的结论，需补对应回归测试。
- 本轮实际修复的 2 条走了完整 TDD：先写复现测试并确认为正确原因失败，再修复。

## 七、遗留：主线上的既有测试失败

核对期间发现 `master` 上有 7 个既有测试失败，与本次整改无关，也不是本轮改动引入的（已在干净 master 上复现同样 7 个）：

- `tests/module/test_cloud_drive.py::test_rclone_upload_uses_exec_and_return_code_success`
- `tests/module/test_comment_workflow.py` 中 3 个 `build_naming_previews` 相关用例
- `tests/test_media_downloader.py` 中 3 个命名上下文相关用例

需单独排查。
