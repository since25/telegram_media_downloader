# Hermes MCP 控制层设计

## 1. 目标与范围

为常驻运行的 Telegram Media Downloader 增加一个 MCP `stdio` 适配器，使 Hermes 可以查询已索引资源包、提交下载、查看任务状态、控制下载，以及管理关键词监控组。

Hermes 与下载器不在同一台机器：Hermes 在 `ubuntu-wg`，下载器在 RackNerd，两者之间没有私有链路。已决定（2026-08-24）MCP 适配器在 Hermes 侧以 `stdio` 运行，通过公网 `https://tgdn.wyichuan.cc` 访问下载器的控制接口，使用 Bearer API Key 鉴权。

选型依据：Web 控制台本身已经公网可达，且控制台已具备提交下载、取消任务、修改设置的完整能力。MCP 走公网并不扩大最坏情况下的能力边界，因此不额外引入 SSH 通道或第二个回环监听。真正由本次改动新增的是**一种新凭据**，所以 Bearer 的失败限速、常量时间比较和鉴权审计是必做项。

本次范围包括：

- MCP `stdio` 服务及其工具定义；
- MCP 到常驻下载器的跨机 HTTPS 控制通道；
- Bearer API Key 鉴权、失败限速与鉴权审计；
- 资源包搜索、详情、下载和任务控制；
- 关键词监控组的查询、创建、更新、删除、历史和失败重试；
- 停用 `resource_delivery` 及 Resource Bot 的发布链路。

交付顺序：先做 `resource_delivery` 停用（与 MCP 独立，且能减少启动路径分支），再做第一批 MCP 只读工具加 `submit_download`，最后做写操作与关键词监控工具。每一批自身可用、可验证。

本次范围不包括：

- 新的 Telegram 搜索或索引算法；
- “搜索后自动下载”的合并工具；
- 多用户、多 Key 或按工具粒度的授权模型；
- 把现有 Web 控制台从 Werkzeug 开发服务器迁移到生产级 WSGI 服务器；
- 收敛源站访问来源（见第 11 节，属于既有基线风险，单独决策）；
- 删除旧的 `resource_bot.py`、`resource_delivery.py` 或 `resource_bot.sqlite3`，以保留回滚能力。

## 2. 已确认的运行约束

- 下载器继续作为常驻服务运行。
- Hermes 在 `ubuntu-wg` 上启动独立 MCP `stdio` 进程；MCP 进程退出或重启不得中断下载。
- MCP 与下载器跨公网通信，入口是 Cloudflare 代理的 `https://tgdn.wyichuan.cc`，只用独立 Bearer API Key 鉴权，不使用 Session 或 Cookie。
- 源站（`192.3.85.23:80`）当前可绕过 Cloudflare 直连。这是既有状态，本次不改变，MCP 的安全设计不得依赖“只能从 Cloudflare 进来”这一假设。
- 单次 MCP 控制请求必须在 Cloudflare 的响应超时内返回；所有等待 owner loop 的调用沿用现有 1–5 秒等待上限，不引入长轮询。
- Web 控制台继续保留，使用现有登录、Session 和 CSRF 逻辑。
- MCP 不直接写 SQLite，不直接操作 Pyrogram 客户端，也不创建第二套下载队列。
- 所有运行时命令必须回到下载器的 owner event loop 执行。

## 3. 总体架构

```text
Hermes Agent（ubuntu-wg）
    │ MCP stdio
    ▼
mcp_server.py（ubuntu-wg，与 Hermes 同机）
    │ HTTPS + Authorization: Bearer <mcp_api_key>
    ▼
Cloudflare 代理（tgdn.wyichuan.cc）
    │ 源站 80 端口同时公网可直连（既有状态）
    ▼
RackNerd 源站 · 常驻 Downloader Web/Control Layer
    │ owner-loop command bridge
    ▼
ChannelLibraryStore / ChannelLibraryService / TaskStore
    ▼
Telegram 下载运行时
```

MCP 服务只负责协议转换、参数校验、错误映射和调用本机控制接口。常驻下载器仍是任务状态、资源索引、队列和 Telegram 运行时的唯一事实来源。

MCP 控制路由挂在现有 Web 进程与现有监听端口上，作为独立的路径前缀（例如 `/api/mcp/...`）与浏览器 API 分离：浏览器路由继续使用 `login_required`/CSRF；MCP 路由只接受 Bearer API Key，拒绝 Session 与 Cookie，且在未鉴权时返回 JSON `401` 而不是跳转登录页。两类路由复用相同的业务 service 和 owner-loop 桥接函数。

因为控制路由与控制台共用公网监听，且 Bearer 是本次新增的凭据类型，以下防护必须随本次改动一起交付：

- MCP 路径的 Key 校验失败按客户端限速，复用 `web_auth.LoginAttemptLimiter` 的既有实现，不新写一套；
- 鉴权成功与失败都写入服务日志，记录来源与工具名，但不记录 Key 本身；
- API Key 使用常量时间比较；任何日志、错误响应、任务历史和 `/api/settings` 输出都不得包含完整或部分密钥。

## 4. MCP 工具

### 4.1 资源包

- `search_resource_packages`
  - 输入：标题关键词及现有资源包筛选条件、分页游标；
  - 输出：资源包摘要、来源频道、媒体数量、已知大小、下载状态、`boundary_status`、`downloadable` 和下一页游标；
  - 查询直接复用 `ChannelLibraryStore.list_packages_aggregate`，返回集合与 Web 完全一致：排除 `superseded`，保留 `stable` / `provisional` / `uncertain`。不在搜索层做稳定性过滤，稳定性拒绝统一由 `submit_download` 承担；
  - `downloadable` 为派生字段，等价于 `boundary_status == "stable"`，让调用方无需理解边界状态语义。

- `get_resource_package`
  - 输入：`package_id`；
  - 输出：资源包元数据和媒体条目（条目分页，单页上限与 Web 一致，最大 200 条）；
  - 非稳定边界包可以查看，但不能直接提交下载。

### 4.2 下载任务

- `submit_download`
  - 输入：一个或多个 `package_id`、`idempotency_key`，以及显式的 `redownload`；
  - 输出：创建结果、每个批次的 ID 与 `task_id`、任务状态和包级摘要；
  - **必须走新增的显式入口，不得复用 Web 的聚合下载路径。** Web 的 `/api/packages/download-batches` 依赖全局勾选状态，并在成功后清空勾选，MCP 复用会污染控制台用户的当前选择。新增的 service 方法直接接收 `package_ids`，按 `library_id` 与实际来源 `source_chat_id` 分组扇出，全程不读写 `channel_package_selections`；
  - 幂等键唯一性是 `(library_id, idempotency_key)`，因此每个分组使用派生键 `"{key}:library:{library_id}:source:{source_chat_id}"`。调用方传入的原始 `idempotency_key` 上限 160 字符；
  - 重复调用返回已存在的批次并标记 `created=false`，不报错、不新建批次；
  - 复用现有批次创建的重复保护、容量检查和 revision 校验；
  - 对已成功下载或已过期 revision 的包，必须显式提供 `redownload=true`，否则返回 `redownload_required`；
  - 非 `stable` 边界的包一律拒绝，返回 `state_conflict`。

- `get_download_task`
  - 输入：只接受字符串 `task_id`。批次的整数主键不作为对外标识；批次通过 `ChannelLibraryStore.get_download_batch_header_by_task_id` 反查，`submit_download` 的返回值里已经带上 `task_id`；
  - 输出：任务状态、当前文件/包、总数、成功数、失败数、速度、错误和更新时间。

- `list_download_tasks`
  - 输入：状态过滤、返回条数上限（默认 50，最大 200）；
  - 输出：最近任务摘要和汇总计数；
  - **不提供时间范围查询。** `TaskStateStore` 只在内存中保留最近 `recent_limit` 条已完成任务，没有可供时间范围检索的历史表，提供该参数会给出无法兑现的承诺。工具描述里必须写明“只覆盖最近任务”；
  - 返回体必须按条数上限截断，服务器是 1 vCPU / 1 GiB，不做全量任务序列化。

- `cancel_download_task`
  - 只允许取消现有生命周期允许取消的任务，必须复用 owner-loop 取消逻辑，不能只修改数据库状态；
  - 返回值必须区分两种成功结果：持久化批次与运行中任务变为 `cancelled`；未持久化的等待、排队任务被直接移除，返回 `removed=true`；
  - 运行态任务缺少进程内运行句柄时返回 `runtime_handle_missing` 冲突错误，不得谎报取消成功。

- `pause_downloads` / `resume_downloads`
  - **不能直接复用 `/set_download_state`。** 现有实现是基于当前状态的翻转，且返回“下一步可执行动作”的标签而非当前状态；
  - MCP 需要幂等的显式设置：已暂停时再次 `pause_downloads` 返回当前的暂停状态，不得恢复下载；
  - 状态变更仍在 owner event loop 上执行，复用现有的 `submit_web_coroutine` / `wait_for_web_command` 桥接；
  - 返回变更后的真实状态，服务不可用或 owner loop 停止时返回明确错误。

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
  - 各字段来源必须逐项对齐现有实现：健康状态取 `RuntimeHealth.phase`，暂停状态取 `get_download_state()`（注意 `GET /api/system` 当前不含该字段，只有 `/api/task-dashboard` 有），速度取 `get_total_download_speed()`，磁盘取 `shutil.disk_usage(app.save_path)`，任务统计取 `TaskStateStore.dashboard()` 的计数部分；
  - 不输出 Telegram token、API hash、MCP Key、Cookie、session 文件路径或文件系统敏感配置。

## 5. `resource_delivery` 停用方案

`resource_delivery` 的“主账号下载 → 暂存频道 → Resource Bot 发布到用户频道”链路在运行时明确关闭：

- `BotManager` 不再根据 `resource_bot_token` 启动 `ResourceBotRole`；
- 不创建或启动 `ResourceDeliveryService`；
- 不注册资源用户、绑定频道和发布任务相关运行时处理；
- 发布控制接口拒绝新任务并返回稳定错误码 `resource_delivery_disabled`，HTTP 映射为 `410`。该判定必须落在 `module/web.py` 的 `_resource_store()` 里：当前所有发布路由都经过它，而它在 store 为 `None` 时统一抛 `503 service_unavailable`，不区分“已停用”和“服务异常”；
- 旧模块、测试和数据库先保留，不再作为当前启动路径的一部分；
- `resource_bot_token` 和 `resource_staging_chat_id` 不再是下载器启动成功的必要条件。`module/bot.py` 中“配置了 `resource_bot_token` 却没有 `bot_token` 就抛错”的校验一并移除；`module/download_runtime.py` 里 `bot_token or resource_bot_token` 的分支判断改为只看 `bot_token`。

对既有功能的影响，必须一并处理而不是宣称“无影响”：

- **Web 控制台的发布任务面板会受影响。** 控制台会持续轮询 `/api/resource-deliveries`，停用后该请求恒定失败，面板会一直显示“发布任务读取失败”。处理方式：读接口在停用时返回 `200` 且带 `disabled: true` 与空列表，前端据此隐藏整个发布面板，不再轮询；写接口仍返回 `410 resource_delivery_disabled`。
- **管理 Bot 的命令列表会变短。** 停用会跳过 `ResourceAdminCommands.register` 与 `build_resource_admin_bot_commands()`，管理 Bot 对外注册的命令随之减少。这是预期结果，需在验证时确认，避免被当成回归。

普通管理 Bot 的下载命令、普通下载、频道资源库、关键词监控和控制台其余部分不受影响。

## 6. 错误与幂等

MCP 适配器将本机控制接口错误转换为稳定的工具错误：

- `401`：API Key 缺失或错误，响应为 JSON，不跳转登录页；
- `404`：资源包、监控组或任务不存在；`mcp.enabled` 为 false 时整个 MCP 路径也返回 `404`；
- `409`：状态冲突、重复下载、需要显式重下载、没有可重试失败，或运行态任务缺少运行句柄（`runtime_handle_missing`）；
- `410`：`resource_delivery` 已停用；
- `429`：Key 校验失败次数超限，响应带可重试秒数；
- `503`：常驻下载器、owner loop 或频道服务不可用。

稳定错误码沿用现有 Web 契约的取值：`invalid_request`、`not_found`、`state_conflict`、`redownload_required`、`runtime_handle_missing`、`service_unavailable`、`resource_delivery_disabled`。

所有产生下载副作用的工具必须要求 `idempotency_key` 或明确的唯一操作标识。MCP 超时不能撤销已经被 owner loop 接收的命令；客户端应通过任务查询工具确认最终状态。

## 7. 配置与进程生命周期

下载器侧新增配置项，只描述开关，不承载密钥：

```yaml
mcp:
  enabled: true
```

API Key 只从环境变量或独立的 0600 文件读取，不写进 `config.yaml`：`Application.update_config()` 会周期性整体重写 `config.yaml`，明文密钥会长期留存在一个被频繁改写的文件里；仓库里已有更合适的先例，`web_auth` 用独立 0600 JSON 保存口令哈希与 session secret。真实值不得进入仓库、测试夹具、日志或设计文档。

Hermes 侧的 MCP `stdio` 进程通过两个环境变量定位服务：控制入口地址（默认 `https://tgdn.wyichuan.cc`）与 API Key。进程启动时不做任何自动发现，也不尝试启动第二个下载器；控制入口不可达、返回非预期状态或 TLS 校验失败时，所有工具返回 `service_unavailable` 并附带可区分的原因。

`mcp.enabled` 为 false 时，MCP 路由整体不注册，请求返回 `404`，与“已配置但服务异常”区分开。

## 8. 验证标准

实现完成后至少验证：

1. 正确 API Key 可以通过 MCP 查询资源包、监控组和系统状态；错误或缺失 Key 被拒绝。
2. 相同筛选条件下，MCP 搜索与 Web 资源包查询返回同一集合与同一游标语义，且 MCP 结果带 `boundary_status` 与 `downloadable`。
3. MCP 提交下载使用现有幂等和 revision 保护，重复调用不会创建重复批次，且全程不读取、不修改、不清空 Web 控制台的勾选状态。
4. MCP 取消、暂停和继续确实作用于 owner event loop，而不是只改持久化状态；重复 `pause_downloads` 保持暂停而不是翻转。
5. 关键词监控新增、修改、删除、历史和失败重试与 Web API 行为一致。
6. 监控组创建/更新会触发当前稳定资源包匹配，并正确返回汇总计数。
7. 配置 `resource_bot_token` 时，Resource Bot 和 `ResourceDeliveryService` 均不会启动；发布写端点返回 `resource_delivery_disabled`，读端点返回 `disabled: true` 且控制台不再显示发布面板。
8. 原有 Web 登录、资源库、下载任务和频道扫描测试继续通过。
9. MCP `stdio` 输出只包含协议消息，日志全部写入 stderr 或常驻服务日志；验证方式为捕获子进程 stdout 并断言每一帧都是合法 JSON-RPC。
10. MCP 路由拒绝 Session/Cookie 鉴权，浏览器路由拒绝 Bearer；未鉴权的 MCP 请求返回 JSON `401` 而不是登录跳转。
11. 连续错误 Key 触发限速；错误响应体与日志中都不出现密钥内容。
12. `mcp.enabled: false` 时 MCP 路由返回 `404`，且 Web 控制台功能不受影响。

## 9. 回滚边界

本设计不要求删除旧模块或数据库。若 MCP 控制层出现问题，可停用 MCP 配置并恢复原 Web 控制路径；若需要恢复资源 Bot 发布功能，再单独恢复 `BotManager` 的资源角色启动逻辑和对应配置，避免与本次 MCP 变更混在一起。

## 10. 设计审查与修改意见（2026-08-24，已并入正文）

> 本节的结论已全部落到第 1 至第 8 节正文与 `docs/superpowers/plans/2026-08-24-mcp-hermes-control.md`，保留在此仅作为决策依据的记录。A1、A2 已关闭，A3 已按“新增 service 入口、不触碰 selection 表”定案。

结论：当前设计的工具边界和"不新建第二套队列"的原则是对的，但**还不能直接进入实现**。有 3 个结构性问题（部署拓扑、控制端口形态、多包下载入口）会改变实现方案本身，必须先定稿；另有若干条"复用现有逻辑"的表述与代码实际不符，需要按下文修正。

### 10.1 必须先定稿的阻断项

**A1. 部署拓扑已确认：跨机，且两端之间没有私有链路（最高优先级）**

2026-08-24 核实到的事实：

- 下载器在 RackNerd（`racknerd-aaefa73`，`192.3.85.23`），`tg-downloader.service` 运行中，Web 以 `web_host: 0.0.0.0` / `web_port: 80` 直接监听公网网卡；
- `tgdn.wyichuan.cc` 解析到 Cloudflare（`104.21.65.133` / `172.67.163.123`），是 Cloudflare 代理，服务器上没有 `cloudflared` 之类的隧道进程；源站 `http://192.3.85.23/` 可直接访问并返回 302，控制台在源站 IP 上同样公网可达；
- RackNerd 上只有 `lo` 与 `eth0`，没有 WireGuard 接口；Hermes 所在的 `ubuntu-wg` 处于私有网段，两台机器之间不存在私有链路；
- 从 `ubuntu-wg` 直接 SSH 到 RackNerd 当前不可用（host key verification failed），需要一次性配置。

因此第 2 节“MCP 只允许本机当前用户使用”和第 7 节“控制端口只绑定 `127.0.0.1`”在当前部署下都不成立，必须改写。可行路线只剩三条：

1. **（推荐）MCP 进程跑在 RackNerd 上，Hermes 通过 `ssh rn <启动命令>` 拉起，stdio 经 SSH 通道传输。** 控制接口继续只绑 `127.0.0.1`，不新增任何公网监听，跨机鉴权由 SSH 密钥承担，API Key 退化为进程内的二次校验。代价：需要在 `ubuntu-wg` 上配置到 RackNerd 的密钥与 known_hosts，MCP 代码随仓库部署到服务器，并在 1 vCPU / 1 GiB 的机器上多驻留一个 Python 进程。
2. MCP 进程留在 `ubuntu-wg`，用常驻 SSH 隧道把 RackNerd 的回环控制端口映射到本地。回环约束仍成立，但多一个必须常驻且必须自愈的隧道单元（autossh/systemd），故障面更大。
3. **（不建议）** 直连 `https://tgdn.wyichuan.cc` + Bearer。等于把可触发下载的控制 API 挂到公网，且源站 IP 可绕过 Cloudflare 直连、由 Werkzeug 开发服务器直接对外提供服务。若一定要走这条，必须先补：源站防火墙只放行 Cloudflare 回源段、MCP 路径独立的失败限速、以及独立于 Web 登录的审计。

**决策（2026-08-24）：采用路线 3。** 依据是控制台已经公网可达，且它已具备与 MCP 等价的完整能力（提交下载、取消任务、修改设置），因此 MCP 走公网不扩大最坏情况的能力边界，路线 1 / 2 换来的隔离收益在既有入口已开放的前提下有限，不足以抵消额外的 SSH 配置、第二个回环监听和服务器依赖安装成本。

随该决策同时确定：

- 由本次改动新增的是一种新凭据，所以 Bearer 的失败限速、常量时间比较、鉴权审计和“未鉴权返回 JSON 401”是必做项，已写入第 1、2、3、8 节；
- 源站访问收敛属于既有基线风险，不并入本次范围，移入第 11 节单独记录；
- MCP 的安全设计不得依赖“源站只能从 Cloudflare 进入”这一假设。

因此 A1 关闭，A2 随之确定为“MCP 路由挂在现有 Web 监听上，用独立路径前缀区分”，不再新增第二个监听端口。

**A2. 控制端口形态自相矛盾**

第 3 节推荐"在现有 Web 进程中增加 MCP 专用控制路由"，第 7 节却给出独立 `host/port: 5010`。而现有实现只有一个 `WebServer` 实例绑定 `app.web_host`，默认 `0.0.0.0:5000`（`module/web.py:253`、`module/app.py:490`）。两条路线的后果不同，必须二选一写死：

- 同应用同端口：MCP 路由会随 Web 一起监听 `0.0.0.0` 并落在公网反代后面，"控制端口只绑定 127.0.0.1"这句话不成立，必须改为"依赖反代/防火墙屏蔽 MCP 路径"；
- 独立 `127.0.0.1:5010`：需要第二个 `WebServer` 实例与独立 Flask 应用（或独立蓝图 + 独立监听），并补充它的启动、停止、失败回滚、健康检查归属，以及与 `/api/settings` 的关系。设计目前完全没有描述这部分生命周期。

**A3. 多包下载没有可复用且无副作用的入口**

`submit_download` 声明"复用现有下载批次创建"，但现有多包路径 `/api/packages/download-batches` 走的是**全局勾选状态**：读 `selection_summary_aggregate()` 与 `selected_download_groups()`，成功后调用 `clear_selection_aggregate()`（`module/web.py:1272-1338`）。MCP 若复用它，会读写 Web 控制台用户当前的勾选，并在提交后把用户的选择清空，属于跨端串扰，不可接受。

单包路径 `/api/packages/<id>/download-batch` 确实不碰勾选，但它没有传 `redownload`（`module/web.py:1196`），无法满足设计要求的显式重下载。

因此必须承认这是**新增入口**而非纯复用：新增一个按显式 `package_ids` + `redownload` 直接建批的 service 级方法，自行按 `library_id` / `source_chat_id` 分组扇出（`create_download_batch_result` 已支持 `package_ids`、`redownload` 两个参数），全程不触碰 selection 表。

### 10.2 需要修正的设计条目

**B1. 幂等键作用域要写明。** 幂等唯一性是 `(library_id, idempotency_key)`（`module/channel_library_store.py:564`），跨库多包提交必须像现有聚合路由那样派生 `:library:{id}:source:{chat_id}` 后缀。设计需补：派生规则、长度上限（现有两处分别是 160 和 200，MCP 侧应统一）、重复调用返回语义（现有实现返回 `created=false`，HTTP 200，而非报错）。

**B2. 搜索口径与验证标准第 2 条互相矛盾。** 第 4.1 写"仅包含可用稳定资源包"，但 `list_packages_aggregate` 只排除 `superseded`，`provisional` / `uncertain` 都会返回（`module/channel_library_store.py:1692`）。照 4.1 实现，第 8 节第 2 条"MCP 搜索结果与 Web 资源包查询结果一致"必然不成立。建议改为：返回与 Web 相同的集合，显式带上 `boundary_status` 与 `downloadable` 字段，把稳定性拒绝集中放在 `submit_download`。

**B3. `pause_downloads` / `resume_downloads` 不能直接复用 `/set_download_state`。** 现有实现是基于当前状态的翻转，且返回值是"下一步可执行动作"的标签而不是当前状态（`module/web.py:1650` 与 `_set_download_state_owned`）。MCP 需要的是幂等的显式设置：已暂停时再次 `pause` 应返回"已暂停"，而不是恢复下载。应在 owner loop 上包一层显式 set 语义。另外目前没有单独读取暂停状态的接口，`GET /api/system` 不含 `download_state`（只有 `/api/task-dashboard` 有），`get_system_status` 需注明每个字段的数据来源。

**B4. `list_download_tasks` 的过滤、时间范围、分页没有现成支撑。** `/api/tasks` 返回全量任务、无过滤无分页（`module/web.py:1797`），且完成任务只在内存中保留 `recent_limit` 条（`module/task_state.py` 的 `_move_completed`）。二选一：把工具降级为"最近 N 条 + 状态过滤"，或明确新增 TaskStore 查询能力并纳入范围。同时要给所有列表类工具设置返回体量上限——服务器是 1 vCPU / 1 GiB，全量序列化任务和包条目是真实成本。

**B5. `get_download_task` 的 ID 语义要写清楚。** 批次同时有整数 `batch.id` 和字符串 `task_id`，现有映射入口是 `get_download_batch_header_by_task_id`（`module/web.py:2638`）。工具应只接受一种 ID，或用两个互斥参数明确区分，不要写成"任务或批次 ID"。

**B6. `cancel_download_task` 的可取消范围与返回语义不完整。** 现有取消依赖进程内运行句柄（`_pending_web_task_previews` / `get_active_task_nodes()`）：句柄缺失且任务处于运行态时返回 409 `runtime_handle_missing`；非持久化的等待/排队任务会被**直接删除**而不是标记为 cancelled（`module/web.py:2620-2700`）。设计的错误映射缺 `runtime_handle_missing`，也没说明"取消可能返回 removed 而不是 cancelled"。

### 10.3 `resource_delivery` 停用方案的修正

**C1. "Web 控制台不受影响"不成立。** 控制台存在发布任务面板，会持续轮询 `/api/resource-deliveries`（`module/templates/index.html:960`、`2174`、`2185`）。停用后 `app.resource_bot_store` 为 `None`，`_resource_store()` 抛 503 `service_unavailable`（`module/web.py:408`），面板会一直显示"发布任务读取失败"。必须决定并写入范围：读接口返回 `disabled` 标记 + 空列表并在前端隐藏该面板，还是保留错误码但前端显式渲染"已停用"。无论哪种，前端改动都要纳入本次范围。

**C2. `resource_delivery_disabled` / 410 的落点要具体。** 目前所有发布相关路由都经过 `_resource_store()` 这一个 helper，默认走 503。要区分"已停用"和"服务不可用"，必须在该 helper（或路由层）显式引入停用判定，否则第 8 节第 7 条验证不了。

**C3. 管理 Bot 命令面会缩小。** 停用会跳过 `ResourceAdminCommands.register` 与 `build_resource_admin_bot_commands()`（`module/bot.py:538-546`），管理 Bot 对外命令列表随之变短。这是预期结果，但要在设计里写明，避免上线后被当成回归。

**C4. `resource_bot_token` 的残留判定要一起处理。** `module/bot.py:483` 仍会在"配置了 resource_bot_token 但没有 bot_token"时抛错；`module/download_runtime.py:139` 与 `:187` 仍用 `bot_token or resource_bot_token` 决定分支。要明确这些判定是保留还是清理，否则"不再是启动成功的必要条件"只兑现一半。

### 10.4 配置与密钥

**D1. 不建议把 `api_key` 明文写进 `config.yaml`。** `Application.update_config()` 会周期性整体重写 `config.yaml`（`module/app.py:1017`），密钥会长期以明文停留在一个被频繁重写的文件里。仓库里已有更合适的先例：`web_auth` 用独立 0600 JSON 文件保存口令哈希与 session secret（`module/web_auth.py`）。建议 `config.yaml` 只保留 `mcp.enabled/host/port`，密钥只从环境变量或独立 0600 文件读取。同时确认 `/api/settings` 的字段白名单不会带出该项（当前 `_settings_from_app` 是显式枚举字段，默认安全，但要加一条回归验证）。

**D2. Bearer 校验需要失败限速与审计。** 登录路径有 `LoginAttemptLimiter`，MCP Bearer 没有对应机制。若最终采用 A1 的第 3 种拓扑（公网暴露），这一条是必需项而不是可选项。

**D3. 新增运行时依赖与运行环境未说明。** `requirements.txt` 中没有 MCP SDK，而仓库存在 `tests/test_dependency_contract.py` 与 Docker 契约测试。需补充：MCP SDK 依赖如何登记、`mcp_server.py` 放在哪个包下、Hermes 用哪个 Python 环境拉起它、是否要进 Docker 镜像。

### 10.5 验证标准修订

- 第 2 条改为"相同筛选条件下 MCP 与 Web 返回同一集合与同一游标语义"，与 B2 对齐。
- 新增：MCP 多包提交不读取、不修改、不清空 Web 控制台的勾选状态（对应 A3）。
- 新增：MCP 路由拒绝 Session/Cookie 鉴权，Web 路由拒绝 Bearer；错误 Key 不写日志、响应体不含密钥片段。
- 新增：停用 `resource_delivery` 后，控制台发布面板处于明确的"已停用"状态而非持续报错（对应 C1）。
- 第 9 条补充可执行的验证方式，例如捕获 MCP 子进程 stdout 并断言每一帧都是合法 JSON-RPC。

### 10.6 范围建议

建议把第一版收敛为**只读通道 + 单一提交入口**：`search_resource_packages`、`get_resource_package`、`get_download_task`、`get_system_status`、`submit_download`。关键词监控 CRUD、`pause/resume`、`cancel`、失败重试放第二批。

理由：A1 / A2 / A3 三个结构性问题全部集中在写入侧和网络暴露侧；先把只读通道打通，可以在不承担写入风险的前提下尽早验证 Hermes 端的集成方式，也能让拓扑决策的返工成本降到最低。

## 11. 未纳入本次范围的既有风险

以下问题在本设计之前就已存在，与 MCP 控制层无关，本次明确不处理，仅记录备查：

- 源站 `192.3.85.23:80` 可绕过 Cloudflare 直连，控制台在源站 IP 上同样公网可达。收敛到只放行 Cloudflare 回源地址段会降低基线风险，但那是既有部署决策，不由本次改动引入，且防火墙误配存在把自己锁在外面的风险，应作为独立运维任务单独执行。
- Web 控制台由 Werkzeug 开发服务器直接对外提供服务，未使用生产级 WSGI 服务器。

MCP 的安全设计不得依赖上述任何一项被修复，必须在“源站可被直连”的前提下自洽。
