# Web Task Console UX and Ranged Batch Download — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Web task dashboard legible (status badges, progress bars, visible errors, readable counts, stable polling) and extend Web prescan into a ranged batch scan with a user-set message count, raised limits, and a clearer selection/batch-download UX.

**Architecture:** Feature A is pure frontend rendering of data the API already returns (`module/templates/index.html`, `module/static/css/index.css`). Feature B raises prescan limit constants and adds one bulk-select endpoint in `module/web.py`, then exposes a scan-count input and selection controls in the frontend. The scan/download pipeline, task store, and auth are unchanged.

**Tech Stack:** Flask, layui 2.x tables + jQuery (vendored under `module/static/layui`), Python 3 `unittest` in `tests/module/test_web.py`.

**Design spec:** `docs/superpowers/specs/2026-07-14-web-task-console-ux-and-batch-design.md`

## Global Constraints

- Frontend only for Feature A: touch only `module/templates/index.html` and `module/static/css/index.css`. Do not change `module/web.py`, `module/task_state.py`, or the download pipeline in Feature A.
- Do NOT start the downloader service locally (it needs a live Telegram client). Backend verification is `pytest`; frontend verification is a static scratchpad harness opened in the browser.
- Reuse existing helpers: `escapeHtml(value)` for all interpolated text; layui background classes `layui-bg-blue|green|orange|red|cyan|gray`; existing `element`, `table`, `form`, `layer`, `$` from `layui.use`.
- Feature B raised limits (exact values): `WEB_PRESCAN_DEFAULT_MESSAGES = 2000`, `WEB_PRESCAN_MAX_MESSAGES = 10000`, `WEB_PRESCAN_DEFAULT_PACKAGES = 30`, `WEB_PRESCAN_MAX_PACKAGES = 100`. `WEB_PRESCAN_DEFAULT_BATCH_SIZE`, `WEB_PRESCAN_MAX_BATCH_SIZE`, `WEB_PRESCAN_BATCH_DELAY_SECONDS` unchanged.
- All Web APIs require the existing login session; new endpoint included.
- Keep existing code style; no unrelated refactors; every changed line traces to this plan.
- Run the regression suite after each task: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`.
- Commit at the end of each task. Do not push (the parent session handles deploy).

---

### Task 1: Feature A — task dashboard rendering and polling stability

**Files:**
- Modify: `module/templates/index.html` (the `<script>` block, lines ~276–855, and the `#task_detail_list`/detail markup near lines ~58–83)
- Modify: `module/static/css/index.css` (append new rules)

**Interfaces:**
- Consumes (already in API payloads): task fields `task_id, source, task_type, status, title, error, total_count, success_count, failed_count, skipped_count, upload_success_count, current_file, workflow`; file fields `message_id, status, filename, total_size, download_progress, download_speed, error`.
- Produces (JS functions later steps and Task 3 rely on): `statusBadge(task)`, `taskProgressCell(task)`, `countCell(task)`, `fileStatusBadge(d)`, `fileProgressCell(d)`, `fileErrorCell(d)`, and the module-scope vars `lastTasksById`, `detailColsType`, `detailSignature`.

- [ ] **Step 1: Add CSS for badges, counts, mini progress bars, error text, empty states**

Append to `module/static/css/index.css`:

```css
.mini-progress { height: 8px; border-radius: 20px; background: #e6e6e6; overflow: hidden; }
.mini-progress-bar { height: 100%; background: #16baaa; transition: width .3s; }
.mini-progress-bar.mp-blue { background: #1e9fff; }
.mini-progress-bar.mp-green { background: #16b777; }
.mini-progress-bar.mp-red { background: #ff5722; }
.mini-progress-text { font-size: 12px; color: #969696; margin-top: 3px; }
.cnt-ok { color: #16b777; }
.cnt-fail { color: #ff5722; }
.cnt-skip { color: #969696; }
.cnt-up { color: #1e9fff; }
.cnt-strong { font-weight: 700; }
.file-error { color: #ff5722; }
.task-detail-error {
  margin: 8px 0; padding: 8px 12px; border-radius: 4px;
  background: #ffe6e6; color: #c0341d; font-size: 13px;
}
.task-detail-error[hidden] { display: none; }
```

- [ ] **Step 2: Add rendering helpers in the `layui.use(...)` callback**

In `module/templates/index.html`, inside the `layui.use([...], function () { ... })` block, after the existing `escapeHtml` function, add:

```javascript
var STATUS_META = {
  created: { cls: 'layui-bg-gray', label: 'created' },
  scanning: { cls: 'layui-bg-blue', label: 'scanning' },
  waiting_confirmation: { cls: 'layui-bg-cyan', label: 'waiting' },
  queued: { cls: 'layui-bg-blue', label: 'queued' },
  downloading: { cls: 'layui-bg-blue', label: 'downloading' },
  uploading: { cls: 'layui-bg-blue', label: 'uploading' },
  completed: { cls: 'layui-bg-green', label: 'completed' },
  completed_with_errors: { cls: 'layui-bg-orange', label: 'completed · errors' },
  failed: { cls: 'layui-bg-red', label: 'failed' },
  cancelled: { cls: 'layui-bg-gray', label: 'cancelled' }
};

function badge(status, cls, label, titleText) {
  var meta = STATUS_META[status] || { cls: cls || 'layui-bg-gray', label: label || status || '' };
  var title = escapeHtml(titleText || status || '');
  return '<span class="layui-badge ' + meta.cls + '" title="' + title + '">' + escapeHtml(meta.label) + '</span>';
}

function statusBadge(task) {
  return badge(task.status, null, null, task.error || task.status);
}

function fileStatusBadge(d) {
  return badge(d.status, null, null, d.error || d.status);
}

function progressClass(pct) {
  if (pct >= 100) { return 'mp-green'; }
  if (pct > 30) { return 'mp-blue'; }
  return 'mp-red';
}

function progressBar(pct, text) {
  pct = Math.max(0, Math.min(Math.round(pct), 100));
  var html = '<div class="mini-progress"><div class="mini-progress-bar ' + progressClass(pct) + '" style="width:' + pct + '%"></div></div>';
  if (text) { html += '<div class="mini-progress-text">' + escapeHtml(text) + '</div>'; }
  return html;
}

function taskProgressCell(task) {
  var total = Number(task.total_count || 0);
  if (total <= 0) { return '<span class="task-action-empty">-</span>'; }
  var done = Number(task.success_count || 0) + Number(task.failed_count || 0) + Number(task.skipped_count || 0);
  return progressBar(done / total * 100, done + ' / ' + total);
}

function countCell(task) {
  function seg(value, cls) {
    var n = Number(value || 0);
    var strong = (cls === 'cnt-fail' && n > 0) ? ' cnt-strong' : '';
    return '<span class="' + cls + strong + '">' + n + '</span>';
  }
  return seg(task.success_count, 'cnt-ok') + ' / ' + seg(task.failed_count, 'cnt-fail')
    + ' / ' + seg(task.skipped_count, 'cnt-skip') + ' / ' + seg(task.upload_success_count, 'cnt-up');
}

function fileProgressCell(d) {
  var pct = Number(d.download_progress || 0);
  var text = '';
  if (pct > 0 && pct < 100) { text = pct + '% · ' + (d.download_speed || ''); }
  return progressBar(pct, text);
}

function fileErrorCell(d) {
  if (!d.error) { return ''; }
  return '<span class="file-error">' + escapeHtml(d.error) + '</span>';
}
```

Delete the now-superseded `countText` function (it returned a plain string; `countCell` replaces it). Keep `currentFileText` and `workflowText`.

- [ ] **Step 3: Wire the task-list columns to the new renderers**

In the `table.render({ elem: '#task_list', ... })` call, update the `cols` so `status` uses `statusBadge`, add a `progress` column using `taskProgressCell`, and switch the counts column to `countCell`:

```javascript
cols: [[
  { field: 'task_id', title: 'task', width: 92 },
  { field: 'source', title: 'source', width: 88 },
  { field: 'task_type', title: 'type', width: 104 },
  { field: 'status', title: 'status', width: 130, templet: statusBadge },
  { field: 'title', title: 'title', minWidth: 180 },
  { field: 'workflow', title: 'preview', minWidth: 200, templet: workflowText },
  { field: 'progress', title: 'progress', width: 118, templet: taskProgressCell },
  { field: 'counts', title: 'ok/fail/skip/up', width: 150, templet: countCell },
  { field: 'current_file', title: 'current file', minWidth: 200, templet: currentFileText },
  { fixed: 'right', title: 'action', width: 132, toolbar: '#task_actions' }
]],
```

- [ ] **Step 4: Add the detail error banner element and the file detail error/progress columns**

In the markup, immediately before `<table class="layui-hide" id="task_detail_list" ...>` (around line 59), add:

```html
<div class="task-detail-error" id="task_detail_error" hidden></div>
```

Add module-scope state near the other `var` declarations (with `selectedTaskId`):

```javascript
var lastTasksById = {};
var detailColsType = null;
var detailSignature = '';
```

Define the shared file column set once (place it near the render helpers):

```javascript
var FILE_DETAIL_COLS = [[
  { field: 'message_id', title: 'message', width: 100 },
  { field: 'status', title: 'status', width: 120, templet: fileStatusBadge },
  { field: 'filename', title: 'file name', minWidth: 160 },
  { field: 'total_size', title: 'size', width: 90 },
  { field: 'download_progress', title: 'progress', width: 150, templet: fileProgressCell },
  { field: 'error', title: 'error', minWidth: 140, templet: fileErrorCell }
]];
```

- [ ] **Step 5: Preserve selected-row highlight after each task-list reload**

Add a `done` callback to the `#task_list` render config that re-applies the highlight:

```javascript
done: function () {
  element.render();
  if (selectedTaskId == null) { return; }
  var rows = this.config.data || [];
  for (var i = 0; i < rows.length; i++) {
    if (String(rows[i].task_id) === String(selectedTaskId)) {
      $(this.config.elem).next('.layui-table-view')
        .find('.layui-table-body tr[data-index="' + i + '"]').addClass('layui-table-click');
      break;
    }
  }
}
```

- [ ] **Step 6: Make the detail panel reload data-only and skip unchanged reloads**

Replace `loadTaskDetail` so it (a) shows/hides the task error banner from `lastTasksById`, (b) sets columns only when the detail type changes, (c) skips `table.reload` when a lightweight signature is unchanged. For the prescan branch keep the existing prescan columns behavior but also gate on the type/signature:

```javascript
function detailSig(items) {
  return (items || []).map(function (row) {
    return [row.message_id || row.package_id, row.status, row.download_progress, row.selected, row.error]
      .join(':');
  }).join('|');
}

function showDetailError(taskId) {
  var task = lastTasksById[taskId];
  var banner = $('#task_detail_error');
  if (task && task.error) {
    banner.text(task.error).removeAttr('hidden');
  } else {
    banner.attr('hidden', 'hidden').text('');
  }
}

function loadTaskDetail(taskId, taskType) {
  showDetailError(taskId);
  if (taskType === 'prescan') {
    $.ajax({
      url: 'api/prescans/' + encodeURIComponent(taskId) + '/packages?page=1&page_size=50',
      type: 'get', dataType: 'json',
      success: function (result) {
        var items = result.items || [];
        var sig = 'prescan:' + detailSig(items);
        if (detailColsType === 'prescan' && sig === detailSignature) { return; }
        var reload = { data: items };
        if (detailColsType !== 'prescan') {
          reload.cols = [[
            { field: 'package_id', title: 'package', width: 100 },
            { field: 'selected', title: 'selected', width: 100, templet: packageSelectedText },
            { field: 'start_message_id', title: 'start', width: 110 },
            { field: 'end_message_id', title: 'end', width: 110 },
            { field: 'media_count', title: 'media', width: 90 },
            { field: 'known_total_size', title: 'known size', width: 120 },
            { field: 'title', title: 'title', minWidth: 220 },
            { fixed: 'right', title: 'action', width: 110, toolbar: '#prescan_package_actions' }
          ]];
        }
        table.reload('task_detail_list_table', reload);
        detailColsType = 'prescan';
        detailSignature = sig;
      },
      error: function () {
        table.reload('task_detail_list_table', { data: [] });
        detailColsType = 'prescan'; detailSignature = '';
      }
    });
    return;
  }
  $.ajax({
    url: 'api/tasks/' + encodeURIComponent(taskId) + '/files?page=1&page_size=50',
    type: 'get', dataType: 'json',
    success: function (result) {
      var items = result.items || [];
      var sig = 'files:' + detailSig(items);
      if (detailColsType === 'files' && sig === detailSignature) { return; }
      var reload = { data: items };
      if (detailColsType !== 'files') { reload.cols = FILE_DETAIL_COLS; }
      table.reload('task_detail_list_table', reload);
      detailColsType = 'files';
      detailSignature = sig;
    },
    error: function () {
      table.reload('task_detail_list_table', { data: [] });
      detailColsType = 'files'; detailSignature = '';
      selectedTaskId = null; selectedTaskType = null;
    }
  });
}
```

Also update the initial `#task_detail_list` render to use `FILE_DETAIL_COLS` for its `cols`, and reset the detail state when the row selection changes. In the `table.on('row(task_list)', ...)` handler, add `detailColsType = null; detailSignature = '';` before calling `loadTaskDetail` so a new selection always rebuilds columns.

- [ ] **Step 7: Populate `lastTasksById` and add empty-state text**

In `updateTaskDashboard`, after receiving `result`, build the lookup before reloading:

```javascript
lastTasksById = {};
(result.tasks || []).forEach(function (task) { lastTasksById[task.task_id] = task; });
```

Add `text: { none: 'No tasks yet — paste a Telegram link above to start a download.' }` to the `#task_list` render config, and `text: { none: 'Select a task to see its files.' }` to the `#task_detail_list` render config.

- [ ] **Step 8: Verify no backend regression**

Run: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`
Expected: all pass (this task changes no Python).

- [ ] **Step 9: Visual smoke check with a scratchpad harness**

Create `<scratchpad>/taskui_harness.html` that loads layui from the repo (`file://` path to `module/static/layui/layui.js` and `layui/css/layui.css`) plus `module/static/css/index.css`, pastes the render helpers and two `table.render` calls, and feeds mock data covering: a `downloading` task with partial progress, a `completed_with_errors` task with `failed_count=2` and an `error`, a `failed` task with `total_count=0`, a `waiting_confirmation` prescan, and an empty list. Open it with the browser tool and confirm: colored status badges, task + file progress bars, red failed count in bold, error banner + file error text, and the empty-state message. Capture one screenshot.
Expected: all five render correctly; no console errors.

- [ ] **Step 10: Commit**

```bash
git add module/templates/index.html module/static/css/index.css
git commit -m "feat: enhance web task dashboard rendering"
```

---

### Task 2: Feature B backend — raised prescan limits and bulk select-all endpoint

**Files:**
- Modify: `module/web.py` (constants at lines ~66–72; new route after `select_prescan_package`, ~line 1148)
- Modify: `tests/module/test_web.py` (new tests modeled on `test_prescan_packages_api_and_selection`, line ~360)

**Interfaces:**
- Produces: `POST /api/prescans/<task_id>/packages/select-all` accepting JSON `{"selected": bool}`, returning `{"ok": true, "task_id", "selected": bool, "selected_count": int, "total": int}`; 404 `{"ok": false, "error": "prescan not found"}` when the prescan is missing. Task 3 (frontend) calls this endpoint.

- [ ] **Step 1: Write the failing test for select-all**

Add to `tests/module/test_web.py` (model on `test_prescan_packages_api_and_selection`):

```python
def test_prescan_select_all_and_clear(self):
    def make_pkg(pid):
        return SimpleNamespace(
            package_id=pid, title="Pack %d" % pid,
            start_message_id=100 + pid, end_message_id=105 + pid,
            media_count=2, messages=[], failed_message_ids=[],
        )
    with tempfile.TemporaryDirectory() as tmp_dir:
        app = build_web_test_app(tmp_dir)
        self.web_module._current_app = app
        self.web_module._flask_app.config["LOGIN_DISABLED"] = True
        self.web_module._pending_web_prescans["web-prescan-all"] = {
            "packages": [make_pkg(1), make_pkg(2), make_pkg(3)],
            "selected_package_ids": set(),
        }
        client = self.web_module.get_flask_app().test_client()

        select_all = client.post(
            "/api/prescans/web-prescan-all/packages/select-all",
            json={"selected": True},
        )
        clear_all = client.post(
            "/api/prescans/web-prescan-all/packages/select-all",
            json={"selected": False},
        )
        missing = client.post(
            "/api/prescans/does-not-exist/packages/select-all",
            json={"selected": True},
        )

        self.assertEqual(select_all.status_code, 200)
        self.assertEqual(select_all.get_json()["selected_count"], 3)
        self.assertEqual(select_all.get_json()["total"], 3)
        self.assertEqual(clear_all.get_json()["selected_count"], 0)
        self.assertEqual(missing.status_code, 404)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/module/test_web.py -k select_all_and_clear -q`
Expected: FAIL (404 for the select-all route because it does not exist yet).

- [ ] **Step 3: Raise the limit constants**

In `module/web.py` change the constants (lines ~66–69):

```python
WEB_PRESCAN_DEFAULT_MESSAGES = 2000
WEB_PRESCAN_MAX_MESSAGES = 10000
WEB_PRESCAN_DEFAULT_PACKAGES = 30
WEB_PRESCAN_MAX_PACKAGES = 100
```

Leave `WEB_PRESCAN_DEFAULT_BATCH_SIZE`, `WEB_PRESCAN_MAX_BATCH_SIZE`, and `WEB_PRESCAN_BATCH_DELAY_SECONDS` as they are.

- [ ] **Step 4: Add the select-all endpoint**

In `module/web.py`, immediately after the `select_prescan_package` function (ends ~line 1148), add:

```python
@_flask_app.route("/api/prescans/<task_id>/packages/select-all", methods=["POST"])
@login_required
def select_all_prescan_packages(task_id: str):
    """Select or clear every Web prescan package at once."""

    prescan = _pending_web_prescans.get(task_id)
    if not prescan:
        return jsonify({"ok": False, "error": "prescan not found"}), 404
    payload = request.get_json(silent=True) or {}
    selected = _as_bool(payload.get("selected"), True)
    packages = list(prescan.get("packages") or [])
    selected_ids = prescan.setdefault("selected_package_ids", set())
    selected_ids.clear()
    if selected:
        for package in packages:
            selected_ids.add(int(getattr(package, "package_id", 0) or 0))
    task = get_task_store().get_task(task_id)
    if task and task.workflow:
        task.workflow.selected_count = len(selected_ids)
        get_task_store().update_task(task_id, workflow=task.workflow)
    return jsonify(
        {
            "ok": True,
            "task_id": task_id,
            "selected": selected,
            "selected_count": len(selected_ids),
            "total": len(packages),
        }
    )
```

- [ ] **Step 5: Run the new test and the bounded-limits test**

Run: `.venv/bin/python -m pytest tests/module/test_web.py -k "select_all_and_clear or limits_are_bounded" -q`
Expected: PASS (the bounded-limits test compares against the constants, so raised values still pass).

- [ ] **Step 6: Run the full regression suite**

Run: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add module/web.py tests/module/test_web.py
git commit -m "feat: raise web prescan limits and add bulk package select"
```

---

### Task 3: Feature B frontend — scan-count input, selection summary, batch controls

**Files:**
- Modify: `module/templates/index.html` (the prescan submit area ~lines 49–57, the detail panel controls, and the `layui.use` script block)
- Modify: `module/static/css/index.css` (append controls/summary styles)

**Interfaces:**
- Consumes: `POST /api/tasks` prescan payload now includes `max_messages`; `POST /api/prescans/<task_id>/packages/select-all` from Task 2; existing `POST /api/tasks/<task_id>/confirm`. Prescan package rows expose `known_total_size_bytes` and `media_count` (already returned by `_package_summary`).

- [ ] **Step 1: Add the scan-count input and batch controls to the markup**

In the `.task-submit` block, after the mode `<select id="web_task_mode">`, add a count input shown only in prescan mode:

```html
<input type="number" id="web_task_count" class="layui-input task-count-input" min="1" max="10000" value="2000" placeholder="messages" style="display:none;">
```

Below the prescan detail table area (near the `prescan_package_actions` template), add a controls bar:

```html
<div class="prescan-controls" id="prescan_controls" hidden>
  <button type="button" class="layui-btn layui-btn-sm" id="prescan_select_all">Select all</button>
  <button type="button" class="layui-btn layui-btn-sm layui-btn-primary" id="prescan_clear_all">Clear all</button>
  <span class="prescan-summary" id="prescan_summary">0 packages selected</span>
  <button type="button" class="layui-btn layui-btn-sm" id="prescan_download">Download selected</button>
</div>
```

- [ ] **Step 2: Add CSS for the controls and summary**

Append to `module/static/css/index.css`:

```css
.task-count-input { width: 120px; }
.prescan-controls { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
.prescan-controls[hidden] { display: none; }
.prescan-summary { font-size: 13px; color: #5f5f5f; }
```

- [ ] **Step 2b: Toggle the count input with the mode select**

In the script block, after `form` is available, bind the mode change (the select is a native `<select>`; layui form may wrap it, so bind both change and layui form select):

```javascript
function syncModeInput() {
  var show = $('#web_task_mode').val() === 'prescan';
  $('#web_task_count').css('display', show ? '' : 'none');
}
$('#web_task_mode').on('change', syncModeInput);
form.on('select()', syncModeInput);
syncModeInput();
```

- [ ] **Step 3: Send `max_messages` on prescan submit**

In `submitWebTask`, build the payload with the count when in prescan mode:

```javascript
var mode = $('#web_task_mode').val();
var payload = { link: link, mode: mode };
if (mode === 'prescan') {
  payload.max_messages = Number($('#web_task_count').val() || 2000);
}
```

and send `JSON.stringify(payload)` instead of the current inline object.

- [ ] **Step 4: Show/hide the prescan controls and update the summary**

Add a helper that shows the controls only for a selected prescan and computes the summary from the current detail rows. Track the latest prescan rows in a module var `prescanRows = []`. In the prescan branch of `loadTaskDetail`, after computing `items`, set `prescanRows = items;` and call `updatePrescanControls(taskId)`. For non-prescan detail, hide the controls:

```javascript
var prescanRows = [];

function formatBytes(n) {
  n = Number(n || 0);
  var units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(i === 0 ? 0 : 2) + ' ' + units[i];
}

function updatePrescanControls(taskId) {
  var selected = prescanRows.filter(function (row) { return row.selected; });
  var media = selected.reduce(function (sum, row) { return sum + Number(row.media_count || 0); }, 0);
  var bytes = selected.reduce(function (sum, row) { return sum + Number(row.known_total_size_bytes || 0); }, 0);
  $('#prescan_summary').text(selected.length + ' packages · ' + media + ' media · ' + formatBytes(bytes));
  $('#prescan_controls').removeAttr('hidden');
}

function hidePrescanControls() {
  $('#prescan_controls').attr('hidden', 'hidden');
  prescanRows = [];
}
```

Call `hidePrescanControls()` at the start of the non-prescan (`files`) branch of `loadTaskDetail`.

Note: the prescan packages endpoint paginates at 50; the summary reflects the loaded page. Keep `page_size=50`; if a prescan exceeds 50 packages the summary counts the visible page, which is acceptable for this pass — do not silently imply it covers all packages (the summary label says "packages", tied to visible rows).

- [ ] **Step 5: Wire Select all / Clear all / Download buttons**

```javascript
function postSelectAll(taskId, selected) {
  $.ajax({
    url: 'api/prescans/' + encodeURIComponent(taskId) + '/packages/select-all',
    type: 'post', data: JSON.stringify({ selected: selected }),
    contentType: 'application/json', dataType: 'json',
    success: function (response) {
      $('#task_submit_status').text('Selected packages: ' + response.selected_count);
      detailColsType = null; detailSignature = '';
      loadTaskDetail(taskId, 'prescan');
      updateTaskDashboard();
    },
    error: function (xhr) {
      $('#task_submit_status').text((xhr.responseJSON || {}).error || 'Selection failed.');
    }
  });
}

$('#prescan_select_all').on('click', function () {
  if (selectedTaskId) { postSelectAll(selectedTaskId, true); }
});
$('#prescan_clear_all').on('click', function () {
  if (selectedTaskId) { postSelectAll(selectedTaskId, false); }
});
$('#prescan_download').on('click', function () {
  if (selectedTaskId) { postTaskAction(selectedTaskId, 'confirm'); }
});
```

- [ ] **Step 6: Verify no backend regression**

Run: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`
Expected: all pass (this task changes no Python).

- [ ] **Step 7: Visual smoke check with the scratchpad harness**

Extend `<scratchpad>/taskui_harness.html` (or a second harness) with the prescan submit row and controls bar. Mock the mode toggle (count input shows only in prescan), mock a prescan detail with three packages having `known_total_size_bytes` and `media_count`, and confirm: the count input toggles with the mode, the summary shows `N packages · M media · X MB`, and Select all / Clear all update the summary. Stub the two `$.ajax` calls to return canned JSON so no server is needed. Capture one screenshot.
Expected: toggle, summary math, and select-all/clear-all update correctly; no console errors.

- [ ] **Step 8: Commit**

```bash
git add module/templates/index.html module/static/css/index.css
git commit -m "feat: add web ranged prescan count and batch selection controls"
```

---

## Self-Review

- Spec coverage: status badges (T1 S2–3), error visibility (T1 S2/S4/S6), progress bars (T1 S2–3, S6), counts (T1 S2–3), empty states + stability (T1 S5–7); Feature B message count (T3 S1/S3), raised limits (T2 S3), select-all endpoint (T2 S4) and UX (T3 S1/S4/S5). All spec sections map to tasks.
- Placeholder scan: no TBD/TODO; all code blocks are concrete.
- Type consistency: `statusBadge/fileStatusBadge/taskProgressCell/countCell/fileProgressCell/fileErrorCell`, `FILE_DETAIL_COLS`, `detailColsType/detailSignature/lastTasksById/prescanRows`, and endpoint field names (`selected`, `selected_count`, `total`) are used identically across tasks. `countCell` replaces `countText`; `loadTaskDetail` signature `(taskId, taskType)` preserved.

## Notes for the executor

- Do not push or deploy; the parent session handles RackNerd deployment after both features are committed and verified.
- If a layui detail (e.g. `done`-callback row selector, `form.on('select()')`) behaves differently than written, adjust minimally and confirm via the browser harness; keep the observable behavior in the step.
