# 频道批量下载：错位归档 + 选择作用域 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复频道批量下载的两个独立缺陷——跨包错位归档（数据损坏）与选择作用域（下载了没勾的包）。

**Architecture:** B1 把 `download_prepared_messages` 的"包完成"屏障从易溢出的聚合计数器换成"本包每个 message_id 到终态"的精确判定；B2 把命名上下文在入队时快照进队列条目，出队命名优先用条目自带上下文（纵深防御）；A2 在批次创建成功后清空该库选择；A1 在前端下载前用服务端真实数字弹确认并修正 redownload 判定口径。

**Tech Stack:** Python 3 / asyncio / pyrogram、SQLite（`channel_library.sqlite3`、`web_tasks.sqlite3`）、Flask + 原生 JS 前端（`module/templates/index.html`）、pytest。

## Global Constraints

- 不改 `channel_library.sqlite3` / `web_tasks.sqlite3` 的 schema，不做数据迁移。
- 不改持久选择存储模型（`select_filtered` 全选仍高效）。
- 非批量/prescan/bot 下载路径行为保持不变（B2 的命名上下文覆盖必须是"可选、缺省回退"）。
- 保持文件原编码；不顺手重构无关代码；每行改动可追溯到本计划。
- 服务器 1 vCPU / 1 GiB，不引入额外常驻内存或全局状态。
- 本地不启动下载服务（需实时 Telegram 客户端）；前端改动用 scratchpad 浏览器 harness + mock 数据验证。
- 每个任务 TDD：先写会 RED 的测试，跑到 RED，再实现到 GREEN，最后提交。

---

### Task 1: B1 — 按精确 message_id 集合判包完成

**Files:**
- Modify: `media_downloader.py`（`download_prepared_messages`，约 2200–2307；新增模块级私有helper）
- Test: `tests/test_media_downloader.py`（新增 helper 单测）、`tests/test_channel_library_download.py`（新增/扩展批量集成测试）

**Interfaces:**
- Produces: `_package_download_complete(node, message_ids: set[int]) -> bool` —— 当 `message_ids` 中每个 id 在 `node.download_status` 里都存在且不等于 `DownloadStatus.Downloading` 时返回 `True`。
- Consumes: `node.download_status`（真实路径在 `media_downloader.py:808` 逐条置终态；scan 失败项在 `download_prepared_messages` 内置 `FailedDownload`）。

- [ ] **Step 1: 写 helper 失败测试**

在 `tests/test_media_downloader.py` 的 `MediaDownloaderTestCase` 内新增：

```python
def test_package_download_complete_waits_for_exact_message_ids(self):
    import media_downloader
    from module.app import DownloadStatus

    class N:
        pass
    node = N()
    node.download_status = {
        101: DownloadStatus.Downloading,
        102: DownloadStatus.SuccessDownload,
    }
    ids = {101, 102}
    # 101 仍在下载中 -> 未完成
    self.assertFalse(media_downloader._package_download_complete(node, ids))
    # 全部终态（含 Failed/Skip）-> 完成
    node.download_status[101] = DownloadStatus.FailedDownload
    self.assertTrue(media_downloader._package_download_complete(node, ids))
    # 缺失的 id 视为未完成
    self.assertFalse(media_downloader._package_download_complete(node, {101, 102, 103}))
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `.venv/bin/python -m pytest tests/test_media_downloader.py -k package_download_complete -q`
Expected: FAIL（`_package_download_complete` 不存在）

- [ ] **Step 3: 实现 helper**

在 `media_downloader.py` 模块级（`download_prepared_messages` 之前）新增：

```python
def _package_download_complete(node, message_ids) -> bool:
    """True when every message_id has reached a terminal download status."""
    status = getattr(node, "download_status", None) or {}
    for message_id in message_ids:
        state = status.get(message_id)
        if state is None or state == DownloadStatus.Downloading:
            return False
    return True
```

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `.venv/bin/python -m pytest tests/test_media_downloader.py -k package_download_complete -q`
Expected: PASS

- [ ] **Step 5: 把等待循环改为按本包 message_id 集合判完成**

在 `download_prepared_messages` 中：`media_messages` 经 `download_filter` 重新赋值（约 2198）之后、进入 for 入队循环之前，计算本包 id 集合：

```python
package_message_ids = {message.id for message in media_messages} | set(failed_message_ids)
```

把等待循环（当前 `while True:` 用 `completed_tasks >= expected_message_tasks` 判定，约 2282–2299）改为：

```python
while True:
    if _package_download_complete(node, package_message_ids):
        logger.info("所有下载任务已完成")
        break
    if not node.is_running or node.is_stop_transmission:
        logger.info("任务已停止，结束消息下载等待")
        break
    await report_bot_status(node.bot, node)
    await asyncio.sleep(5)
```

保留 `expected_message_tasks`/`completed_tasks_baseline` 相关的日志计算不动（仅进度打印用），完成判据只用 `package_message_ids`。保留后续 `report_bot_status` 与 finally 清理不变。

- [ ] **Step 6: 写批量集成失败测试（跨包不错位）**

在 `tests/test_channel_library_download.py` 新增测试：2 包批次（包 A 起始 message_id 小、包 B 大），用 fake `add_download_task`，让**包 A 的最后一条消息**在"聚合计数已达阈值之后"才置终态，从而在旧逻辑下 `download_prepared_messages` 会提前返回、主循环覆盖命名上下文。断言：每条被 `upsert_file` 记录的 `save_path`/文件名归属其**自身包**（包 A 的消息不出现在包 B 的文件夹上下文里）。参考现有 `test_run_download_batch_streams_one_package_into_memory_at_a_time` 的夹具构造 fake client / fake add_download_task / task_store，实现要点：

```python
# fake add_download_task: 先把除最后一条外的消息置终态并 human 计数虚高，
# 最后一条延迟到 node.package_naming_context 已切换后再置终态，
# 记录每条消息落地时的 node.package_naming_context.start_message_id。
# 断言 recorded[msg_id].start_message_id 等于该消息所属包的 start_message_id。
```

Run（RED）: `.venv/bin/python -m pytest tests/test_channel_library_download.py -k cross_package_no_misfile -q`
Expected: 旧逻辑 FAIL（包 A 尾消息记录到包 B 的 start_message_id）

- [ ] **Step 7: 跑集成测试确认 GREEN，并跑相关回归**

Run: `.venv/bin/python -m pytest tests/test_channel_library_download.py tests/test_media_downloader.py -q`
Expected: 全 PASS

- [ ] **Step 8: 提交**

```bash
git add media_downloader.py tests/test_media_downloader.py tests/test_channel_library_download.py
git commit -m "fix: gate channel package completion on exact message-id set (B1)"
```

---

### Task 2: B2 — 命名上下文绑定到队列条目（纵深防御）

**Files:**
- Modify: `media_downloader.py`（`add_download_task` 入队处约 657；`worker` 解包约 1495–1535；`download_task` 签名与 `_get_media_meta` 调用；`_get_media_meta` 约 557–582）
- Test: `tests/test_media_downloader.py`

**Interfaces:**
- Produces: 队列条目扩展为可带命名快照的 4 元组 `(message, node, download_intent, naming_snapshot)`，其中 `naming_snapshot` 为 `None` 或 `dict(context=PackageNamingContext, item=PackageMediaItem|None)`；`_get_media_meta(..., naming_snapshot=None)` 新增可选参数，非空时优先于 `node.package_naming_context` / `node.package_media_items`。
- Consumes: `node.package_naming_context`、`node.package_media_items`（Task 1 不改这两者的写入时机）。

- [ ] **Step 1: 写 `_get_media_meta` 覆盖优先失败测试**

在 `tests/test_media_downloader.py` 新增：构造一条 message + node，`node.package_naming_context` 设为 P2（start_message_id=222），传入 `naming_snapshot` 携带 P1（start_message_id=111）；断言返回的文件名走 P1 的 `111-...` 路径而非 P2。参考现有对 `_get_media_meta` / `build_package_name_for_strategy` 的用法组织断言：

```python
# 期望 gen_file_name 以 "111-" 开头（P1），即使 node.package_naming_context 是 P2
self.assertIn("111-", file_name)
self.assertNotIn("222-", file_name)
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `.venv/bin/python -m pytest tests/test_media_downloader.py -k naming_snapshot -q`
Expected: FAIL（`naming_snapshot` 参数不存在）

- [ ] **Step 3: 实现 `_get_media_meta` 覆盖优先**

在 `_get_media_meta` 签名加可选 `naming_snapshot=None`；在读取 `node.package_naming_context`（约 557）处改为：`context = (naming_snapshot or {}).get("context") or getattr(node, "package_naming_context", None)`；`package_item` 优先取 `(naming_snapshot or {}).get("item")`，否则回退现有 `node.package_media_items.get(message.id)`。其余逻辑不变。非批量路径 `naming_snapshot=None` 时行为与现状完全一致。

- [ ] **Step 4: 跑测试确认 GREEN**

Run: `.venv/bin/python -m pytest tests/test_media_downloader.py -k naming_snapshot -q`
Expected: PASS

- [ ] **Step 5: 入队快照 + worker 透传 + download_task 透传**

- `add_download_task`（约 657）入队时构造快照（仅当 `node.package_naming_context` 存在）：
  ```python
  naming_snapshot = None
  ctx = getattr(node, "package_naming_context", None)
  if ctx is not None:
      items = getattr(node, "package_media_items", None) or {}
      naming_snapshot = {"context": ctx, "item": items.get(msg_id)}
  await queue.put((message, node, download_intent, naming_snapshot))
  ```
- `worker` 解包（约 1495）新增 4 元组分支，保留 2/3 元组兼容；把 `naming_snapshot` 传给 `download_task(..., naming_snapshot=naming_snapshot)`（3 元组时 `naming_snapshot=None`）。
- `download_task` 签名加可选 `naming_snapshot=None`，在其内部调用 `_get_media_meta` 处透传该参数。

- [ ] **Step 6: 写 worker 兼容 + 端到端命名快照测试并跑 GREEN**

新增测试：入队一条 package 消息后，把 `node.package_naming_context` 改成 P2，再手动驱动 worker/`download_task`（或直接断言 `add_download_task` 放入队列的条目第 4 位携带 P1 快照），断言最终文件名走 P1。并保留一条 3 元组（无快照）路径断言回退到 `node.package_naming_context`。

Run: `.venv/bin/python -m pytest tests/test_media_downloader.py -q`
Expected: 全 PASS（含既有 worker/queue 相关测试）

- [ ] **Step 7: 提交**

```bash
git add media_downloader.py tests/test_media_downloader.py
git commit -m "fix: bind package naming context to queue item (B2 defense-in-depth)"
```

---

### Task 3: A2 — 批次创建成功后自动清空该库已选

**Files:**
- Modify: `module/channel_library_store.py`（`create_download_batch_result`，约 1386–1559）
- Test: `tests/test_channel_library_download.py`

**Interfaces:**
- Consumes: 现有 `clear_selection` 语义（`DELETE FROM channel_package_selections WHERE library_id=?`）与 `selection_summary`。
- Produces: `create_download_batch_result` 在**新建**批次（`created == True`）成功提交后，于**同一事务**内清空该库 `channel_package_selections`；幂等命中（`created == False`）不动选择。

- [ ] **Step 1: 写失败测试**

在 `tests/test_channel_library_download.py` 新增（复用 `make_download_service` 夹具，其已建带选择的 library）：

```python
def test_create_download_batch_clears_selection(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        assert service.store.selection_summary(library["id"])["selected_count"] > 0
        service.create_download_batch(library["id"], "clear-key")
        assert service.store.selection_summary(library["id"])["selected_count"] == 0
        # 幂等命中不报错、仍为已清空态
        service.create_download_batch(library["id"], "clear-key")
        assert service.store.selection_summary(library["id"])["selected_count"] == 0
    finally:
        loop.close()
```

- [ ] **Step 2: 跑测试确认 RED**

Run: `.venv/bin/python -m pytest tests/test_channel_library_download.py -k clears_selection -q`
Expected: FAIL（批次后仍有选择）

- [ ] **Step 3: 实现事务内清空**

在 `create_download_batch_result` 的 `else`（新建）分支、所有包 item 插入与 `channel_packages` 状态更新完成之后、`with self.connect()` 块内、`return` 之前，加入：

```python
connection.execute(
    "DELETE FROM channel_package_selections WHERE library_id = ?",
    (library_id,),
)
```

（在既有 `BEGIN IMMEDIATE` 事务内，与批次快照同原子提交；幂等分支不进入此代码。）

- [ ] **Step 4: 跑测试确认 GREEN + 回归（含现有幂等/快照测试）**

Run: `.venv/bin/python -m pytest tests/test_channel_library_download.py -q`
Expected: 全 PASS（若既有测试假定"批次后选择仍在"，改为符合新语义——批次后选择已清空；不放宽其它断言）

- [ ] **Step 5: 提交**

```bash
git add module/channel_library_store.py tests/test_channel_library_download.py
git commit -m "fix: clear channel selection after batch creation (A2)"
```

---

### Task 4: A1 — 前端下载前真实数量确认 + 修正 redownload 判定

**Files:**
- Modify: `module/templates/index.html`（下载按钮处理 `channel_download_selection` 约 1239–1244；`submitChannelDownload` 约 1226）
- Verify: scratchpad 浏览器 harness + mock 数据（无 pytest 覆盖，前端逻辑）

**Interfaces:**
- Consumes: `state.channel.selection`（`GET /selection` 摘要：`selected_count`、`media_count`），`loadChannelSelection()`。
- Produces: 下载前 `confirm(...)` 用服务端真实 `selected_count`/`media_count`；`redownload` 判定改为基于服务端摘要而非可见子集。

- [ ] **Step 1: 实现确认 + redownload 口径修正**

把 `#channel_download_selection` click 处理改为先刷新并读取服务端摘要，再确认：

```javascript
$('#channel_download_selection').addEventListener('click', async () => {
  const libraryId = state.channel.selectedLibraryId;
  await loadChannelSelection();                       // 拉取权威摘要
  const sel = state.channel.selection || {};
  const n = Number(sel.selected_count) || 0;
  const m = Number(sel.media_count) || 0;
  if (n <= 0) { showChannelNotice('请先选择稳定包', 'error'); return; }
  if (!confirm(`即将下载 ${n} 个包 · ${m} 个文件（可能包含当前筛选下未显示的已选包）。确认下载？`)) return;
  // redownload 判定改用服务端信号：有失效/需重下由后端 409 redownload_required 驱动
  await submitChannelDownload(false);
});
```

保留 `submitChannelDownload` 内既有的 `redownload_required` → 二次 `confirm` → `submitChannelDownload(true)` 流程（后端权威判定），删除原先基于 `state.channel.packages.filter(...)`（可见子集）的 `redownload` 预判。

- [ ] **Step 2: 浏览器 harness 验证**

用 scratchpad 起一个静态 harness 加载 `index.html` 的下载区块 + mock：模拟 `GET /selection` 返回 `{selected_count:71, media_count:91, ...}`，点击"下载所选"，断言弹出确认文案含"71 个包 · 91 个文件"；取消则不 POST，确认则 POST `/download-batches`（mock 拦截，校验请求体仅 `{redownload:false}` + `Idempotency-Key`）。记录验证证据（截图/console）写入 progress.md 的 Testing。

- [ ] **Step 3: 提交**

```bash
git add module/templates/index.html
git commit -m "fix: confirm true selection count before channel download (A1)"
```

---

### Task 5: 整分支收口（全量测试 + 静态检查 + 文档）

**Files:**
- Modify: `progress.md`（追加一轮，固定格式）、必要时 `docs/`

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全绿（对齐既有基线 `480 passed, 1 skipped` 量级，新增测试计入）

- [ ] **Step 2: 静态检查**

Run: `.venv/bin/python -m pylint --errors-only media_downloader.py module/channel_library_store.py module/web.py`（仅关注新引入错误；已知 `STARTUP_SCAN_WINDOW_SEC` E0602、`os`/`pyrogram` E1101 误报除外）；`git diff --check` 干净。

- [ ] **Step 3: progress.md 追加本轮记录**（What was done / Testing / Notes：Changed files + Rollback）

- [ ] **Step 4: 提交**

```bash
git add progress.md docs
git commit -m "docs: log channel batch misfiling + selection scope fix"
```

---

## 交付与部署（收口后）

- 整分支复审（whole-branch review）通过后：合并到 `master`、`git push origin master`。
- 部署 RackNerd：`ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && systemctl restart tg-downloader.service'`，验证 `https://tgdn.wyichuan.cc/` 返回 302 到 login，在 progress.md 记录部署。
- 回滚：`git revert` 本分支合并；无 schema/数据迁移；部署回滚保留 `*.sqlite3`。

## Self-Review 覆盖对照

- 错位归档根因（计数器屏障 + 共享命名上下文）→ Task 1（B1）+ Task 2（B2）。
- 计数溢出 B3 → 经 B1 后不再造成错位，作为文档化后续项延后（progress.md Notes 记录），本计划不含 B3 任务以避免开放式排查。
- 选择作用域（下载没勾的包）→ Task 3（A2 自动清空）+ Task 4（A1 真实数量确认 + redownload 口径修正）。
- 全量验证 + 部署 → Task 5 + 部署段。
