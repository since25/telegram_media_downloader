# Task Panels Density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eight-column task table and crowded detail heading with a five-column, keyboard-accessible task list and one consistent task-detail hierarchy.

**Architecture:** Keep the existing Flask/Jinja single-file task renderer and APIs. Add task-page-specific semantic classes in the template and stylesheet, then reorganize existing fields in JavaScript without changing task state, commands, polling frequency, or backend payloads.

**Tech Stack:** Flask/Jinja HTML, plain JavaScript, plain CSS, pytest static DOM contracts, Node.js syntax checking.

## Global Constraints

- Do not change Flask APIs, task state, download/upload behavior, database schema, configuration, or polling frequency.
- Keep the existing Industry tokens, square geometry, muted blue palette, and table-based desktop layout.
- Do not add dependencies, gradients, shadows, floating panels, decorative copy, or mobile card rendering.
- Preserve HTML escaping for every task-, Telegram-, and filename-sourced value.
- Append implementation and fresh verification evidence to `progress.md`.

---

### Task 1: Lock the compact task-panel contract

**Files:**
- Create: `tests/module/test_task_page_ui.py`
- Read: `module/templates/index.html`
- Read: `module/static/css/index.css`

**Interfaces:**
- Consumes: the existing `task_rows`, `task_detail`, `detail_title`, `detail_meta`, `detail_current_file`, `prescan_controls`, and `detail_body` element IDs.
- Produces: static contracts for five task columns, accessible filters and rows, a unified detail header, stale-request guards, and task-specific CSS.

- [ ] **Step 1: Write failing DOM and CSS contract tests**

```python
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_TEMPLATE = PROJECT_ROOT / "module/templates/index.html"
INDEX_CSS = PROJECT_ROOT / "module/static/css/index.css"


def test_task_table_uses_five_column_information_hierarchy():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    table = html.split('class="table task-table"', 1)[1].split("</table>", 1)[0]
    headers = re.findall(r"<th(?:\\s[^>]*)?>(.*?)</th>", table, re.S)
    assert [re.sub(r"<[^>]+>", "", item).strip() for item in headers] == [
        "任务",
        "状态",
        "进度",
        "结果",
        "操作",
    ]
    assert "task-primary" in html
    assert "task-secondary" in html
    assert "task-result-grid" in html


def test_task_panel_exposes_filter_selection_and_keyboard_row_selection():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    assert 'class="task-filter-group"' in html
    assert 'aria-pressed="true"' in html
    assert "btn.setAttribute('aria-pressed', String(btn.dataset.filter === taskFilter))" in html
    assert 'aria-selected="${selected}"' in html
    assert 'tabindex="0"' in html
    assert "['Enter',' '].includes(e.key)" in html


def test_task_detail_has_unified_header_and_guards_async_identity():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    for element_id in ("detail_status", "detail_actions", "detail_title", "detail_meta"):
        assert len(re.findall(rf'id="{element_id}"', html)) == 1
    assert "detailGeneration:0" in html
    assert "generation !== state.detailGeneration" in html
    assert "state.selectedTaskId !== task.task_id" in html
    assert "无法加载任务明细" in html


def test_task_panel_styles_are_scoped_and_responsive():
    css = INDEX_CSS.read_text(encoding="utf-8")
    for selector in (
        ".task-panel-header",
        ".task-table",
        ".task-primary",
        ".task-secondary",
        ".task-result-grid",
        ".task-detail-header",
        ".task-detail-meta",
        ".task-current-file",
    ):
        assert selector in css
    assert '.task-table tbody tr[aria-selected="true"]' in css
    assert "min-width: 820px" in css
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m pytest tests/module/test_task_page_ui.py -q`

Expected: four failures because the five-column markup, accessibility attributes, detail guards, and scoped styles do not exist yet.

- [ ] **Step 3: Commit only after Task 2 is green**

The test file remains uncommitted until the implementation in Task 2 satisfies it.

### Task 2: Implement the task table and unified detail panel

**Files:**
- Modify: `module/templates/index.html`
- Modify: `module/static/css/index.css`
- Test: `tests/module/test_task_page_ui.py`

**Interfaces:**
- Consumes: `/api/task-dashboard`, `/api/tasks/<task_id>`, `/api/prescans/<task_id>/packages`, `taskActions(task)`, `statusTag(status)`, and `escapeHtml(value)`.
- Produces: `renderTaskTable(tasks)`, `renderDetail(task)`, `renderFileTable(task, files)`, `renderPrescanPackages(task, generation)`, and `renderPrescanDownloading(task, generation)` with unchanged API effects.

- [ ] **Step 1: Replace the panel markup**

Use one `task-panel-header`, one `task-filter-group` with `aria-pressed`, a `table task-table` with the exact five headers from Task 1, and a detail header containing `detail_title`, `detail_status`, `detail_meta`, and `detail_actions`. Preserve every existing ID consumed elsewhere.

- [ ] **Step 2: Reorganize each task row**

Render:

```javascript
const selected = t.task_id === state.selectedTaskId;
return `<tr data-id="${escapeHtml(t.task_id)}" data-type="${escapeHtml(t.task_type||'')}"
  aria-selected="${selected}" tabindex="0">
  <td><div class="task-primary" title="${escapeHtml(t.title||'任务')}">${escapeHtml(t.title||'任务')}</div>
    <div class="task-secondary"><span>${escapeHtml(t.source||'—')}</span><span>${escapeHtml(t.task_type||'—')}</span>
    <span class="nums" title="${escapeHtml(t.task_id)}">${escapeHtml(shortId(t.task_id))}</span></div></td>
  <td>${statusTag(t.status)}</td>
  <td><div class="task-progress">${progressCell(t)}</div></td>
  <td><div class="task-result-grid">…</div></td>
  <td class="task-actions"><div>${taskActions(t)}</div></td>
</tr>`;
```

When the filtered list is empty, render one `task-empty-row` whose text distinguishes all, active, and completed filters.

- [ ] **Step 3: Add selection and filter accessibility**

After a filter click, set `aria-pressed` on all filter buttons. Add delegated `keydown` handling on `task_rows`; Enter and Space select the focused task row unless the event originated from a button.

- [ ] **Step 4: Standardize detail metadata and current-file rendering**

Set the title text and status in separate elements. Populate metadata with escaped source, task type, full task ID, and the file/package count. Render current filename as the main line and progress/speed as metadata. Populate `detail_actions` with the existing status-appropriate buttons.

- [ ] **Step 5: Guard every asynchronous detail renderer**

Increment `state.detailGeneration` in `renderDetail`. Pass the captured generation into ordinary and prescan renderers. After each awaited request, return unless both the generation and selected task ID still match. On fetch failure, render “无法加载任务明细” only if the same guard still passes.

- [ ] **Step 6: Add scoped styles**

Add only `.task-*` and `.task-detail-*` rules. Keep the table at `min-width: 820px`, use a stable 3px inset selected marker, constrain long titles with ellipsis, use tabular result numbers, and allow only the task table/detail tables—not the whole page—to scroll horizontally.

- [ ] **Step 7: Run focused verification and verify GREEN**

Run: `.venv/bin/python -m pytest tests/module/test_task_page_ui.py -q`

Expected: `4 passed`.

Run: extract the inline script from `module/templates/index.html` into a temporary `.js` file and run `node --check` on it.

Expected: exit code 0 with no syntax errors.

- [ ] **Step 8: Commit the implementation**

```bash
git add tests/module/test_task_page_ui.py module/templates/index.html module/static/css/index.css
git commit -m "feat(web): refine task panels"
```

### Task 3: Document and verify the complete change

**Files:**
- Modify: `docs/web-control-console.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: the completed task panel implementation and fresh command output.
- Produces: operator-facing behavior notes and the required append-only implementation record.

- [ ] **Step 1: Update operator documentation**

Add a short Tasks UI paragraph stating that task rows consolidate identity metadata, selecting a row opens the detail panel, and ordinary/prescan details share one header while retaining their existing APIs and actions.

- [ ] **Step 2: Run targeted regressions**

Run: `.venv/bin/python -m pytest tests/module/test_task_page_ui.py tests/module/test_web.py tests/module/test_channel_library_web.py -q`

Expected: all selected tests pass.

- [ ] **Step 3: Run the full verification suite**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass with the repository's existing single skip.

Run: `.venv/bin/python check_imports.py`

Expected: compatibility imports pass.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Append `progress.md`**

Record the five-column task hierarchy, unified detail header, accessibility and stale-response guard work, exact test counts, JavaScript syntax result, browser verification status, changed files, and a revert-based rollback.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/web-control-console.md progress.md docs/superpowers/plans/2026-07-29-task-panels-density.md
git commit -m "docs: record task panel refinement"
```
