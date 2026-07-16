# Web 全频道包库设计

## 1. 目标

在现有 Web 控制台新增独立的“频道库”视图。用户提交当前 Telegram 账号可见的频道或超级群中的任意一条消息链接后，系统识别会话并对其全部可见历史执行一次低频全量扫描，持久化媒体元信息，按照现有资源包规则形成可长期使用的频道包库。

用户可以在扫描过程中浏览和筛选已经稳定识别的包；首次全量扫描结束前不能发起下载。扫描完成后，用户可以跨分页选择当前频道中的包，并通过现有推荐 C 命名和串行包下载链路下载。以后可手动执行增量扫描，只收录上次扫描快照之后的新消息。

本设计优先保证：

- 首次扫描对 Telegram 请求频率保守；耗时不设硬性目标。
- 扫描进度、候选包、失败区间和下载状态都能跨进程重启恢复。
- 包边界、支持的媒体类型、命名和实际下载继续复用现有逻辑。
- 多个频道可进入包库，但全局同一时间只运行一个频道扫描。
- 频道扫描是低优先级工作；普通下载或包下载运行时自动让行。

## 2. 已确认的用户决策

- 链接只用于识别频道；首次扫描覆盖该账号当时可见的完整历史，而不是从链接消息开始。
- 支持 Telegram 频道和超级群，不支持普通私聊。
- 扫描任务、检查点和结果持久化；进程重启后自动续扫。
- 首版筛选字段：标题关键词、发布时间、消息 ID、媒体数量、已知总大小和下载状态。
- 扫描结果形成持久化频道包库，可反复打开、筛选和分批下载。
- 扫描中可浏览和筛选稳定包；首次全量扫描结束前禁止提交下载。
- 支持暂停、继续和停止；停止保留数据和检查点，删除频道包库是独立操作。
- 包级下载状态持久化；默认阻止误重复下载，但允许显式重新下载。
- 首次全量完成后通过按钮手动执行增量扫描，不做后台定时扫描。
- 完全沿用现有资源包规则及支持媒体类型，包内可包含视频、图片、文档等媒体。
- 可添加多个频道；扫描全局串行，后提交的任务排队。
- 扫描遇到下载活动时自动暂停，下载空闲后继续。
- 首次全量每批读取 50 个消息 ID，批间随机等待 4-6 秒；增量扫描每批 50 个消息 ID，批间随机等待 1-2 秒。
- 单批失败自动退避重试；最终失败则记录失败区间并继续，支持以后补扫。
- 页面采用独立“频道库”Tab，左侧频道列表，右侧扫描状态、筛选和包列表。
- “全选”作用于当前全部筛选结果并跨分页生效；切换筛选条件不清除已有选择。
- 一次下载批次只处理当前频道，按消息顺序串行下载。
- 包可展开查看消息 ID、媒体类型、原文件名、大小和时长等元信息；首版不抓缩略图。

## 3. 范围

### 3.1 包含

- 新的 Web 频道库页面和导航入口。
- 频道/超级群链接解析、权限验证和去重。
- 低频全量扫描、增量扫描、暂停、继续、停止、自动让行和失败区间补扫。
- 独立 SQLite 持久化频道、扫描、媒体元信息、包索引、选择和包下载尝试。
- 扫描中稳定包的渐进展示。
- 包级筛选、跨分页选择、批量下载和显式重新下载。
- 频道库下载批次接入现有 Web 任务中心、文件进度、上传和取消链路。
- 页面和 API 登录保护、输入校验、错误摘要与可操作状态。
- 单元、集成、恢复、API、前端和回归验证。

### 3.2 不包含

- Telegram 私聊扫描。
- 自动定时增量扫描。
- 多频道并行扫描。
- 扫描未完成时下载。
- 缩略图、视频在线播放或媒体内容预取。
- 用户自定义包规则或命名模板。
- 跨频道下载购物车。
- 重写现有普通链接、评论链接和有限 Prescan 工作流。
- 生产数据库的外部服务化或多进程 Web 部署支持。

## 4. 总体架构

新增 `channel_library` 业务边界，负责长期索引；现有任务中心和下载器继续负责媒体下载。

扫描调度器、Telegram 元信息扫描器、包索引器、下载桥接器和共享 Telegram I/O gate 都运行在 downloader 的 `Application.loop` 上。Flask 仍运行在独立线程，只负责同步校验、数据库命令写入，并通过现有线程安全调度入口唤醒 `Application.loop`；禁止在 Flask 线程创建 Pyrogram task、asyncio queue 或第二个事件循环。应用启动时只创建一个长期 scheduler task，关闭时显式停止并 `await` 它。

### 4.1 Web 频道库

职责：

- 添加、切换和删除频道库。
- 展示扫描队列、进度、自动暂停原因和失败区间。
- 提交全量、增量、暂停、继续、停止和补扫命令。
- 对包进行服务端筛选、跨分页选择和下载批次提交。

Web 页面不持有 Pyrogram `Message` 对象，也不把大量包或媒体一次性载入浏览器。

### 4.2 扫描调度器

职责：

- 全局只授予一个频道扫描槽。
- 按创建时间调度排队任务。
- 普通下载或包下载存在活动节点时，将当前扫描切换为 `auto_paused_download`；下载空闲后自动重新排队。
- 进程启动时把中断前的 `running` 和 `auto_paused_download` 扫描恢复为 `queued`；用户主动暂停的任务保持暂停，停止的任务不自动恢复。

调度器只决定何时运行，不执行 Telegram 请求或包规划。

“观察到活动下载再暂停”不足以消除竞态，因此新增运行在 `Application.loop` 上的下载优先 `TelegramActivityGate`：

- 普通下载、包下载、现有链接预览中的 Telegram 读取在请求前登记高优先级 intent。
- 频道扫描每一批在发请求前申请低优先级 permit；存在下载 intent、排队下载或下载中的媒体请求时不得取得 permit。
- 下载 intent 到达后立即阻止下一扫描批；如果单次扫描 API 已经发出，下载等待该调用释放 permit 后开始，不强行取消请求。
- gate 由 downloader 入队、worker 开始/结束和相关预览读取路径共同维护；不得用无锁的 `get_active_task_nodes()` 或任务表 active 数量推断。
- 纯云盘上传不占用 Telegram gate，不阻塞扫描；Telegram 媒体下载的 queued 和 in-flight 状态都会阻塞扫描。

这样可以证明扫描 API 与 Telegram 下载/预览 API 不并发，同时不会改变现有多个下载 worker 之间的并发策略。

### 4.3 Telegram 元信息扫描器

首次全量扫描采用可恢复的升序消息 ID 窗口：

1. 解析链接并调用 `get_chat` 验证会话类型和权限。
2. 读取当前最新可见消息，记录不可变的 `snapshot_max_message_id`。
3. 从消息 ID 1 开始，每次调用 `get_messages` 读取连续 50 个 ID。
4. 空消息、删除消息和不可见消息作为正常缺口，不创建媒体记录。
5. 对受支持媒体提取包规划和明细展示所需元信息。
6. 在同一数据库事务中写入媒体元信息并把 `next_message_id` 推进到下一批；事务成功后才算完成该批。
7. 首次全量批间随机等待 4-6 秒；增量和补扫批间随机等待 1-2 秒。

升序 ID 窗口使扫描顺序与现有包规划顺序一致，也使失败区间、检查点和补扫边界明确。消息 ID 缺口会增加扫描耗时，但不会增加单次请求频率；“时间不限、优先降低风险”的用户决策允许这一取舍。

首次全量任务只扫描到创建任务时记录的 `snapshot_max_message_id`。扫描期间的新消息不改变本次终点，完成后由增量扫描收录，避免一个持续增长的频道导致全量任务永不结束。

每次 Telegram 批读取必须在 `TelegramActivityGate` 内执行。数据库写入、包索引和批间 sleep 不持有 gate。任务存在 `wait_until` 时，调度器在绝对截止时间之前不得领取；该约束跨进程重启保持。

增量扫描从已完成库的 `fetched_through_message_id + 1` 开始，并在创建任务时重新记录新的 `snapshot_max_message_id`。为正确处理旧尾包被新无标题媒体延长的情况，包索引会从最后一个稳定包的起点或最后一个未完成包的起点重新计算重叠尾部，并独立推进 `indexed_through_message_id`。

### 4.4 包边界索引器

扫描器只保存元信息；索引器负责调用现有包规则。

- 持久化媒体记录通过明确的 `PersistedMessageAdapter` 还原：`id`、`empty=False`、`caption`、`media_group_id`、可被现有 `_media_name` 识别的 `media` 值，以及与类型同名的 `video/photo/document/...` 属性。对应属性是包含 `file_name`、`file_size`、`mime_type`、`duration`、`width`、`height` 的 `MediaDTO`，其他媒体属性为 `None`。
- 索引器从上次稳定边界后的尾部开始，调用现有 `plan_message_package` / `plan_message_package_sequence`。
- 发现“下一包起点”后，前一包才标记为 `stable` 并发布到 Web。
- 当前扫描前沿的最后一个包标记为 `provisional`，可以展示但不能选择。
- 到达扫描快照终点时，最后一个非空包转为 `stable`。
- 失败区间对应完整不确定闭包内的包保持 `uncertain`；补扫并重新索引后才能转为 `stable`。

不复制标题相似度、caption 继承、专辑 caption、媒体类型或大小汇总算法。若现有规划器的输入协议不足，只提取供现有 Prescan 和频道库共同调用的纯辅助函数，避免产生两套边界规则。

现有规划器默认 500 条上限不能成为频道库边界。索引器对“当前未稳定尾包 + 下一包首项”传入实际完整长度加一；达到任意规划窗口或出现 `scan_warning` 时绝不能把包标为 `stable`。连续同标题媒体超过 500 条时保持一个持久化 provisional 尾包，直到看到真实下一包边界或到达扫描快照终点。若完整尾部加载成为现实内存问题，再把现有边界判定抽为 Prescan 与频道库共用的增量状态机；首版不得通过静默拆包规避。

失败区间建立“不确定闭包”：记录失败前最近包起点作为 `reindex_anchor_start`，从该点开始的派生包均为 `uncertain`，直到失败区间之后观察到两个连续、可证明的新包边界，或到达扫描快照终点。补扫必须从 anchor 重算完整闭包，并在同一事务更新包 revision、索引水位和 failure 状态；不能只重算紧邻两包。

### 4.5 下载桥接器

下载桥接器不直接下载文件：

1. 验证首次全量状态为 `ready` 或 `partial`，并拒绝 `provisional`、`uncertain` 包。
2. 验证选择只属于当前频道；已完成包必须携带显式 `redownload=true` 才能再次加入批次。
3. 按包起始消息 ID 排序，在频道库数据库中创建不可变批次快照和 outbox 记录，再幂等创建现有 Web 任务。
4. 按每个包保存的消息 ID 重新调用 Telegram 获取实时 `Message` 对象。
5. 使用保存的包标题、起始 ID 和现有 `PackageNamingContext` 构造推荐 C 命名上下文。
6. 调用兼容性扩展后的现有串行包下载函数；下载、上传、删除、取消和文件进度仍由现有链路负责。
7. 将任务结果回写到包下载尝试和包的当前下载状态。

重新读取消息失败时，只影响对应包/媒体的下载结果，不篡改扫描索引；用户可在失败后显式重试。

两个 SQLite 之间不声明原子事务。采用持久化 outbox/saga：浏览器为提交提供 `Idempotency-Key`；频道库事务用唯一键创建 `pending_dispatch` 批次、确定性 `task_id` 和包 revision/标题/消息 ID 的不可变快照；提交后对 `web_tasks.sqlite3` 幂等 upsert 同一 `task_id`，成功再把批次标为 `dispatched`。启动时对所有 `pending_dispatch` 重放，同一确定性 task ID 不会产生第二任务；Web 任务只在频道批次提交之后创建，因此不存在合法的“无频道批次 Web 任务”。

现有 `download_prescan_packages` 必须增加向后兼容的可选包生命周期接口：`on_package_started(attempt_id, package_snapshot)` 和 `on_package_finished(attempt_id, message_results)`，并返回每包结果。父 `TaskNode` 只在最外层注册/完成一次；内层包下载不得在第一包后移除父节点或把 Web 任务提前置为终态。包结果按该包预期 message ID 集合和 FileSnapshot 计算，不读取父节点累计计数。

## 5. 持久化模型

新增独立的 `channel_library.sqlite3`，不迁移、不复用现有 `web_tasks.sqlite3`。使用 SQLite WAL、外键和短事务，新增 `schema_meta` 记录 schema 版本。

### 5.1 `channel_libraries`

- `id`: 内部整数主键。
- `chat_id`: Telegram 数字会话 ID，唯一去重键。
- `chat_type`: `channel` 或 `supergroup`。
- `username`, `title`, `source_link`: 展示与审计字段。
- `status`: `new`, `indexing`, `ready`, `partial`, `paused`, `stopped`, `failed`。
- `fetched_through_message_id`: 已提交元信息事务的最高消息 ID。
- `indexed_through_message_id`: 已提交派生包事务的最高消息 ID。
- `index_revision`: 每次派生包变更时递增。
- `last_full_scan_at`, `last_incremental_scan_at`。
- `created_at`, `updated_at`。

重复提交同一 `chat_id` 不创建第二个库，而是打开已有库；若首次全量未完成，返回现有扫描状态。

### 5.2 `channel_scan_jobs`

- `id`, `library_id`。
- `kind`: `full`, `incremental`, `repair`。
- `status`: `queued`, `running`, `paused_user`, `auto_paused_download`, `waiting_rate_limit`, `stopped`, `completed`, `partial`, `failed`。
- `snapshot_max_message_id`, `start_message_id`, `next_message_id`。
- `fetched_through_message_id`, `indexed_through_message_id`, `index_revision`。
- `scanned_id_count`, `visible_message_count`, `media_count`, `stable_package_count`。
- `retry_count`, `wait_until`, `wait_reason`, `last_error`。
- `created_at`, `started_at`, `updated_at`, `completed_at`。

同一频道同一时间只允许一个可恢复任务。数据库部分唯一索引覆盖 `queued`, `running`, `paused_user`, `auto_paused_download`, `waiting_rate_limit`, `stopped`；新任务必须复用或明确终结旧 stopped 任务。`completed`, `partial`, `failed` 是终态。

媒体数据与 `fetched_through_message_id` 同事务提交；派生包、`indexed_through_message_id` 和 `index_revision` 同事务提交。只有两个水位均追上 `snapshot_max_message_id`，尾包已稳定或不确定闭包已登记，才在同一事务把 job/library 置为 `completed/ready` 或 `partial`。抓取完成但索引未完成的重启会从索引水位继续，不重复 Telegram 请求。

### 5.3 `channel_media_messages`

复合唯一键：`(library_id, message_id)`。

保存：

- `message_id`, `message_date`。
- `media_type`, `media_group_id`。
- `caption`, `file_name`, `file_size`, `mime_type`。
- `duration`, `width`, `height`（Telegram 未提供时为 `NULL`）。
- `raw_fingerprint`: 对影响包规划的字段计算稳定摘要，用于增量重算时判断是否变化。
- `first_seen_at`, `updated_at`。

不保存媒体二进制、缩略图、Telegram 文件下载路径、token 或 session 数据。

### 5.4 `channel_packages`

- `id`, `library_id`。
- `start_message_id`, `end_message_id`，频道内起始 ID 唯一。
- `title`, `published_at`。
- `boundary_status`: `stable`, `provisional`, `uncertain`, `superseded`。
- `media_count`, `known_total_size`, `unknown_size_count`。
- `current_download_status`: `never`, `queued`, `downloading`, `completed`, `outdated`, `failed`, `cancelled`。
- `has_successful_attempt`, `completed_revision`, `last_successful_at`。
- `last_download_task_id`, `last_downloaded_at`, `download_attempt_count`, `superseded_by_package_id`。
- `index_revision`, `created_at`, `updated_at`。

包是从媒体元信息派生的数据。相同 `start_message_id` 的包原位 UPSERT 并递增 revision；拆分或合并造成身份变化时，旧包标记 `superseded` 而不是删除。下载批次永远引用创建时的不可变 revision 和消息 ID 快照。重算范围与正在下载的包重叠时，先完成/取消该批次再发布新 revision。

包成员变化会清除受影响的当前选择并返回可展示原因。若旧 revision 曾下载成功，新 revision 的状态为 `outdated`；再次下载必须显式确认。`has_successful_attempt` 不可因后续失败而回退，因此“成功后重下失败”仍不能绕过重复下载保护。

### 5.5 `channel_package_items`

- `library_id`, `package_id`, `message_id` 复合唯一。
- `ordinal`, `media_type`。
- `caption_for_naming`, `original_caption`, `inherited_caption`。

文件名、大小、时长等明细通过 `(library_id, message_id)` 复合外键关联媒体表，不重复存储。包项同时用 `(library_id, package_id)` 约束属于同一频道，避免不同频道复用 message ID 时串联。

### 5.6 `channel_scan_failures`

- `id`, `job_id`, `library_id`。
- `start_message_id`, `end_message_id`。
- `attempt_count`, `last_error`, `status`: `open`, `repairing`, `resolved`。
- `reindex_anchor_start`, `uncertain_through_message_id`。
- `created_at`, `updated_at`, `resolved_at`。

相邻失败批次合并为连续区间。补扫成功后将区间标记为 resolved，并重新索引完整不确定闭包。

`channel_scan_repair_targets` 用 `(job_id, failure_id)` 唯一键保存多个非连续失败区间各自的 `next_message_id` 和状态。repair job 可选择指定 failure ID，默认领取全部 open failure；逐目标持久化进度。

### 5.7 选择与下载批次

`channel_package_selections` 使用 `(library_id, package_id)` 唯一键并保存 `package_revision`，使选择跨分页、筛选切换和页面刷新保留；revision 变化时选择失效并记录原因。

`channel_download_batches` 保存频道、确定性 Web `task_id`、客户端 `idempotency_key`、`dispatch_status`、状态、是否允许重新下载、创建和完成时间；`(library_id, idempotency_key)` 唯一。

`channel_download_batch_packages` 保存批次内包、package revision、标题、起止 ID、顺序和该次尝试状态。`channel_download_batch_items` 保存该次不可变 message ID/caption 命名快照。历史尝试不覆盖，包表只保存最新状态摘要。

## 6. 扫描状态与控制

### 6.1 用户暂停、自动暂停和停止

- `暂停`: 当前批完成后变为 `paused_user`，不会自动恢复。
- `继续`: 将 `paused_user` 或仍有检查点的 `stopped` 任务重新排队。
- `自动让行`: 调度器发现活动下载后在批边界切换为 `auto_paused_download`，下载空闲后自动排队。
- `停止`: 当前批完成后把任务标为 `stopped`，保留元信息、包、失败区间和检查点，但不自动恢复。
- `删除频道库`: 需要二次确认；只有该库没有运行中的扫描或下载批次时才能删除数据库记录。媒体文件和既有任务历史不随频道库删除。

所有控制都在批边界生效，不强行中断正在进行的 Telegram API 请求或数据库事务。

完整状态迁移：

- `queued -> running | paused_user | stopped | failed`。
- `running -> queued | paused_user | auto_paused_download | waiting_rate_limit | stopped | completed | partial | failed`。
- `auto_paused_download -> queued | paused_user | stopped | failed`。
- `waiting_rate_limit -> queued | paused_user | stopped | failed`，且 `wait_until` 未到时不能转 queued/running。
- `paused_user -> queued | stopped`。
- `stopped -> queued` 只恢复同一个 job；存在 stopped job 时不能创建 full/incremental/repair 新任务。
- `completed`, `partial`, `failed` 为终态；failed 修复外部原因后通过“重试”创建从持久化水位继续的新同类任务。

首次 full 未达到 completed/partial 前禁止 incremental。repair 只允许库为 partial 且存在 open failure 时创建。非法状态命令返回 `409 state_conflict`；对象不存在返回 404；输入错误返回 400。

### 6.2 重启恢复

应用启动时执行一次恢复：

- `running` -> `queued`。
- `auto_paused_download` -> `queued`，调度器会再次判断下载活动。
- `waiting_rate_limit` 保持原状态和绝对 `wait_until`；到期前不领取。
- `queued` 保持排队。
- `paused_user`、`stopped` 和终态保持不变。
- 已经写入元信息但未推进检查点的批次会被幂等重放；复合唯一键阻止重复数据。

检查点和批次数据必须同事务提交，禁止出现“检查点已推进、数据未写入”的不可恢复状态。

### 6.3 失败和限流

- `FloodWait`: 在事务中保存绝对 `wait_until`、等待原因和 Telegram 指定时长加 1-3 秒随机缓冲，状态改为 `waiting_rate_limit` 并释放扫描槽；不计入普通重试次数，重启不得提前重试。
- 网络/临时 RPC 错误: 最多重试 3 次，采用 5 秒、15 秒、45 秒退避并附加小幅随机抖动。
- 单批最终失败: 记录消息 ID 区间，继续下一批；任务最终为 `partial`。
- 权限失效、频道不可访问、会话未登录: 立即暂停为 `failed`，不继续发请求。
- SQLite 写入失败: 不推进检查点，任务变为 `failed`；恢复前不得继续扫描。
- 包规划异常: 保留原始元信息，任务变为 `failed`，允许修复代码后从索引检查点重建，不重新请求 Telegram。

`partial` 库允许筛选和下载远离失败区间的 `stable` 包；失败区间相邻的 `uncertain` 包不可选择，直到补扫成功。

## 7. Web API

所有接口继续使用现有 Web 登录保护。错误响应使用稳定的机器码和可读摘要，不返回 token、session、原始配置秘密或完整异常堆栈。

所有新增状态变更接口同时要求 session 绑定的同步 CSRF token，并通过 `X-CSRF-Token` 提交；使用现有 `secrets` 能力生成，不新增依赖。登录保护和 `SameSite=Lax` 不能替代 CSRF 校验。

### 7.1 频道与扫描

- `GET /api/channel-libraries`: 分页返回频道库及当前/最近扫描摘要。
- `POST /api/channel-libraries`: `{"link": "https://t.me/..."}`，解析并创建或返回已有频道库，同时为新库排队首次全量扫描。
- `GET /api/channel-libraries/<library_id>`: 返回频道、扫描、计数和错误摘要。
- `DELETE /api/channel-libraries/<library_id>`: 请求体必须包含 `confirm_library_id` 和读取详情时获得的 `library_version`，服务端再次验证无活动扫描/下载后删除；版本变化返回 409。
- `POST /api/channel-libraries/<library_id>/scans`: `mode=incremental|repair|retry`；repair 可带 `failure_ids`，默认全部 open failure。
- `POST /api/channel-scans/<job_id>/pause`。
- `POST /api/channel-scans/<job_id>/resume`。
- `POST /api/channel-scans/<job_id>/stop`。

首次全量由创建频道库自动发起，不额外暴露可绕过保守频率的客户端参数。批大小和等待范围属于服务端配置，首版 Web 页面不提供速度档位。

### 7.2 包查询和明细

- `GET /api/channel-libraries/<library_id>/packages`。
- 查询参数：`q`, `date_from`, `date_to`, `message_id_min`, `message_id_max`, `media_count_min`, `media_count_max`, `size_min`, `size_max`, `include_unknown_size`, `download_status`, `cursor`, `page_size`。
- 默认按 `(start_message_id DESC, id DESC)` 使用 keyset cursor；`page_size` 默认 50，最大 200。响应返回 `next_cursor` 和 `library_revision`；revision 变化时客户端提示结果已更新并从第一页重载，不使用会在扫描中漂移的 offset 页码。
- `GET /api/channel-libraries/<library_id>/packages/<package_id>/items` 分页返回媒体明细。

包列表返回 `selectable` 和不可选原因。扫描期间 `stable` 包可预选，`provisional`/`uncertain` 不可选；下载提交仍受首次全量完成门槛约束。

筛选语义固定：`q` 对规范化标题做不区分大小写的子串匹配；时间以 UTC 保存，`date_from` 含起点、`date_to` 不含终点；消息 ID 条件按包区间相交判断；数量边界均包含；大小筛选只比较已知总大小，存在未知大小的包默认排除，只有 `include_unknown_size=true` 才保留并标记结果不精确。`partial` 表示本轮已到快照终点但存在失败区间，属于可浏览/有限下载的终态，不等同于仍在扫描。

### 7.3 选择与下载

- `PUT /api/channel-libraries/<library_id>/selection/packages/<package_id>`: 设置单包选择状态。
- `POST /api/channel-libraries/<library_id>/selection/select-filtered`: 使用与包查询相同的筛选对象选择全部匹配稳定包。
- `POST /api/channel-libraries/<library_id>/selection/clear`: 清空当前频道选择。
- `GET /api/channel-libraries/<library_id>/selection`: 返回选择数量、媒体数和已知总大小。
- `POST /api/channel-libraries/<library_id>/download-batches`: 提交当前选择，要求 `Idempotency-Key`，可选 `redownload=true`。

服务端必须重新执行筛选和可选性校验，不能信任浏览器传来的包计数或状态。只要包历史上有成功尝试或状态为 `outdated`，没有 `redownload=true` 就拒绝；显式重下确认失败后仍保留历史成功事实。批次通过 4.5 的 outbox/saga 跨库派发，不宣称跨库原子性。

## 8. Web 页面设计

现有 `module/templates/index.html` 单页导航新增 `data-tab="channel-library"` 面板，不创建第二个前端路由；保留当前 Industry 蓝图视觉体系和桌面优先的信息密度。频道库轮询只在该 Tab 激活时运行。

### 8.1 左侧频道列表

- 添加频道链接输入和提交按钮。
- 频道标题、类型、扫描状态、包数量和更新时间。
- 排队、扫描、自动暂停、用户暂停、部分完成、就绪、失败等状态标签。
- 多频道切换不丢失服务端选择。

### 8.2 右侧工作区

顶部：频道标题、全量/增量状态、进度、扫描速率说明和控制按钮。

筛选条：标题关键词、时间、消息 ID、媒体数量、总大小、下载状态；支持清除筛选。

选择摘要：已选包数、媒体数、已知大小；提供“全选全部筛选结果”“清空选择”“下载所选”。扫描未完成时下载按钮禁用并说明原因。

包表：选择框、包号/起始 ID、消息范围、标题、发布时间、媒体数、大小、边界状态和下载状态。点击展开后通过独立分页接口加载媒体明细，不把全频道文件列表嵌入页面。

### 8.3 交互约束

- 列表、包和明细均使用稳定分页，不因状态刷新重排已打开的行。
- 扫描状态轮询频率沿用任务页的 1 秒上限；包列表仅在版本号变化或用户操作时刷新，避免每秒重查大表。
- 所有标题、文件名和错误文本按不可信输入转义。
- 删除、重新下载和包含大量匹配结果的“全选”显示明确确认信息。
- 移动端允许左侧频道列表折叠为切换菜单，但首版不改变桌面主布局。

## 9. 下载状态一致性

- 频道库下载批次创建后立即把选中包标记为 `queued` 并记录批次关系。
- 现有任务进入下载时标记当前包 `downloading`。
- 包内全部媒体完成且现有任务没有该包失败项时标记 `completed`；存在失败项则标记 `failed`。
- 用户取消尚未开始或进行中的批次时，未完成包标记 `cancelled`；已完成包保持完成。
- 服务重启后通过批次绑定的 Web 任务状态进行一次对账；没有可证明完成证据的 `queued/downloading` 包降为 `failed`，不误标完成。
- 显式重新下载创建新的尝试记录；历史完成记录不删除，包摘要显示最新尝试状态和总尝试次数。

包完成语义按该 revision 的预期 message ID 集合判断：消息读取失败、`FailedDownload`、`skip_not_found` 或用户取消均不能算完成；完整本地文件导致的可接受 skip 可算下载完成。若配置启用云盘上传，任一应上传文件的 `UPLOAD_FAILED` 使该包尝试为 failed；只有下载及已启用上传链路都成功才标记 completed。回调从包级 message result/FileSnapshot 读取，不从父节点累计数推导。

## 10. 并发、资源与安全边界

- 一个进程内只有一个在 `Application.loop` 上启动的频道扫描 scheduler/worker；进程锁和任务生命周期防止重复启动，数据库唯一状态约束防止重复任务。首版不使用数据库租约，也不支持多个应用进程共享调度。
- 每批最多持有 50 个 Telegram 消息对象；落库后释放。包索引只加载上次稳定边界之后的媒体尾部。
- SQLite 使用参数化查询、WAL、外键、忙等待超时和显式短事务。
- `channel_library.sqlite3` 创建后强制权限 `0600`，启动时发现权限过宽则收紧并记录不含敏感字段的日志。
- 不接受客户端指定 batch size、sleep、数据库路径、shell 命令或文件系统路径。
- 频道权限以当前运行的 Telegram session 为准；Web 登录用户不能切换 Telegram 身份。
- `hide_file_name` 打开时，API 和页面对原文件名使用现有脱敏规则；数据库仍保存下载命名所需原始元信息，数据库文件按现有运行目录权限保护。
- 删除频道库只删除索引数据，不删除下载文件、Telegram 消息或现有任务历史。

## 11. 配置

首版新增只读服务端配置，默认值固定为已确认的保守参数：

```yaml
channel_library:
  full_scan_batch_size: 50
  full_scan_delay_min_sec: 4
  full_scan_delay_max_sec: 6
  incremental_scan_batch_size: 50
  incremental_scan_delay_min_sec: 1
  incremental_scan_delay_max_sec: 2
  transient_retry_delays_sec: [5, 15, 45]
```

配置加载必须做上下限校验，禁止把生产配置误设为无等待高频扫描。首版最小值：全量延迟不低于 2 秒，增量延迟不低于 0.5 秒，批大小不超过 100。

配置由 `Application.assign_config` 读取为已验证、运行期不可变的配置对象；整数和浮点延迟分别校验。首版不加入 `/api/settings` 的读取/写回界面，修改配置仍通过 `config.yaml` 并重启生效，同时更新 `config.example.yaml` 和运维文档。

数据库路径固定为运行目录下 `channel_library.sqlite3`，并沿用 `.gitignore` 的 `*.sqlite3*` 规则。

## 12. 测试与验收

### 12.1 纯逻辑测试

- 轻量持久化消息可以产生与真实消息相同的包边界、caption 继承、媒体组处理、类型和大小汇总。
- 包边界跨 50 条批次时只发布稳定包，尾包在终点正确稳定。
- 连续同标题单包超过 500 个媒体且跨多个批次时不被截断或提前稳定。
- 增量扫描通过尾部重叠正确延长旧尾包或创建新包。
- 失败区间从 `reindex_anchor_start` 到闭包终点的包变为 uncertain，补扫后完整重建并稳定。

### 12.2 存储与恢复测试

- 媒体写入和检查点推进原子提交。
- 抓取水位和索引水位独立恢复；抓取完成、索引提交前崩溃不会误标 ready。
- 同一批重放不产生重复媒体、包或下载批次。
- 重启后 running/auto-paused 自动排队，用户暂停和停止保持不变。
- 重复频道链接按 chat_id 去重。
- 尾部重算只替换受影响派生记录。

### 12.3 调度与错误测试

- 多频道任务严格串行。
- 下载 intent 与扫描批竞争 gate 时下载优先；扫描和 Telegram 下载/预览 API 不并发。
- FloodWait 按指定时间加缓冲等待。
- FloodWait 等待中重启仍遵守持久化绝对截止时间。
- 临时错误执行三次退避；最终失败记录区间并继续。
- 权限错误和数据库写入错误停止任务且不推进检查点。

### 12.4 API 与页面测试

- 未登录请求被拒绝。
- 所有筛选比较语义、keyset cursor、revision 变化、分页上限和输入边界正确；扫描中发布新包不会造成翻页重复或漏项。
- 全选作用于全部筛选结果，选择跨分页和页面刷新保留。
- 扫描未完成、包不稳定和重复下载请求被服务端拒绝。
- 明细分页只返回目标包的媒体，不复用现有 Prescan 的全任务文件列表。
- 标题、文件名和错误文本不产生存储型 XSS。
- 所有新增写接口拒绝缺失/错误 CSRF；删除拒绝错误确认 ID、旧 library_version 和活动任务竞态。
- 频道列表、扫描控制、筛选、选择、展开明细和下载提交流程在桌面及移动宽度下无重叠或溢出。

### 12.5 集成与回归测试

- 使用假 Telegram client 扫描至少 15,000 个消息 ID，验证 300 个批次、检查点、包计数和重启续扫，不执行真实等待。
- 验证完整工作流：链接 -> 全量 -> 筛选 -> 跨页选择 -> 串行下载桥接 -> 包状态回写。
- 对 outbox 的三个崩溃窗口做故障注入：频道事务前、频道事务后/Web task 前、Web task 后/标记 dispatched 前；重启后都只产生一个批次和一个确定性 task。
- 使用真实 TaskStateStore 集成验证多包批次不会在第一包后提前完成，并能逐包回写结果。
- 全量现有测试通过，普通链接、评论链接、有限 Prescan、任务中心、上传和配置不回归。
- 浏览器实际渲染频道库页面，验证空态、扫描中、自动暂停、部分完成、就绪、批量选择和下载中状态。

验收标准：

1. 15,000 消息 ID 的模拟全量扫描可中断并在重启后从已提交检查点继续，无重复包。
2. 真实节流参数在代码和配置中生效；首次全量默认 50 条/批、4-6 秒间隔。
3. 扫描活动与下载活动不并发发起频道历史请求。
4. 扫描结果跨服务重启存在，包筛选和选择仍可用。
5. 选中包按起始消息 ID 串行进入现有推荐 C 下载链路。
6. 失败区间可见、可补扫，不把边界不确定包误设为可下载。
7. 现有功能测试和新增测试全部通过。
8. 跨库派发、Telegram gate、包 revision、FloodWait 截止时间、CSRF 和数据库权限都有故障/竞态测试证据。

## 13. 部署与回滚

部署属于显式批准范围，但仍按可回滚步骤执行：

1. 停止服务后，使用 SQLite backup API/`.backup` 为现有 `web_tasks.sqlite3` 创建一致性备份并验证可打开；备份配置和 Telegram session。禁止在 WAL 活动时只复制主数据库文件。新库尚不存在时无需备份。
2. 推送代码并在服务器执行 fast-forward 更新。
3. 安装依赖（本设计不要求新增第三方依赖）。
4. 重启 `tg-downloader.service`，确认服务 active、Web 登录和现有任务 API 正常。
5. 若用户提供明确批准的受控小频道链接，创建测试库，验证首批低频扫描后停止并删除测试库；没有受控链接时不擅自扫描真实频道，改为验证登录后的新 API、数据库初始化、scheduler 单实例和现有功能 smoke。
6. 检查日志不存在高频循环、数据库错误、未脱敏秘密或持续异常。

回滚代码使用对应提交的 `git revert` 并重启服务。`channel_library.sqlite3` 是新增的独立文件；回滚代码时保留该文件，避免丢失扫描数据。确认不再需要后才能人工删除，删除前必须备份。

## 14. 已知限制

- 升序扫描按消息 ID 范围而非“实际消息条数”计费；删除消息很多的频道耗时会更长。
- 首版单进程调度，不支持多 Web worker 或多实例共享扫描槽。
- 增量扫描只收录新消息，不主动重新抓取历史消息的编辑或删除。
- 频道权限变化可能导致补扫或下载失败，系统不会绕过 Telegram 权限。
- 扫描包元信息不是下载成功保证；下载时消息可能已删除、权限可能已变化。

## 15. 对抗性审查处置

设计初稿完成后进行了三路独立只读审查：数据与恢复正确性、产品/运维/安全、现有代码适配。审查提出的问题均已纳入本版，而不是留到实施时猜测：

- 用 outbox/saga 和确定性 task ID 取代不可能实现的跨 SQLite 原子事务。
- 用下载优先的 `TelegramActivityGate` 消除“先检查再请求”的并发竞态。
- 拆分抓取与索引水位，并把 ready/partial 与尾包处理放入一致事务。
- 引入 package revision、superseded、outdated、不可回退成功事实和不可变下载快照。
- 把失败影响定义为可重建的不确定闭包，而不是模糊的相邻两包。
- 明确 >500 媒体长包不能因现有默认窗口被截断或提前稳定。
- 为现有串行包下载增加外层生命周期和逐包结果接口，禁止第一包后提前完成父任务。
- 增加 FloodWait 绝对截止时间、keyset cursor、完整状态迁移、repair targets、CSRF、0600 权限和一致性 SQLite 备份要求。
- 明确 Application.loop 生命周期、持久化消息适配器、上传失败语义及只读配置接入点。

审查修订后再次执行了占位符、旧术语、内部一致性、范围和 diff 格式检查；没有保留占位标记或未决实现分支。
