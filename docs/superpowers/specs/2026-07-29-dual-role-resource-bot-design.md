# 双角色资源发布 Bot 设计

**日期：** 2026-07-29  
**状态：** 已完成设计，待用户复核后实施

## 1. 目标

在保留两个 Telegram Bot 账号的前提下，重构现有 `module/bot.py` 为统一生命周期入口：

- 原管理 Bot 继续提供下载、预扫、过滤和其他现有管理能力。
- 新资源 Bot 仅向已激活用户提供频道绑定、资源包搜索和资源发布能力。
- 用户只需把资源 Bot 添加为自己频道的管理员并授予发帖权限，不需要让后台主账号加入目标频道。
- 资源发布默认由后台主账号读取和下载来源媒体，再由资源 Bot 上传到用户绑定的频道。
- 旧 `/forward` 公共入口被移除，不再作为资源发布能力的基础。
- 本轮施工完成本地实现、测试、配置示例和部署准备，停在生产服务器配置、重启和最终验收之前。

成功标准：

1. 一个应用生命周期统一启动和停止管理 Bot、资源 Bot、资源发布队列。
2. 没有第二套独立程序入口，也没有第二套未被统一管理的全局 Bot 生命周期。
3. 资源 Bot Token 缺失时，原管理 Bot 和现有下载/Web 能力保持原行为。
4. 激活密钥只能兑换一次；激活用户持续有效，直至管理员撤销。
5. 每个激活用户第一版最多绑定一个目标频道。
6. 绑定时验证用户为频道创建者或管理员，并验证资源 Bot 具备频道发帖权限。
7. 用户可以按关键词搜索全部稳定资源包、分页浏览，并一键创建发布任务。
8. 发布任务使用后台主账号下载，资源 Bot 上传；保持包内顺序和 Telegram 媒体组。
9. 重复点击同一操作不会创建重复任务，失败任务返回稳定错误摘要且清理临时文件。
10. 真实 Token 不进入 Git、示例配置、日志或测试夹具。

## 2. 范围

本次包含：

- 统一 Bot 生命周期和角色边界。
- 移除 `/forward` 命令、Handler、帮助文案和命令菜单入口。
- 新增 `resource_bot_token` 配置。
- `.env.new` 的本地忽略保护。
- 激活密钥生成、兑换和用户撤销。
- 频道绑定、解绑和权限变化处理。
- 稳定资源包的关键词搜索、详情、分页和发布按钮。
- 持久化发布任务、串行 worker、进度和失败状态。
- 主账号下载媒体、资源 Bot 上传媒体。
- 单文件、普通消息序列和媒体组上传。
- 配置示例、中文说明文档、测试和 `progress.md`。

本次不包含：

- 生产服务器配置变更、服务重启或线上验收。
- 把主账号添加到用户的目标频道。
- 把资源 Bot 批量添加到来源频道。
- 直接复制消息作为第一版优化路径。
- 多频道绑定、批量选择多个资源包或定时发布。
- Web 管理界面中的激活密钥或资源 Bot 管理页面。
- 修改 `/listen_forward` 和 `/forward_to_comments` 的现有公共入口。
- 修改来源频道库索引、资源包边界或现有下载到云盘行为。

## 3. 方案选择

### 3.1 采用方案：主账号下载，资源 Bot 上传

主账号已经拥有来源资源频道的读取权限。资源 Bot 只需要拥有用户目标频道的发帖权限。一次发布的数据流为：

```text
channel_library.sqlite3
    -> 资源包和来源消息快照
后台主账号 Client
    -> 重新读取来源消息
任务独立临时目录
    -> 下载媒体文件
资源 Bot Client
    -> 上传到用户绑定频道
resource_bot.sqlite3
    -> 记录最终任务状态
```

选择该方案是因为它不要求主账号进入每个用户频道，也不要求资源 Bot 能访问全部私有来源频道。来源禁止原生转发但仍允许主账号下载时，也走相同路径。

### 3.2 暂不采用：主账号原生转发

主账号原生转发要求主账号同时能够访问来源和目标频道，不符合“用户只添加资源 Bot”的产品边界。

### 3.3 暂不采用：资源 Bot 直接复制

资源 Bot 直接复制要求资源 Bot 同时能访问来源和目标。当前资源库中的私有频道和评论讨论组不保证满足这一条件。该路径可在第一版稳定后作为性能优化单独设计。

## 4. 统一 Bot 生命周期

`module/bot.py` 继续是下载应用唯一的 Bot 入口，保留现有外部函数名：

```python
async def start_download_bot(app, client, add_download_task, download_chat_task)
async def stop_download_bot()
```

内部改为一个统一管理对象：

```text
BotManager
├── admin_role: DownloadBot
├── resource_role: ResourceBotRole | None
└── delivery_service: ResourceDeliveryService | None
```

规则：

- `bot_token` 创建原管理 Bot。
- `resource_bot_token` 创建资源 Bot。
- `resource_bot_token` 为空时不创建资源角色和发布服务。
- `start_download_bot` 依次启动管理角色、资源存储、发布 worker、资源角色。
- 启动任一步失败时，按相反顺序清理已启动组件。
- `stop_download_bot` 停止接收新任务，等待当前 Telegram 请求完成或安全中断，再停止两个 Bot Client。
- 现有管理 Bot Handler 可以在第一阶段继续使用 `module/bot.py` 内部兼容状态，但不得再创建独立的启动/停止入口。
- 新资源 Bot 的 Handler 和状态不写入现有 `DownloadBot.pending_*` 字典。

`module/download_runtime.py` 仍只调用一次 `start_download_bot` 和一次 `stop_download_bot`，不感知有两个 Bot 账号。

## 5. 配置与秘密

`Application` 新增：

```python
self.resource_bot_token: str = ""
```

从 `config.yaml` 读取：

```yaml
bot_token: 原管理Bot的Token
resource_bot_token: 新资源Bot的Token
```

`config.example.yaml` 只写：

```yaml
bot_token: your_bot_token
resource_bot_token: your_resource_bot_token
```

本地 `.env.new`：

- 仅作为当前真实 Token 的临时来源。
- 加入 `.gitignore` 的精确规则 `/.env.new`。
- 不由应用自动加载。
- 不被复制到测试、文档或日志。
- 最终生产部署时，由用户接管并把其值写入服务器 `config.yaml`。

安全日志不得输出：

- Bot Token。
- 完整激活密钥。
- Telegram session 数据。
- 原始异常中可能包含的凭证或请求参数。

## 6. 资源 Bot 状态库

新增独立 SQLite 数据库 `resource_bot.sqlite3`，不修改 `channel_library.sqlite3` 的现有 schema。数据库使用外键、事务和显式 schema 版本。

### 6.1 `resource_activation_keys`

字段：

- `id`
- `key_hash`：完整随机密钥的 SHA-256 摘要，唯一
- `key_prefix`：仅用于管理员识别的短前缀
- `status`：`available`、`redeemed`、`revoked`
- `created_by`
- `redeemed_by`
- `created_at`
- `redeemed_at`
- `revoked_at`

规则：

- 使用 `secrets.token_urlsafe(24)` 生成高熵密钥。
- 数据库不保存明文。
- 密钥只在创建命令的成功回复中显示一次。
- 一个密钥只能被一个 Telegram 用户成功兑换一次。

### 6.2 `resource_users`

字段：

- `telegram_user_id`，主键
- `status`：`active`、`revoked`
- `activation_key_id`
- `activated_at`
- `updated_at`
- `revoked_at`

激活默认无到期时间。管理员可手工撤销；再次启用必须使用新的激活密钥。

### 6.3 `resource_channel_bindings`

字段：

- `telegram_user_id`，主键
- `chat_id`，唯一
- `title`
- `username`
- `status`：`active`、`permission_lost`、`unbound`
- `bound_at`
- `updated_at`
- `last_verified_at`

每个用户只有一个活动绑定，每个频道也只绑定给一个激活用户。

### 6.4 `resource_delivery_jobs`

字段：

- `id`
- `public_id`，不可预测且唯一
- `idempotency_key`，唯一
- `telegram_user_id`
- `package_id`
- `package_revision`
- `target_chat_id`
- `status`：`queued`、`downloading`、`uploading`、`completed`、`failed`、`cancelled`
- `total_items`
- `downloaded_items`
- `uploaded_items`
- `error_code`
- `error_summary`
- `created_at`
- `started_at`
- `updated_at`
- `finished_at`

启动恢复规则：

- `queued` 任务继续排队。
- 进程退出时处于 `downloading` 或 `uploading` 的任务标为 `failed/restart_interrupted`，不自动重试，避免部分上传后产生重复内容。

## 7. 激活密钥

### 7.1 管理 Bot

在原管理 Bot 增加仅允许现有 `allowed_user_ids` 使用的命令：

```text
/create_resource_key
/revoke_resource_user <telegram_user_id>
```

`/create_resource_key`：

- 创建一次性密钥。
- 私聊回复完整密钥一次。
- 日志只记录 key prefix 和操作者 ID。

`/revoke_resource_user`：

- 将用户状态改为 `revoked`。
- 将其频道绑定标记为 `unbound`。
- 新搜索和新发布立即拒绝。
- 已排队但未开始的任务取消；正在执行的任务在下一安全检查点停止。

### 7.2 资源 Bot

资源 Bot 私聊命令：

```text
/start
/activate <activation_key>
/status
/bind
/channel
/unbind
/search <keyword>
/help
```

兑换使用单个 `BEGIN IMMEDIATE` 事务完成密钥检查、密钥占用和用户激活，防止同一密钥并发兑换。

## 8. 频道绑定

绑定流程：

1. 激活用户在资源 Bot 私聊中执行 `/bind`。
2. Bot 提示用户把资源 Bot 添加到目标频道并授予管理员发帖权限。
3. 资源 Bot 通过 `ChatMemberUpdatedHandler` 接收自身频道成员状态变化。
4. 更新操作者必须是已激活用户。
5. 资源 Bot 调用 `get_chat_member(chat_id, actor_id)`，确认操作者为频道创建者或管理员。
6. 确认资源 Bot 是频道管理员并具备 `can_post_messages`。
7. 事务写入绑定，并私聊用户绑定成功。

权限丢失：

- 资源 Bot 被移除、降级或失去发帖权限时，将绑定标记为 `permission_lost`。
- 每次创建发布任务前再次检查权限。
- worker 真正上传前再次检查权限。
- 权限检查失败时任务以 `target_permission_lost` 结束。

`/unbind` 只解除绑定，不从频道删除 Bot。

## 9. 资源搜索

搜索只读取现有 `ChannelLibraryStore`：

```python
store.list_packages_aggregate(
    [],
    PackageFilter(q=keyword),
    cursor=cursor,
    limit=5,
)
```

规则：

- 只向用户展示 `boundary_status == "stable"` 的资源包。
- 结果显示标题、来源频道、发布日期、媒体数量和已知总大小。
- 每页最多五个资源包。
- 每个结果提供“发布到频道”按钮。
- 页面提供上一页或下一页按钮；短期分页状态按用户保存在资源 Bot 内存中。
- 进程重启后旧分页按钮提示重新搜索。
- 搜索不使用全局 `channel_package_selections`，不同资源 Bot 用户不会相互影响。
- 用户未激活、已撤销或未绑定频道时，不允许创建发布任务。

用户点击发布按钮时：

- 验证回调发起者与搜索会话用户一致。
- 重新读取资源包并确认仍为稳定版本。
- 为该按钮操作生成一次性 action token。
- 使用 action token 作为持久化幂等键创建一个任务。
- 同一个按钮重复提交只返回同一个任务。

## 10. 资源发布

### 10.1 快照

创建任务时保存：

- 资源包 ID。
- `index_revision`。
- 目标频道 ID。
- 包内项目数量。

worker 开始时重新读取包和项目：

- 包不存在、被 supersede 或 revision 变化：`package_changed`。
- 来源消息缺失：单项标记失败；第一版整包失败，不发布不完整资源包。
- 目标权限丢失：`target_permission_lost`。

### 10.2 下载

每个任务使用：

```text
temp/resource-deliveries/<public_job_id>/
```

规则：

- 来源 chat/message ID 来自包内持久快照。
- 使用后台主账号 Client 重新获取消息。
- 支持 `audio`、`document`、`photo`、`video`、`voice`、`video_note`。
- 每个文件下载完成后更新 `downloaded_items`。
- 下载失败时不开始上传。
- 已创建的临时目录和文件在 `finally` 中清理。

### 10.3 上传

上传由资源 Bot Client 执行：

- 无 `media_group_id` 的项目按资源包 ordinal 顺序逐条上传。
- 相同 `media_group_id` 的连续项目组成一个媒体组。
- 媒体组保留原始顺序；不跨组重排。
- 原始 caption 仅附在原本有 caption 的项目上。
- 不生成额外广告、来源水印或文件名改写。
- 单项上传成功后更新 `uploaded_items`。
- Telegram `FloodWait` 按返回秒数等待后继续，不自行增加指数重试。
- 任何上传失败都记录安全错误摘要；已经成功发布的内容不自动删除。

因为 Telegram 不提供跨多条消息的原子发布，任务可能出现部分上传后失败。此时任务状态为 `failed/partial_upload`，回复用户已上传数量，人工决定是否清理或重试。

### 10.4 并发

第一版只有一个全局资源发布 worker，一次只执行一个发布任务：

- 避免新 Bot 并发上传导致 FloodWait。
- 避免与频道库扫描产生不可控 Telegram 并发。
- 不修改现有下载 worker 数量。
- 发布 worker 使用现有 Telegram activity gate 或等价的单所有者协调点，避免与频道扫描同时发起批量读取。

## 11. 错误边界

对用户只返回稳定错误：

- `activation_required`
- `activation_invalid`
- `activation_revoked`
- `channel_not_bound`
- `target_permission_lost`
- `package_not_found`
- `package_changed`
- `source_message_missing`
- `download_failed`
- `upload_failed`
- `partial_upload`
- `restart_interrupted`
- `service_unavailable`

日志可以记录异常类型和任务 ID，但不包含 Token、激活密钥、session、完整配置或用户私聊内容。

## 12. 测试

必须使用测试驱动方式覆盖：

### 生命周期与配置

- `resource_bot_token` 为空时只启动管理 Bot。
- 两个 Token 同时存在时统一入口启动两个角色。
- 任一角色启动失败时已启动组件被清理。
- 停止顺序不会留下 worker 或 Bot Client。
- `/forward` 不再注册或出现在帮助信息中。

### 激活与绑定

- 明文激活密钥不持久化。
- 同一个密钥只能成功兑换一次。
- 撤销用户不能继续搜索或创建任务。
- 未激活操作者不能绑定频道。
- 非频道管理员不能绑定。
- Bot 没有 `can_post_messages` 时不能绑定。
- 权限被撤销后绑定立即失效。

### 搜索

- 关键词搜索复用 Unicode 归一化。
- 只显示稳定资源包。
- 分页不跨用户。
- 过期回调要求重新搜索。
- 未绑定用户不能发布。
- 重复点击返回同一个任务。

### 发布

- 来源消息按 ordinal 下载。
- 媒体组顺序保持不变。
- 资源 Bot 是上传调用者。
- 下载失败时零上传。
- 部分上传返回 `partial_upload`。
- 权限在排队后丢失时不上传。
- 临时目录在成功、失败和取消后均清理。
- 重启将活动任务标记为 `restart_interrupted`，排队任务可恢复。

### 回归

- 原管理 Bot 下载、预扫、评论包和停止任务测试通过。
- 频道库、Web、任务状态和完整 pytest 套件通过。
- `check_imports.py`、Python compile 和 `git diff --check` 通过。

真实 Telegram 验证停在生产服务器之前，可使用本地测试 Bot/频道完成；若本地没有可用测试频道，必须明确记录为服务器验收项。

## 13. 文档与记录

更新：

- `config.example.yaml`
- `README_CN.md`
- 必要时更新 `README.md`
- `docs/web-control-console.md` 中与共享资源库和任务边界相关的说明
- `progress.md`

文档明确：

- 两个 Bot 角色。
- 激活和频道绑定流程。
- 用户只添加资源 Bot，不添加主账号。
- 下载后上传的行为和部分上传风险。
- 生产配置由用户在最终服务器验收阶段接管。

## 14. 部署边界

本轮完成后允许：

- 本地提交完整代码和文档。
- 给出服务器 `config.yaml` 的精确新增项。
- 给出数据库备份、服务重启和验收命令。

本轮不执行：

- 连接生产服务器。
- 修改生产 `config.yaml`。
- 写入 `.env.new` 中的真实 Token。
- 重启 `tg-downloader.service`。
- 生产数据库迁移或线上 Bot 验收。

最终交接时由用户接管生产服务器验收。

## 15. 回滚

代码回滚：

- 回滚本功能的实现提交即可恢复原管理 Bot 生命周期。
- `resource_bot_token` 为新增可选配置，旧配置继续可用。

数据回滚：

- `resource_bot.sqlite3` 是独立新增数据库，可在服务停止后单独备份或移走。
- 不修改 `channel_library.sqlite3` 和 `web_tasks.sqlite3` schema。
- 回滚时保留 `resource_bot.sqlite3` 不影响旧代码；如需彻底移除，可在备份后删除该独立数据库。
