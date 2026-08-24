# Hermes MCP 控制层设计

## 1. 目标与范围

为常驻运行的 Telegram Media Downloader 增加一个由 Hermes 启动的本机 MCP `stdio` 适配器，使 Hermes 可以查询已索引资源包、提交下载、查看任务状态、控制下载，以及管理关键词监控组。

本次范围包括：

- MCP `stdio` 服务及其工具定义；
- MCP 到常驻下载器的本机控制通道；
- API Key 鉴权；
- 资源包搜索、详情、下载和任务控制；
- 关键词监控组的查询、创建、更新、删除、历史和失败重试；
- 停用 `resource_delivery` 及 Resource Bot 的发布链路。

本次范围不包括：

- 新的 Telegram 搜索或索引算法；
- “搜索后自动下载”的合并工具；
- 局域网、多用户或远程 MCP 访问；
- 删除旧的 `resource_bot.py`、`resource_delivery.py` 或 `resource_bot.sqlite3`，以保留回滚能力。

## 2. 已确认的运行约束

- 下载器继续作为常驻服务运行。
- Hermes 启动的是独立 MCP `stdio` 进程；MCP 进程退出或重启不得中断下载。
- MCP 只允许本机当前用户使用，通过独立 API Key 鉴权。
- Web 控制台继续保留，使用现有登录、Session 和 CSRF 逻辑。
- MCP 不直接写 SQLite，不直接操作 Pyrogram 客户端，也不创建第二套下载队列。
- 所有运行时命令必须回到下载器的 owner event loop 执行。

## 3. 总体架构

```text
Hermes Agent
    │ MCP stdio
    ▼
mcp_server.py
    │ Authorization: Bearer <mcp_api_key>
    │ 127.0.0.1 专用控制接口
    ▼
常驻 Downloader Web/Control Layer
    │ owner-loop command bridge
    ▼
ChannelLibraryStore / ChannelLibraryService / TaskStore
    ▼
Telegram 下载运行时
```

MCP 服务只负责协议转换、参数校验、错误映射和调用本机控制接口。常驻下载器仍是任务状态、资源索引、队列和 Telegram 运行时的唯一事实来源。

推荐在现有 Web 进程中增加 MCP 专用控制路由或控制蓝图，并与浏览器 API 分离：浏览器路由继续使用 `login_required`/CSRF；MCP 路由使用 Bearer API Key，但复用相同的业务 service 和 owner-loop 桥接函数。

控制端口只绑定 `127.0.0.1`。MCP API Key 从受保护配置或环境变量读取，比较时使用常量时间比较，任何日志、错误响应和任务历史都不得输出完整密钥。

## 4. MCP 工具

### 4.1 资源包

- `search_resource_packages`
  - 输入：标题关键词及现有资源包筛选条件、分页游标；
  - 输出：仅包含可用稳定资源包的摘要、来源频道、媒体数量、已知大小、下载状态和下一页游标；
  - 查询直接复用 `ChannelLibraryStore` 的聚合包查询。

- `get_resource_package`
  - 输入：`package_id`；
  - 输出：资源包元数据和媒体条目；
  - 非稳定边界包可以查看，但不能直接提交下载。

### 4.2 下载任务

- `submit_download`
  - 输入：一个或多个 `package_id`、`idempotency_key`，以及显式的 `redownload`；
  - 输出：创建结果、批次 ID、任务状态和包级摘要；
  - 复用现有下载批次创建、重复保护、容量检查和 revision 校验；
  - 对已成功下载或已过期 revision 的包，必须显式提供 `redownload=true`。

- `get_download_task`
  - 输入：任务或批次 ID；
  - 输出：任务状态、当前文件/包、总数、成功数、失败数、速度、错误和更新时间。

- `list_download_tasks`
  - 输入：状态过滤、时间范围、分页参数；
  - 输出：近期任务摘要和汇总计数。

- `cancel_download_task`
  - 只允许取消现有生命周期允许取消的任务；
  - 必须复用 owner-loop 取消逻辑，不能只修改数据库状态。

- `pause_downloads` / `resume_downloads`
  - 复用现有全局下载状态控制；
  - 返回变更后的状态，服务不可用或 owner loop 停止时返回明确错误。

### 4.3 关键词监控

- `list_keyword_monitors`
  - 输出监控组总数、启用数、停用数；
  - 输出每个组的名称、启用状态、三类关键词、更新时间，以及 queued/downloading/completed/failed/cancelled 汇总。

- `get_keyword_monitor`
  - 输入：`group_id`；
  - 输出：单个监控组完整配置和当前进度汇总。

- `create_keyword_monitor`
  - 输入：`name`、`enabled`、`required_keywords`、`match_keywords`、`blacklist_keywords`；
  - 复用现有校验；至少需要一个匹配关键词；
  - 保存后立即调用现有 `trigger_keyword_monitors()`。

- `update_keyword_monitor`
  - 输入：`group_id` 及完整配置；
  - 更新后立即调用现有匹配逻辑。

- `delete_keyword_monitor`
  - 输入：`group_id`；
  - 删除配置，不删除已经产生的历史下载任务。

- `get_keyword_monitor_history`
  - 输入：`group_id`、分页游标和页大小；
  - 输出：命中资源包、匹配关键词、来源频道、下载批次、包状态和任务进度。

- `retry_keyword_monitor_failures`
  - 输入：`group_id`；
  - 复用现有 owner-loop 批量重试逻辑；无可恢复失败时返回冲突错误，而不是创建空任务。

第一版不新增独立的手动“重新扫描全部关键词”语义。监控组创建/更新后立即匹配，频道扫描完成后继续由现有服务触发。

### 4.4 运行状态

- `get_system_status`
  - 输出服务健康状态、下载暂停状态、队列摘要、当前速度、磁盘空间、频道扫描状态和最近任务统计；
  - 不输出 Telegram token、API hash、MCP Key、Cookie 或文件系统敏感配置。

## 5. `resource_delivery` 停用方案

`resource_delivery` 的“主账号下载 → 暂存频道 → Resource Bot 发布到用户频道”链路在运行时明确关闭：

- `BotManager` 不再根据 `resource_bot_token` 启动 `ResourceBotRole`；
- 不创建或启动 `ResourceDeliveryService`；
- 不注册资源用户、绑定频道和发布任务相关运行时处理；
- 发布控制接口拒绝新任务并返回稳定错误码 `resource_delivery_disabled`，HTTP 映射为 `410`；
- 旧模块、测试和数据库先保留，不再作为当前启动路径的一部分；
- `resource_bot_token` 和 `resource_staging_chat_id` 不再是下载器启动成功的必要条件。

普通管理 Bot、普通下载、频道资源库、关键词监控和 Web 控制台不受影响。

## 6. 错误与幂等

MCP 适配器将本机控制接口错误转换为稳定的工具错误：

- `401/403`：API Key 缺失或错误；
- `404`：资源包、监控组或任务不存在；
- `409`：状态冲突、重复下载、需要显式重下载或没有可重试失败；
- `410`：`resource_delivery` 已停用；
- `503`：常驻下载器、owner loop 或频道服务不可用。

所有产生下载副作用的工具必须要求 `idempotency_key` 或明确的唯一操作标识。MCP 超时不能撤销已经被 owner loop 接收的命令；客户端应通过任务查询工具确认最终状态。

## 7. 配置与进程生命周期

建议新增 MCP 配置项：

```yaml
mcp:
  enabled: true
  host: 127.0.0.1
  port: 5010
  api_key: <protected-secret>
```

环境变量可覆盖 API Key，但不得把真实值写入仓库、测试夹具、日志或设计文档。MCP `stdio` 进程由 Hermes 启动时连接该控制端口；常驻下载器负责提供健康状态和控制接口。控制端口不可用时，MCP 工具返回 `service_unavailable`，不尝试启动第二个下载器。

## 8. 验证标准

实现完成后至少验证：

1. 正确 API Key 可以通过 MCP 查询资源包、监控组和系统状态；错误或缺失 Key 被拒绝。
2. MCP 搜索结果与 Web 资源包查询结果一致。
3. MCP 提交下载使用现有幂等和 revision 保护，重复调用不会创建重复批次。
4. MCP 取消、暂停和继续确实作用于 owner event loop，而不是只改持久化状态。
5. 关键词监控新增、修改、删除、历史和失败重试与 Web API 行为一致。
6. 监控组创建/更新会触发当前稳定资源包匹配，并正确返回汇总计数。
7. 配置 `resource_bot_token` 时，Resource Bot 和 `ResourceDeliveryService` 均不会启动；发布端点返回 `resource_delivery_disabled`。
8. 原有 Web 登录、资源库、下载任务和频道扫描测试继续通过。
9. MCP `stdio` 输出只包含协议消息，日志全部写入 stderr 或常驻服务日志。

## 9. 回滚边界

本设计不要求删除旧模块或数据库。若 MCP 控制层出现问题，可停用 MCP 配置并恢复原 Web 控制路径；若需要恢复资源 Bot 发布功能，再单独恢复 `BotManager` 的资源角色启动逻辑和对应配置，避免与本次 MCP 变更混在一起。
