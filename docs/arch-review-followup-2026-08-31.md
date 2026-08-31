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
- `module/static/aes/crypto-js-master/` 和 `utils/crypto.py` 的死代码。
- `module/comment_workflow.py` 的 `month_for_comment`：全仓库零调用者（含测试），自 `b4ebf98` 起成为死代码。独立一笔，与下述预览构建器无关。

原 P2-19 中的「预览构建器」部分已于 2026-08-31 清理，见第八节。**但该条目对命名策略枚举的判断是错的，已订正**：

> ~~`module/comment_workflow.py:46-49` 的命名策略 A/B/D 在生产不可达。~~

**订正**：A/B/D 三个枚举成员**在生产运行时仍会被真实构造**，不是死代码。`parse_callback_data`
（`module/comment_workflow.py:594`）与 `parse_package_callback_data`（`:615`）用
`NamingStrategy(parts[2])` 把 Telegram 回调里的**外部字符串**直接转成枚举。
`c7ed458`（2026-06-09）之前的版本给用户发过「采用A / 采用B / 采用D」内联按钮，
而 Telegram 的内联键盘随消息永久留在聊天记录里 —— 老用户往上翻点旧按钮，
`NamingStrategy("A")` 今天仍会执行，随后被 `module/bot.py:2783` / `:2647` 的
RECOMMENDED 守卫拒绝。仓库自带两条针对该路径的回归测试
（`test_confirm_callback_rejects_forged_non_recommended_strategy` 及其 package 版本）。

因此这三个枚举成员**不应删除**，两个 RECOMMENDED 守卫也不应删除。

## 六、核对方法与局限

本清单基于**静态代码核对**（定位 + 读实现），不是运行时实测。

- 标"仍然是活的"的条目都定位到了具体文件与行号，判断可靠。
- 标"已修复"的条目核对的是代码结构是否正确，**没有为每条构造复现场景验证**。若需更硬的结论，需补对应回归测试。
- 本轮实际修复的 2 条走了完整 TDD：先写复现测试并确认为正确原因失败，再修复。

## 七、遗留：主线上的 7 个测试失败 —— 全部是过期测试，非代码退化

核对期间发现 `master` 上有 7 个测试失败，与本次整改无关，也不是本轮改动引入的（已在干净 master 上复现同样 7 个）。**已查明根因：产品代码行为是正确的、是有意改的，是测试断言没跟上。**

### 第 1 组（6 个）：资源包路径去前缀

根因提交 `b4ebf98`「feat: save package downloads directly under save root/\<package\>」（2026-08-16，已在 master）。该提交有意做了两件事：

1. `module/comment_workflow.py` 的 `build_package_name_for_strategy`：MONTH_CAPTION 策略不再拼 `channel/month/` 前缀。
2. `module/download_entry.py` 的 `_get_media_meta`：存在 package context 时 `file_save_path = app.save_path`，跳过 `get_file_save_path` 生成的 `chat_title/media_datetime` 前缀。代码内有注释说明意图。

即资源包下载直接落在 `<保存根目录>/<资源包名>/<文件>`。

二分法定量验证：父提交 `8e827e3` 上 `pytest tests/module/test_comment_workflow.py tests/test_media_downloader.py -q` → 144 passed；`b4ebf98` 上 → 2 failed, 142 passed。后续提交新增同类命名测试，累积成现在的 6 个。

受影响用例（前 3 个期望里多了频道名前缀 `zhyseseb/`，后 3 个多了 `Private/2026_06/`）：

- `tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_naming_previews_falls_back_for_extension_only_filename`
- `tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_naming_previews_generates_four_clean_options`
- `tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_naming_previews_uses_fallbacks`
- `tests/test_media_downloader.py::MediaDownloaderTestCase::test_download_prepared_messages_preserves_planned_later_caption_for_package_naming_context`
- `tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_comment_naming_context_for_video`
- `tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_package_naming_context_for_video`

**后续进展**：前 3 个用例已随 `build_naming_previews` / `build_package_naming_previews` 一并删除（见第八节）。
注意此处原先的判断「命名策略 A/B/D 在生产不可达」**是错的**，已在第五节订正 —— 零调用者的只是两个
预览构建器，枚举成员本身仍在生产运行时被外部回调数据构造，不可删除。

### 第 2 组（1 个）：rclone 参数

`tests/module/test_cloud_drive.py::test_rclone_upload_uses_exec_and_return_code_success`

产品代码已支持 `rclone_transfers` 配置（`module/cloud_drive.py:31,40`），实际 argv 多了 `--transfers <n>`，测试期望的 argv 元组没跟上。更新期望值即可。

## 八、过期测试全面审计（2026-08-31，多代理核查）

用 14 个子代理做了一轮侦察 + 对抗核验，每个失败用例在**独立 git 工作区**里用二分法定位起点提交。

### 审计口径与结论

套件规模：collected 799，passed 791，failed 7，skipped 1。

**7 个报红全部是过期测试，真实缺陷 0 个，存疑 0 个。**

| 起点提交 | 数量 | 性质 |
|---|---|---|
| `b4ebf98` + `54dbc4a`（资源包/评论包改存到 save-root/\<package\>） | 6 | 有意的布局调整，测试写死的期望路径没跟上 |
| `a93fce5`（rclone 并发与 transfers 限制） | 1 | 有意新增 `--transfers` 参数，测试期望的 argv 没跟上 |

判定「有意为之」的依据不是「改测试更省事」，而是每条都能拿到独立证据：提交标题声明目标结构、
代码内解释性注释、`config.example.yaml` 中新增的用户可配置项。

### 隐藏的失效测试

除报红外，另有 **1 个被整段注释掉、根本不参与收集**的测试：

- `tests/test_media_downloader.py:2223-2268` 的 `test_upload_telegram_chat`，
  连同其 6 个 `@mock.patch` 装饰器一起被注释。

另有 4 处 `skipIf` / `skipUnless` 属于**正当的平台闸门**（Windows 文件名长度、POSIX 文件权限），
不是过期测试；本次 macOS 运行中只有 1 个真正跳过。全仓库 **零 xfail 标记**。

**合计：7 个报红 + 1 个被注释掉 = 8 个失效测试。**

### 本轮已清理

删除生产零调用者的两个预览构建器 `build_naming_previews` / `build_package_naming_previews`
（`module/comment_workflow.py`，共 78 行），以及测试侧 5 个用例（3 个报红 + 2 个仅服务于被删函数）。
其余夹具调用切到生产在用的 `build_recommended_*` 版本。

结果：全量测试从 7 failed / 791 passed 变为 **4 failed / 789 passed**，无新增失败。

### 剩余 4 个报红的处置（已于 2026-08-31 完成，见第十节）

均为更新断言，**未改产品代码**：

1. `test_get_media_meta_uses_package_naming_context_for_video`
   —— `tests/test_media_downloader.py` 中期望值去掉 `Private/2026_06/` 前缀；
   同用例的 `temp_file_name` 断言保持不变（临时目录仍按 dirname 分层）。
2. `test_get_media_meta_uses_comment_naming_context_for_video`
   —— 期望值去掉 `Discussion/2026_06/zhyseseb/` 前缀。
3. `test_download_prepared_messages_preserves_planned_later_caption_for_package_naming_context`
   —— MONTH_CAPTION 的 `expected_suffix` 去掉 `私密频道/2026_06/`；
   CAPTION 项与 `caption_for_naming` 断言不动。
4. `test_rclone_upload_uses_exec_and_return_code_success`
   —— `tests/module/test_cloud_drive.py` 期望 argv 末尾补 `"--transfers", "1"`
   （对应 `CloudDriveConfig` 默认 `rclone_transfers=1`）。
   注意保留该用例原有的 `reject_shell` 断言，那是防 shell 注入的防线。

### 方法论备注

对抗核验阶段 3 个视角**全部提出了反对证据**，推翻了「A/B/D 完全不可达」这一措辞，
促成了第五节的订正。这是本轮审计最有价值的产出：若按原判断连枚举一起删，
会悄悄削弱针对陈旧/伪造回调的防线，并打掉两条现役回归测试。

## 九、清理废弃分支时挖出的两个真实缺陷（2026-08-31）

准备删除 `arch-review-remediation` 前做的存量核查，发现该分支上的
`tests/module/test_pyrogram_extension.py`（88 行，对应原评审 R5-2）
拿到今天的主线上跑是 **5 failed / 1 passed**。核查确认**不是过期测试，是主线从未修复的真实缺陷**。

### 为什么一直没被发现

`tests/test_media_downloader.py:358-359` 在类级把真的 `get_extension` 整体 patch 掉，
换成 `tests/test_common.py:181` 的手工平行实现，而那份替身把 `guessed_extension`
硬编码成 `""` —— 恰好绕开了出错的那条分支。整个套件从未执行过真实的
mime 猜测路径。

### 缺陷 1：扩展名双点

`_guess_extension` 直接返回 `mimetypes.guess_extension()` 的结果，而后者**带前导点**（`".mp4"`）。
`get_extension` 的各兜底分支（`"mp4"` / `"ogg"` / `"zip"`）都不带点，末尾统一补一个点，
于是 mime 能被识别时补成双点：

| 输入 | 修复前 | 修复后 |
|---|---|---|
| 语音 `audio/ogg` | `..ogg` | `.ogg` |
| 视频 `video/mp4` | `..mp4` | `.mp4` |
| 文档 `application/pdf` | `..pdf` | `.pdf` |

后缀经 `module/download_entry.py` 的 `gen_file_name = app.get_file_name(...) + file_name_suffix`
原样进入最终文件名。

**实际影响范围**：仅在媒体**自身不带文件名**时触发（`module/download_entry.py:510`）。
查线上任务库 1567 条真实下载记录，双点文件名 **0 条** —— 该用户的媒体都自带文件名，
照片走硬编码 `jpg` 分支。即该缺陷真实存在但尚未在生产暴露，会在语音消息、
无文件名的视频、无扩展名的文档上首次触发。

### 缺陷 2：过滤器的 `file_extension` 字段带点（已在生产暴露）

`module/pyrogram_extension.py:1303` 以 `dot=False` 调用，语义是"要不带点的扩展名"，
用于填充 `meta_data.file_extension`；而该字段是**下载过滤器的可用变量**
（`utils/meta_data.py:96,116`）。

修复前该调用返回 `'.mp4'`（mime 可识别时）或 `'mp4'`（走兜底时）—— 取值不一致。
后果是用户写 `file_extension == "mp4"` 这类过滤条件，对正常 mp4 视频**永远匹配不上**，
反而对 mime 识别不出来的视频能匹配上。

### 缺陷 3：mime 为 None 时崩溃

`mimetypes.guess_extension(None)` 抛 `AttributeError: 'NoneType' object has no attribute 'lower'`。
`module/download_entry.py` 用 `getattr(media_obj, "mime_type", "")` 取值，属性存在但为 `None` 时即命中。

### 修复

只改 `module/pyrogram_extension.py` 的 `_guess_extension` 一处（该函数全仓库仅一个调用者）：
剥掉前导点并对空 mime 返回 `None`，使"扩展名"在整条路径上始终保持不带点的形式，
补点只发生在 `get_extension` 末尾一处。三个缺陷一并解决。

回归测试：`tests/module/test_pyrogram_extension.py`（自废弃分支收回，6 个用例）。
验证：全量 4 failed / 795 passed，无新增失败（4 个为第八节所述的已知过期断言）。

### 废弃分支处置

`arch-review-remediation` 上另有两个文件，经核查无保留价值，随分支一并废弃：

- `tests/module/test_bot_config.py`（102 行）—— 覆盖的 P0-4 两个缺陷已于本日修复，
  并已有等价回归测试 `tests/module/test_bot_commands.py`，内容重复。
- `tests/module/test_bot_workflows.py`（3262 行）—— 原评审 R5-3 的测试文件拆分，
  属于组织结构调整而非新增覆盖；这些用例在主线上仍位于 `tests/module/test_comment_workflow.py`
  并正常通过，内容未丢失。

`docs/architecture-review-2026-07-07.md` 与 `tests/module/test_pyrogram_extension.py`
已取回主线，该分支至此可安全删除。

## 十、过期测试断言全部对齐，套件转绿（2026-08-31）

第八节列出的 4 个报红已全部处理，**未改动任何产品代码**。每条在改断言前都先复核了
对应产品行为确实是有意设计，而非为让红转绿放宽断言。

### 处置明细

| 用例 | 改动 | 产品行为的意图依据 |
|---|---|---|
| `test_get_media_meta_uses_comment_naming_context_for_video` | `file_name` 去掉 `Discussion/2026_06/zhyseseb/`；`temp_file_name` 去掉 `zhyseseb/`（`Discussion/` 保留） | `module/download_entry.py` 中 `file_save_path = app.save_path` 分支带有明确注释说明跳过 channel/date 前缀；`build_name_for_strategy` 的 RECOMMENDED 分支返回 `{post_id}-{title}/{id} - {file}`，不含频道名 |
| `test_get_media_meta_uses_package_naming_context_for_video` | `file_name` 去掉 `Private/2026_06/`；`temp_file_name` 不变 | 同上。临时目录仍按 `dirname` 分层，故 `temp` 路径中的 `Private/` 是正确的 |
| `test_download_prepared_messages_preserves_planned_later_caption_for_package_naming_context` | MONTH_CAPTION 的 `expected_suffix` 去掉 `私密频道/2026_06/` | `b4ebf98` 手工删除了 `build_package_name_for_strategy` 中 `channel` 变量定义与 `f"{channel}/{month_for_comment(message)}/..."` 拼接 |
| `test_rclone_upload_uses_exec_and_return_code_success` | 期望 argv 末尾补 `"--transfers", "1"` | `config.example.yaml:46,56` 将 `rclone_transfers` 做成带注释的用户可配置项（"caps connections per rclone process"），`module/cloud_drive.py:210-211` 据此构造参数 |

该 rclone 用例原有的 `reject_shell` 断言与恶意文件名 `odd name 'quoted';$(touch nope).txt`
**原样保留** —— 那是防 shell 注入的防线，不在本次改动范围内。

### 当前基线

```
799 passed, 1 skipped, 0 failed
```

唯一的 skip 是 `test_windows_filename_too_long` 的正当平台闸门（`skipIf` 非 Windows）。

**至此主线测试套件全绿。** 后续任何报红都是新引入的回归，不再需要区分「本来就红的」与「刚改坏的」。

### 仍待处置

- `tests/test_media_downloader.py` 中被整段注释掉的 `test_upload_telegram_chat`
  （连同 6 个 `@mock.patch` 装饰器），不参与收集。需单独判断是恢复还是删除。
