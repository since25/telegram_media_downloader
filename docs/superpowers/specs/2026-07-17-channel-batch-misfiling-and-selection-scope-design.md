# 频道批量下载：错位归档 + 选择作用域 修复设计

日期：2026-07-17
分支：`fix/channel-batch-misfiling-and-selection-scope`

## 背景与问题

线上（RackNerd，library 4，批次 `channel-batch-b5f6741d…`，状态 failed）出现两个相互独立、但叠加导致同一次事故的缺陷。已用生产 DB + 服务日志实锤：

- **Bug B — 错位归档（数据损坏）**：包 17899（消息 121070–121159，共 90 个）中 40 个文件（121120–121159）被写进了另一个包 #18277（消息 129365）的文件夹 `2025_12/129365-明天睡醒删除这个视频/`。
- **Bug A — 选择作用域（下载了没勾的包）**：这次批次把用户没打算选的包 17899（90 个消息）和用户想要的 #18277（1 个消息）一起下了。

数据侧已单独清理完成（错位文件移入云盘隔离区、DB 错位记录已删、均可回滚），本设计只覆盖代码修复。

## Bug B — 错位归档

### 根因

1. `download_prepared_messages`（`media_downloader.py`）判断"本包是否下完"用的是**聚合计数器**：`node.success_download_task + node.failed_download_task + node.skip_download_task >= expected_message_tasks`（`expected = baseline + len(media_messages) + len(failed_message_ids)`）。
2. 下载走**进程级全局** `asyncio.Queue` + `worker`；文件的输出文件夹/文件名在**出队时**由 `_get_media_meta` 读取共享的 `parent_node.package_naming_context` 现算。
3. 批量主循环 `download_prescan_packages` 串行处理各包，**每换一个包就覆盖** `parent_node.package_naming_context`（`{start_message_id}-{title}` 决定文件夹名）。
4. 计数器**溢出**（日志：`已完成 96/90 → 所有下载任务已完成`），屏障在本包消息尚未从队列排空时提前放行。主循环随即前进到 #18277 并覆盖命名上下文（`start_message_id=129365`），队列里残留的 121120–121159 出队时拿到新上下文 → 落入 `129365-…` 文件夹（月份段 `2025_12` 仍来自消息自身日期，形成 `2025_12/129365-…` 这种不可能组合，正是错位铁证）。

### 修复

**B1 — 按精确 message_id 集合判完成（对症、核心）**
- 在 `download_prepared_messages` 中，把等待循环从"聚合计数器达阈值"改成"**本包每个 message_id 都到终态**"。
- 本包 message_id 集合 = 本次 `media_messages` 的 id ∪ `failed_message_ids`。
- 终态判定：`node.download_status[mid]` 存在且不等于 `DownloadStatus.Downloading`（即 Success/Failed/Skip 之一）。`download_status[mid]` 由真实下载路径在 `media_downloader.py:808` 逐条置终态，已确认可用。
- 保留既有的 `not node.is_running or node.is_stop_transmission` 提前退出，避免个别消息永不落地导致挂死。
- 保留周期性 `report_bot_status`。
- 效果：本包消息全部落地前主循环不前进，命名上下文不会在有消息挂起时被覆盖。对计数溢出天然免疫。

**B2 — 命名上下文绑定到队列条目（纵深防御）**
- `add_download_task` 入队时，把当前 `node.package_naming_context` 与该消息的 `node.package_media_items.get(message.id)` **快照进队列条目**。
- 队列条目由裸元组 `(message, node, intent)` 改为一个小结构（含 `naming_context`、`package_item` 两个可选字段）；`worker` 与 `_get_media_meta` 相应改为优先使用条目自带上下文，缺省再回退到 `node.package_naming_context`（保持非批量路径行为不变）。
- 效果：即便有漏网残留消息，也按其**自身包**命名，错位在结构上不可能。

**B3 — 计数溢出附带修正（小）**
- 查明 `已完成 96/90` 的 +6 来源（大概率相册/媒体组成员或重试导致 `node.stat(...)` 重复计数），消除重复自增，使进度% 与 `success_count` 准确。
- 若根因过深、修复超出小改动范围，则记录并延后；B1 已保证溢出不再造成错位，B3 仅为计量准确性。

### 测试（TDD，先 RED）

- **B1 复现测试**：构造 2 包批次 + 可控的假 queue/worker，让包 1 的部分消息在"计数器本会溢出放行"之后才落地；断言每个文件被记录的 `save_path` 都落在**自己包**的文件夹（包 1 无任何文件出现在包 2 的文件夹下）。当前代码 RED，B1 后 GREEN。
- **B2 单测**：在上下文 P1 下入队一条消息，随后把 `node.package_naming_context` 覆盖为 P2，再出队；断言该文件按 P1 命名。
- **回归**：现有 streaming/batch 相关测试（`tests/test_channel_library_download.py`、`tests/test_media_downloader.py`）全绿。

## Bug A — 选择作用域

### 根因

- `POST /api/channel-libraries/<id>/download-batches`（`module/web.py`）请求体只有 `{redownload}` + `Idempotency-Key`；批次由 `create_download_batch_result`（`module/channel_library_store.py`）从**全库** `channel_package_selections.selected = 1` 快照生成。
- 选择按库持久、批次创建后**不清空**；包列表带筛选/分页，残留勾选**不可见**。
- 前端下载按钮的 `redownload` 判定只用**当前已加载**的包（`index.html:1240`），与服务端实际下载集合口径不一致。

### 修复

**A1 — 下载前用服务端真实数字确认**
- 前端派发前，用权威的选择摘要（复用现有 `GET /api/channel-libraries/<id>/selection` → `selection_summary`）弹确认框：`即将下载 N 包 · M 文件（可能包含当前筛选下未显示的已选包）`，显式确认才 POST。
- 同时把 `redownload` 判定改为基于服务端摘要（`invalidations`/已完成态）而非可见子集，消除"跳过重下确认"的口径错位。

**A2 — 批次创建成功后自动清空该库已选**
- 在批次成功提交后清空该库 `channel_package_selections`。批次快照自包含（`_run_download_batch_owned` 只读 `list_download_batch_package_summaries` / `get_download_batch_package_items`，不读实时选择，已确认），清空不影响执行与重试/恢复，且根除残留累积。
- 幂等命中既有批次（`created = False`）时不重复清空（已是清空态或由首次创建清空）。

> 不采用"前端把所有包 ID 传给后端"：`select_filtered`（全选筛选结果）可能上千个包，传 ID 列表不划算；确认 + 自动清空更小且与全选模型兼容。

### 测试

- **后端**：创建批次成功后 `selection_summary.selected_count == 0`；用批次快照跑 `run_download_batch` 仍正常（清空不影响执行）。
- **Web**：创建响应/确认流程能反映真实计数；构造"另一筛选下的残留已选"，断言确认所示 N/M 把它算进去（守住不可见选择陷阱）。

## 非目标（YAGNI）

- 不改持久选择存储模型（全选仍高效）。
- 不改 `channel_library.sqlite3` schema，不做数据迁移。
- 不顺手重构无关代码。

## 交付与回滚

- 按标准流程：本 feature 分支 → 子代理驱动实现（每任务实现者 + 复审者）→ 整分支复审 → 合并/推送/部署 RackNerd。
- 全程 TDD（先写会 RED 的复现测试，再修）。
- 回滚：`git revert` 本分支合并；无 schema/数据迁移；部署回滚保留 `*.sqlite3`。
