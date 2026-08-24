# Hermes MCP 控制接入

这份文档说明如何让运行在 `ubuntu-wg` 的 Hermes 通过本地 MCP `stdio` 进程，调用 RackNerd 上的下载器控制接口。MCP 进程只做协议转换和 HTTPS 调用，不读取 SQLite、不操作 Pyrogram，也不创建第二套下载队列。

## 拓扑

```text
Hermes（ubuntu-wg）
        │ stdio
        ▼
    mcp_server.py
        │ HTTPS + Bearer API Key
        ▼
https://tgdn.wyichuan.cc/api/mcp/*
        │ 现有 Web 进程
        ▼
RackNerd Telegram Media Downloader
```

下载器仍是资源索引、任务状态和下载队列的唯一事实来源。MCP 进程退出或重启不会中断已经提交的下载。

## 下载器侧启用

MCP 路由挂在现有 Web 进程上，因此需要同时启用 Web 和 MCP。在下载器的 `config.yaml` 中确认：

```yaml
enable_web: true
mcp:
  enabled: true
```

API Key 不写入 `config.yaml`。推荐把它写入与 `config.yaml` 同目录、权限为 `0600` 的 `mcp_api_key` 文件：

```bash
python3 -c "import secrets;print(secrets.token_urlsafe(32))"
chmod 600 /path/to/config-directory/mcp_api_key
```

也可以给下载器进程设置 `TMD_MCP_API_KEY`。环境变量优先于密钥文件；两者都没有时 MCP 请求不会被接受。密钥文件只由下载器读取，Hermes 侧仍需通过环境变量提供同一个值。

修改配置或密钥后重启现有服务：

```bash
systemctl restart tg-downloader.service
```

不要把真实 Key 写进仓库、日志、Shell 历史、测试夹具或本文件。

## Hermes 侧安装与启动

将本仓库部署到 Hermes 所在机器，在独立 Python 3.11 环境中安装 MCP 依赖：

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/python -m pip install -r /path/to/telegram_media_downloader/mcp-requirements.txt
```

Hermes 的 MCP 配置需要启动 `mcp_server.py`，并把控制入口和 Key 注入进程环境。不同 Hermes 版本的配置文件字段可能不同，下面是通用形态：

```yaml
mcpServers:
  telegram-media-downloader:
    command: /path/to/.venv-mcp/bin/python
    args:
      - /path/to/telegram_media_downloader/mcp_server.py
    env:
      TMD_MCP_BASE_URL: https://tgdn.wyichuan.cc
      TMD_MCP_API_KEY: <从受保护的密钥管理方式注入>
```

`TMD_MCP_BASE_URL` 可省略，默认值就是 `https://tgdn.wyichuan.cc`。MCP 进程启动时不自动发现服务、不启动下载器；入口不可达、TLS 失败或下载器返回非预期响应时，工具会返回 `service_unavailable`。

## 可调用工具

### 资源包和下载任务

| 工具 | 用途和边界 |
| --- | --- |
| `search_resource_packages` | 按关键词、频道、日期、下载状态和游标查询资源包。返回所有非 `superseded` 包；只有 `downloadable: true`（即 `boundary_status: stable`）的包可以提交下载。 |
| `get_resource_package` | 查询单个资源包及分页媒体条目；非稳定包可以查看但不能提交。 |
| `submit_download` | 按显式 `package_ids` 提交下载，必须提供 `idempotency_key`；不会读取、修改或清空 Web 控制台的勾选状态。重复幂等键返回已有批次。 |
| `get_download_task` | 按字符串 `task_id` 查询一个任务及其包/文件进度。 |
| `list_download_tasks` | 查询最近任务，可按状态和数量限制筛选；只覆盖任务存储保留的最近记录，不提供时间范围历史检索。 |
| `get_system_status` | 查询健康阶段、下载状态、速度、磁盘和任务计数。 |
| `pause_downloads` | 在 owner loop 上显式设置全局暂停状态，重复调用保持暂停。 |
| `resume_downloads` | 在 owner loop 上显式恢复全局下载状态。 |
| `cancel_download_task` | 在 owner loop 上取消任务；根据任务生命周期返回 `cancelled` 或 `removed`。运行态缺少句柄时返回 `runtime_handle_missing`。 |

### 关键词监控

| 工具 | 用途和边界 |
| --- | --- |
| `list_keyword_monitors` | 查询监控组、总数、启用数、停用数和触发摘要。 |
| `get_keyword_monitor` | 查询一个监控组的完整配置和汇总状态。 |
| `create_keyword_monitor` | 创建监控组，至少需要一个 `match_keywords`；创建后立即匹配当前稳定资源包。 |
| `update_keyword_monitor` | 替换监控组配置，更新后立即执行现有匹配逻辑。 |
| `delete_keyword_monitor` | 删除监控配置，不删除已产生的历史下载任务。 |
| `get_keyword_monitor_history` | 分页查询命中资源包、匹配词、来源、批次、包状态和任务进度。 |
| `retry_keyword_monitor_failures` | 通过 owner loop 重试当前可恢复失败；没有可恢复失败时返回 `state_conflict`，不会创建空任务。 |

关键词规则与 Web 页面一致：关键词会规范化并去重，必要关键词必须全部命中，匹配关键词至少命中一个，黑名单命中会排除结果。

## 错误码

| 错误码 | 含义 |
| --- | --- |
| `invalid_request` | 参数、JSON 字段或分页输入不合法。 |
| `unauthorized` | Bearer Key 缺失或错误。MCP 不接受 Session/Cookie。 |
| `not_found` | 资源包、任务或监控组不存在。 |
| `state_conflict` | 当前状态不允许操作，或没有可重试失败。 |
| `redownload_required` | 已完成或 revision 已变化，必须显式确认 `redownload: true`。 |
| `runtime_handle_missing` | 任务仍处于运行态，但进程内运行句柄已不可用。 |
| `rate_limited` | Key 校验失败次数过多，需要等待后重试。 |
| `resource_delivery_disabled` | 旧的 Resource Bot 发布链路已停用。 |
| `service_unavailable` | Web 进程、owner loop、频道服务或 HTTPS 入口不可用。 |

## `resource_delivery` 状态与恢复

“主账号下载 → 暂存频道 → Resource Bot 转发到用户频道”的 `resource_delivery` 链路已明确停用：不再启动 Resource Bot 或发布服务，不再注册资源管理命令。发布读接口返回 `disabled: true` 和空列表，发布写接口返回 `410 resource_delivery_disabled`；旧模块和数据库仍保留，便于回滚。

恢复时应回滚本次停用链路对应的独立提交，并重新核对 `BotManager`、发布接口和 Web 面板，不要仅重新填写 `resource_bot_token`。MCP 控制层可以单独通过 `mcp.enabled: false` 停用，不影响 Web 控制台和已存在的下载批次。

## 手工验收

在下载器可访问的机器上执行，Key 通过受保护的环境变量提供：

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://tgdn.wyichuan.cc/api/mcp/ping
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $TMD_MCP_API_KEY" \
  https://tgdn.wyichuan.cc/api/mcp/ping
curl -s -H "Authorization: Bearer $TMD_MCP_API_KEY" \
  "https://tgdn.wyichuan.cc/api/mcp/packages?page_size=5" | head -c 400
```

预期结果依次是无 Key 的 `401`、有效 Key 的 `200`，以及包含 `boundary_status` 和 `downloadable` 字段的 JSON。`mcp.enabled: false` 时整个 `/api/mcp/` 路径返回 `404`。

## 已知但本次未处理的风险

- 源站 80 端口当前可以绕过 Cloudflare 直连；MCP 的安全设计不依赖“只能从 Cloudflare 进入”。
- 控制台仍运行在现有 Werkzeug 开发服务器上；本次只增加 Bearer 鉴权和失败限速，不改部署服务器形态。
- Web 登录、Session、CSRF 逻辑保持原样；MCP Key 是独立凭据，不能用于浏览器路由。
