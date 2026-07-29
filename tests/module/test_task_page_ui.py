"""Static DOM and style contracts for the Web task panels."""

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_TEMPLATE = PROJECT_ROOT / "module/templates/index.html"
INDEX_CSS = PROJECT_ROOT / "module/static/css/index.css"


def test_task_table_uses_five_column_information_hierarchy():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    table = html.split('class="table task-table"', 1)[1].split("</table>", 1)[0]
    headers = re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", table, re.S)

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
    assert (
        "btn.setAttribute('aria-pressed', String(btn.dataset.filter === taskFilter))"
        in html
    )
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
