# Web 控制台 Industry 蓝图风格重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 layui + jQuery 的 Web 控制台重构为统一的 Industry 蓝图风格(钢蓝/方角/十字角标/Barlow),覆盖任务·文件·高级配置·登录四屏,并新增上传进度与系统资源监控。

**Architecture:** 路线 A —— 保留 Flask + Jinja2 + 现有轮询接口,手写 Industry CSS 替换 layui,原生 `<table>` 渲染;新增三项后端能力(`GET /api/system`、上传进度接入、预扫描确认后保留包状态)。渲染 JS 沿用现有「内联在 `index.html`」的模式。

**Tech Stack:** Flask / Jinja2 / 原生 JS(无框架、无构建)/ 手写 CSS / Lucide 内联 SVG / psutil / pytest(后端)/ 静态浏览器 harness(前端保真)。

**设计源(唯一权威,逐字 markup/CSS 取自此处):**
- `docs/design/frontend-redesign/styles.css` —— DS token + 组件类(唯一样式源)。
- `docs/design/frontend-redesign/prototype.html` —— 四屏高保真原型。关键行区:任务屏 67–341、预扫描「下载中」详情 343–397、文件屏 399–462、配置屏 464–565、登录屏 567–585。**`1b 流水线`(587–745)为早期备选,忽略。**
- `docs/design/frontend-redesign/README.md` —— 交接说明。
(这三个文件由 Task 1 Step 1 从 `/Users/wangyichuan/Downloads/前端重构与设计规划.zip` 解出并入库。)

**配套 spec:** `docs/superpowers/specs/2026-07-14-web-industry-redesign-design.md`(数据形状、屏幕规格、状态映射的完整依据)。

## Global Constraints

- 部署机 **1 vCPU / 1 GiB**,Flask web 与下载器(Pyrogram + 下载循环 + rclone)**同进程**。前端保持纯静态、去 layui;`psutil.cpu_percent(interval=None)` 非阻塞。
- **唯一样式源** `styles.css`:所有颜色/间距/圆角/字体直接引用其 CSS 变量,**不另造数值或颜色**。
- **单色方案,错误/告警不用红色** —— 用 `.tag-outline`(描边)+ 三角感叹号(Lucide `alert-triangle`)。
- **一律方角**;卡片/图形透明线框(1px `--color-divider`);唯一实底是 primary 按钮。
- **蓝图角标**:卡片/主按钮/对话框加 `.blueprint` + 四个 `<i class="corner tl|tr|bl|br"></i>`;父级勿 `overflow:hidden`。
- Lucide 图标:**stroke-width 1.5**,内联 SVG,`stroke="currentColor"`。
- 字体:标题 `Barlow Condensed` 600,正文 `Barlow` 400/500/700。
- 全中文文案;数字/ID/大小/速度加 `.nums`(tabular-nums)。
- **登录 AES 加密逻辑不改**:key `1234123412ABCDEF`、iv `ABCDEF1234123412`,CBC/Pkcs7,POST `login`,`code==='1'` 跳首页。
- **hide_file_name 脱敏由后端负责**,前端直接展示后端返回的 `filename`/`save_path`,不自行还原。
- **验证约束**:严禁本地启动下载服务(需真 Telegram 客户端)。后端 = pytest;前端 = scratchpad 静态 harness + mock JSON,浏览器核对像素保真。
- 每个任务结束提交一次;分支 `feature/web-industry-redesign`;**不 push、不部署**(由 Task 10 统一处理)。

## File Structure

| 文件 | 责任 | 任务 |
|---|---|---|
| `docs/design/frontend-redesign/*` | 设计源入库(styles.css / prototype.html / README) | T1 |
| `module/static/css/index.css` | 重写为单一手写 Industry 样式表(DS 变量+组件类+shell 自定义类) | T1 |
| `module/templates/index.html` | 三屏外壳(nav/body/foot)+ 各屏 markup + 内联渲染 JS | T1,T5–T8 |
| `module/templates/login.html` | 分栏登录页(沿用 AES) | T9 |
| `module/web.py` | `GET /api/system`、`GET /get_upload_list`、dashboard 上传字段、预扫描保留 | T2–T4 |
| `module/task_state.py` | FileSnapshot/TaskSnapshot 上传字段与 dashboard 输出 | T3 |
| `requirements.txt` | 加入 `psutil` | T2 |
| `tests/test_web_system_api.py` | `/api/system` 测试 | T2 |
| `tests/test_web_upload_progress.py` | 上传进度 payload 测试 | T3 |
| `tests/test_web_prescan_retention.py` | 预扫描保留测试 | T4 |
| `docs/web-control-console.md` | 补充新接口 | T2–T4 |
| `progress.md` | 交付记录 | T10 |

> **渲染 JS 归属**:沿用现有「内联 `<script>` 在 `index.html`」模式(现状即如此,`module/static/request/index.js` 仅 20 行 layui 引导)。本次重构后 `index.js` 的 layui 依赖失效——T1 将其内容替换为空引导或删除引用,渲染逻辑集中在 `index.html` 内联脚本,按屏拆分为独立函数。

---

### Task 1: 设计系统 CSS + 应用外壳(nav / body / foot)

**Files:**
- Create: `docs/design/frontend-redesign/styles.css`, `docs/design/frontend-redesign/prototype.html`, `docs/design/frontend-redesign/README.md`
- Rewrite: `module/static/css/index.css`
- Modify: `module/templates/index.html`(替换 `<head>` 引用 + nav/foot 外壳;正文各屏留空容器,后续任务填充)
- Modify: `module/static/request/index.js`(移除 layui 引导,置为空或最小)
- Verify: `scratchpad/harness/shell.html`(静态外壳预览)

**Interfaces:**
- Produces(供 T5–T9):外壳 DOM 结构与 class —— `.app > .app-nav(.brand + nav a[data-tab] + .state-chip#download_state + 退出 btn) + .app-body(#tab_tasks / #tab_files / #tab_config 三容器) + .app-foot(#app_version + #foot_speed)`;全部 DS 组件类(`.card .blueprint .corner .btn .tag .field .input .seg .sw .table .track .nums .live-dot .state-chip`)。
- Produces:CSS 变量与组件类在 `index.css` 内全部可用。

- [ ] **Step 1: 从交接 zip 解出设计源入库**

```bash
mkdir -p docs/design/frontend-redesign scratchpad/harness
TMP=$(mktemp -d)
unzip -o "/Users/wangyichuan/Downloads/前端重构与设计规划.zip" -d "$TMP"
cp "$TMP/design_handoff_frontend_redesign/design/ds/styles.css" docs/design/frontend-redesign/styles.css
cp "$TMP/design_handoff_frontend_redesign/design/TG Downloader Redesign.dc.html" docs/design/frontend-redesign/prototype.html
cp "$TMP/design_handoff_frontend_redesign/README.md" docs/design/frontend-redesign/README.md
rm -rf "$TMP"
ls -la docs/design/frontend-redesign/
```

Expected: 三个文件就位。

- [ ] **Step 2: 重写 `module/static/css/index.css` 为单一 Industry 样式表**

把 `docs/design/frontend-redesign/styles.css` 的**全部内容**(`:root` 变量 + 全部组件类 + 末尾方角覆盖)复制为 `index.css` 的开头。**注意**:`styles.css` 顶部有 `@import url('https://fonts.googleapis.com/...Barlow...')` —— 保留(在线);离线自托管为后续可选项,本次不做。

然后在其后追加原型的 shell 自定义类(逐字取自 `prototype.html` 第 33–55 行,`.dv-*`/`.screen-cap` 是设计画布 chrome,**不要**复制):

```css
/* ── App shell (from prototype.html:33-55) ── */
.cfg-title { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.cfg-title span { font-family: var(--font-heading); font-weight: 600; font-size: 15.5px; }
.sw { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; }
.sw > i { width: 34px; height: 19px; position: relative; flex: none; background: var(--color-neutral-200); border: 1px solid var(--color-divider); }
.sw > i::after { content: ""; position: absolute; top: 1px; left: 1px; width: 15px; height: 15px; background: var(--color-bg); border: 1px solid var(--color-neutral-400); }
.sw.on > i { background: var(--color-accent); border-color: var(--color-accent); }
.sw.on > i::after { left: 16px; border: 0; }
.sw.off span { color: var(--color-neutral-600); }
.app { width: 1240px; max-width: 100%; margin: 0 auto; background: var(--color-bg); border: 1px solid var(--color-divider); box-shadow: var(--shadow-lg); overflow: hidden; }
.app-nav { display: flex; align-items: center; gap: 26px; padding: 15px 24px; border-bottom: 1px solid var(--color-divider); }
.app-nav .brand { display: flex; align-items: center; gap: 10px; font-family: var(--font-heading); font-weight: 600; font-size: 18px; letter-spacing: -0.01em; }
.app-nav a { color: inherit; text-decoration: none; font-size: 14px; padding-bottom: 2px; cursor: pointer; }
.app-nav a:hover { color: var(--color-accent); }
.app-nav a[aria-current="page"] { color: var(--color-accent); border-bottom: 2px solid var(--color-accent); }
.app-body { padding: 22px 24px 26px; display: flex; flex-direction: column; gap: 18px; }
.state-chip { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-family: var(--font-heading); font-weight: 600; font-size: 13px; padding: 6px 12px; border: 1px solid var(--color-divider); background: transparent; color: var(--color-text); }
.state-chip:hover { background: color-mix(in srgb, var(--color-text) 6%, transparent); }
.live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--color-accent); box-shadow: 0 0 0 3px var(--color-accent-100); }
.track { height: 6px; background: var(--color-neutral-200); position: relative; overflow: hidden; }
.track > i { position: absolute; top: 0; bottom: 0; left: 0; background: var(--color-accent); transition: width .3s; }
.nums { font-variant-numeric: tabular-nums; }
.app-foot { display: flex; align-items: center; justify-content: space-between; padding: 11px 24px; border-top: 1px solid var(--color-divider); font-size: 12px; color: var(--color-neutral-600); }
.app-foot b { color: var(--color-text); }
/* tab 容器:非当前屏隐藏 */
.tab-panel { display: none; flex-direction: column; gap: 18px; }
.tab-panel.active { display: flex; }
/* 响应式:窄屏表格横向滚动 */
.table-scroll { overflow-x: auto; }
@media (max-width: 760px) { .app { width: 100%; } }
```

- [ ] **Step 3: 重写 `index.html` 的 `<head>` 与外壳骨架**

移除 layui 的 CSS/JS 引用(`static/layui/css/layui.css`、`layui.js`),保留 `static/aes/...` (登录页用,index 不需要可不引)与 `static/request/index.js`。`<head>` 引 `static/css/index.css`。外壳(逐字结构参照 `prototype.html:73-87` 的 nav+body、`:336-341` 的 foot;图标用 Lucide download / log-out):

```html
<body>
<div class="app">
  <nav class="app-nav">
    <div class="brand">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
      TG 媒体下载器
    </div>
    <a data-tab="tasks" aria-current="page">任务</a>
    <a data-tab="files">文件</a>
    <a data-tab="config">高级配置</a>
    <span class="nums text-muted" id="nav_total_speed" style="margin-left:auto;font-size:13px;display:none"></span>
    <button type="button" class="state-chip" id="download_state" data-value="{{ download_state }}">
      <span class="live-dot"></span><span id="download_state_text">运行中</span>
    </button>
    <button type="button" class="btn btn-ghost" id="logout_btn" style="gap:6px">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></svg>退出
    </button>
  </nav>
  <div class="app-body">
    <div class="tab-panel active" id="tab_tasks"><!-- T5/T6 --></div>
    <div class="tab-panel" id="tab_files"><!-- T7 --></div>
    <div class="tab-panel" id="tab_config"><!-- T8 --></div>
  </div>
  <div class="app-foot">
    <span>Telegram Media Downloader v<span id="app_version">{{ version }}</span></span>
    <span class="nums" id="foot_speed">⬇ 0.00 B/s</span>
  </div>
</div>
<script src="static/request/index.js"></script>
<script>/* T5 起填充:tab 切换 + 轮询 + 渲染 */</script>
</body>
```

> `{{ version }}` 若模板未提供,用 JS 拉 `get_app_version` 填 `#app_version`(T5)。tab 切换、`#download_state` 点击、`#logout_btn` 行为在 T5 接线。

- [ ] **Step 4: 清空 `index.js` 的 layui 引导**

`module/static/request/index.js` 现为 `const $ = layui.$` 等 layui 依赖(20 行)。整屏渲染改内联脚本,此文件 layui 依赖已失效。将其替换为:

```javascript
// Industry web console — rendering logic lives inline in index.html.
// This file intentionally left as a no-op after the layui removal.
```

- [ ] **Step 5: 静态外壳 harness 验证**

新建 `scratchpad/harness/shell.html`:引用 `../../module/static/css/index.css`(相对路径按实际调整),粘贴 Step 3 的 `.app` 外壳(把 `{{ version }}` 写死 `2.2.0`)。在浏览器打开核对:

- [ ] 外壳宽 1240、浅灰底、四角**无**角标(shell 本身不加 `.blueprint`),`--shadow-lg` 投影;
- [ ] 顶栏品牌 18px 标题字 + download 图标;三 Tab,当前项 accent + 2px 下边框;
- [ ] `.state-chip` 描边方角 + live-dot(accent 圆点 + accent-100 光环);
- [ ] 底栏 12px neutral-600,左版本右速度;
- [ ] 字体确为 Barlow(标题 Condensed)。

用浏览器工具打开 harness(见 spec §9),逐条比对 `prototype.html` 任务屏顶部/底部。

- [ ] **Step 6: Commit**

```bash
git add docs/design/frontend-redesign module/static/css/index.css module/templates/index.html module/static/request/index.js
git commit -m "feat(web): Industry design system CSS + app shell, drop layui"
```

---

### Task 2: `GET /api/system` 系统监控接口

**Files:**
- Modify: `requirements.txt`(加 `psutil`)
- Modify: `module/web.py`(新增路由 `system_metrics`,靠近 `get_download_speed`)
- Create: `tests/test_web_system_api.py`
- Modify: `docs/web-control-console.md`

**Interfaces:**
- Produces(供 T5 系统监控卡):`GET /api/system` → JSON `{cpu_percent:float, mem_used:int(bytes), mem_total:int, disk_used:int, disk_total:int, disk_free:int, download_speed:str, upload_speed:str}`。`download_speed`/`upload_speed` 为已格式化字符串(如 `"6.88 MB/s"`),数值型字段为字节整数。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_web_system_api.py
"""Tests for GET /api/system metrics endpoint."""
import json
from unittest import mock

import module.web as web


def _client():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_system_metrics_shape(monkeypatch):
    # bypass login
    monkeypatch.setattr(web, "login_required", lambda f: f, raising=False)
    fake_app = mock.Mock(save_path="/tmp")
    monkeypatch.setattr(web, "_active_app", lambda: fake_app)
    monkeypatch.setattr(web, "get_total_download_speed", lambda: 7215000)
    with _client() as client:
        with client.session_transaction() as sess:
            sess["login"] = True  # match existing login gate
        resp = client.get("/api/system")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    for key in ("cpu_percent", "mem_used", "mem_total",
                "disk_used", "disk_total", "disk_free",
                "download_speed", "upload_speed"):
        assert key in body, f"missing {key}"
    assert isinstance(body["disk_total"], int) and body["disk_total"] > 0
    assert body["download_speed"].endswith("/s")
```

> 执行前先确认现有登录 gate 的 session 键名:`grep -n "session\[" module/web.py`。若不是 `login`,把上面的 `sess["login"]=True` 换成实际键;若 `login_required` 无法用 monkeypatch 绕过,改用现有测试套件里既有的登录夹具(`grep -rn "test_client\|login_required" tests/`)。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_web_system_api.py -v`
Expected: FAIL(路由不存在 → 404)。

- [ ] **Step 3: 加 psutil 依赖**

在 `requirements.txt` 末尾加一行 `psutil`(不钉版本,跟随现有风格;若现有依赖都钉版本,用 `psutil==5.9.8`)。本地安装:`pip install psutil`。

- [ ] **Step 4: 实现路由**

在 `module/web.py`(`get_download_speed` 附近)加:

```python
@_flask_app.route("/api/system")
@login_required
def system_metrics():
    """Return CPU / memory / disk / throughput for the monitor card."""
    import shutil
    import psutil

    app = _active_app()
    save_path = getattr(app, "save_path", None) or "/"
    try:
        usage = shutil.disk_usage(save_path)
    except OSError:
        usage = shutil.disk_usage("/")
    vmem = psutil.virtual_memory()
    return jsonify(
        {
            "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            "mem_used": int(vmem.total - vmem.available),
            "mem_total": int(vmem.total),
            "disk_used": int(usage.used),
            "disk_total": int(usage.total),
            "disk_free": int(usage.free),
            "download_speed": format_byte(get_total_download_speed()) + "/s",
            "upload_speed": format_byte(get_total_upload_speed()) + "/s",
        }
    )
```

> **执行顺序**:T3 已先于本任务完成,`get_total_upload_speed()` 已在 `module/download_stat.py` 中定义并可用——**直接调用,无占位、无 TODO**。确保 `module/web.py` 顶部从 `module.download_stat` import 了 `get_total_upload_speed`(若缺则加入现有 import 行)。

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_web_system_api.py -v`
Expected: PASS。

- [ ] **Step 6: 补文档 + Commit**

在 `docs/web-control-console.md` 的 APIs 段加一行:`- GET /api/system: CPU / memory / disk(save_path 卷)/ throughput 快照。`

```bash
git add requirements.txt module/web.py tests/test_web_system_api.py docs/web-control-console.md
git commit -m "feat(web): add GET /api/system metrics endpoint"
```

---

### Task 3: 上传进度接入(dashboard 字段 + `GET /get_upload_list`)

**Files:**
- Modify: `module/task_state.py`(FileSnapshot 上传字段;TaskSnapshot 任务级上传聚合;**`snapshot_node` 补写上传态**)
- Modify: `module/download_stat.py`(`get_total_upload_speed`)
- Modify: `module/web.py`(`GET /get_upload_list`)
- Create: `tests/test_web_upload_progress.py`
- Modify: `docs/web-control-console.md`

**Interfaces:**
- Consumes:活跃节点上传态 —— `get_active_task_nodes()`、`TaskNode.upload_status`/`upload_stat_dict`、`module.app.UploadStatus`/`UploadProgressStat`(真实模型,见 Step 5.5 说明块)。
- Produces(供 T2/T5/T6/T7):
  - `FileSnapshot.to_dict` 新增 `uploaded_size_bytes`、`upload_progress:float(0–100)`、`upload_speed:str`、`upload_speed_bytes:int`。
  - **`snapshot_node` 现在也把 `node.upload_status`/`upload_stat_dict` 写入 FileSnapshot**(否则 dashboard/文件列表永远显示不出上传进度)。
  - task-dashboard 每个任务新增 `upload_progress:float`、`upload_speed:str`(`upload_success_count` 已存在)。
  - `GET /get_upload_list` → `[{chat, id, filename, total_size, upload_progress, upload_speed}]`(uploading 状态文件)。
  - `get_total_upload_speed() -> int`(字节/秒,供 T2 `/api/system` 直接调用)。

- [ ] **Step 1: 写失败测试(FileSnapshot 上传字段)**

```python
# tests/test_web_upload_progress.py
"""Tests for upload progress in Web task/file payloads."""
from module.task_state import FileSnapshot, FileStatus, TaskSnapshot, TaskStatus


def test_file_snapshot_exposes_upload_fields():
    f = FileSnapshot(message_id="1", status=FileStatus.UPLOADING,
                     total_size=1000, uploaded_size=740, upload_speed=200)
    d = f.to_dict()
    assert d["upload_progress"] == 74.0
    assert d["upload_speed"].endswith("/s")
    assert d["upload_speed_bytes"] == 200


def test_task_dashboard_row_has_upload_progress():
    t = TaskSnapshot(task_id="t1", status=TaskStatus.UPLOADING)
    t.files["1"] = FileSnapshot(message_id="1", status=FileStatus.UPLOADING,
                                total_size=1000, uploaded_size=500)
    d = t.to_dict()
    assert "upload_progress" in d
    assert d["upload_progress"] == 50.0
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_web_upload_progress.py -v`
Expected: FAIL(`FileSnapshot` 无 `uploaded_size`/`upload_speed` 字段 → TypeError；无 `upload_progress`)。

- [ ] **Step 3: 给 FileSnapshot 加上传字段**

`module/task_state.py` 的 `FileSnapshot` dataclass 增字段 + 属性 + to_dict 输出:

```python
    # 追加到现有字段后
    uploaded_size: int = 0
    upload_speed: int = 0

    @property
    def upload_progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return round(min(self.uploaded_size / self.total_size * 100, 100.0), 1)
```

在 `FileSnapshot.to_dict` 的返回字典里追加:

```python
            "uploaded_size_bytes": self.uploaded_size,
            "upload_progress": self.upload_progress,
            "upload_speed": format_byte(int(self.upload_speed)) + "/s",
            "upload_speed_bytes": int(self.upload_speed),
```

- [ ] **Step 4: 任务级上传进度**

在 `TaskSnapshot.to_dict` 的 payload 里追加任务级聚合(基于 files):

```python
            "upload_progress": self._upload_progress(),
            "upload_speed": format_byte(self._upload_speed_bytes()) + "/s",
```

并加两个私有方法:

```python
    def _upload_progress(self) -> float:
        uploading = [f for f in self.files.values()
                     if f.status in (FileStatus.UPLOADING, FileStatus.UPLOADED)]
        if not uploading:
            return 0.0
        done = sum(1 for f in uploading if f.status == FileStatus.UPLOADED)
        active = [f.upload_progress for f in uploading if f.status == FileStatus.UPLOADING]
        partial = sum(active) / 100.0
        return round((done + partial) / len(uploading) * 100, 1)

    def _upload_speed_bytes(self) -> int:
        return int(sum(f.upload_speed for f in self.files.values()
                       if f.status == FileStatus.UPLOADING))
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_web_upload_progress.py -v`
Expected: PASS。

> **真实数据模型(执行前已由控制器核实,取代原「get_upload_result」假设)**:仓库**没有** `get_upload_result()`。上传进度挂在活跃 `TaskNode` 上:
> - `module.download_stat.get_active_task_nodes() -> {task_id: TaskNode}`(活跃节点表)。
> - `TaskNode.upload_status: {message_id: UploadStatus}`;`TaskNode.upload_stat_dict: {message_id: UploadProgressStat}`;`TaskNode.upload_success_count: int`。
> - `module.app.UploadStatus`:`Uploading / SuccessUpload / FailedUpload / SkipUpload`。
> - `module.app.UploadProgressStat`:`file_name, total_size, upload_size, start_time, last_stat_time, upload_speed`(逐文件字节进度**存在**,可做全保真)。
> - 关键:`module/task_state.py` 的 `snapshot_node()`(节点→Web 快照的唯一桥)**当前只映射 `download_status`,完全忽略上传**。所以只加 FileSnapshot 字段还不够——必须在 `snapshot_node` 里补写上传状态,dashboard/文件列表才会真正显示上传进度。

- [ ] **Step 6: 关键接线 —— `snapshot_node` 写入上传状态(TDD)**

先在 `tests/test_web_upload_progress.py` 追加失败测试(用最小 fake node,真实模型):

```python
def test_snapshot_node_maps_upload_state():
    from module.task_state import snapshot_node, get_task_store, FileStatus
    from module.app import UploadStatus, UploadProgressStat

    class _Node:
        pass
    node = _Node()
    node.task_id = "up-1"; node.chat_id = -100
    node.download_status = {}
    node.upload_status = {7: UploadStatus.Uploading}
    node.upload_stat_dict = {7: UploadProgressStat(
        file_name="wall_31.jpg", total_size=1000, upload_size=600,
        start_time=0.0, last_stat_time=0.0, upload_speed=150)}
    node.upload_success_count = 0
    snapshot_node(node)
    f = get_task_store().get_task("up-1").files["7"]
    assert f.status == FileStatus.UPLOADING
    assert f.uploaded_size == 600 and f.upload_speed == 150
```

> `snapshot_node` 对 node 大量用 `getattr(..., 默认值)`,最小 fake node 可用;若 `_status_from_node(node)` 需要额外属性,给 fake node 补最小属性(执行时按报错补,勿改 `_status_from_node` 逻辑)。

实现:`module/task_state.py` 顶部 `from module.app import DownloadStatus` 改为 `from module.app import DownloadStatus, UploadStatus`。加映射辅助:

```python
def _file_status_from_upload_status(status) -> str:
    if status is UploadStatus.SuccessUpload:
        return FileStatus.UPLOADED
    if status is UploadStatus.FailedUpload:
        return FileStatus.UPLOAD_FAILED
    if status is UploadStatus.Uploading:
        return FileStatus.UPLOADING
    return FileStatus.SKIPPED
```

在 `snapshot_node` 的 `download_status` 循环**之后**追加上传循环(上传是后续阶段,须覆盖同一文件的下载态):

```python
    for message_id, up_status in (getattr(node, "upload_status", {}) or {}).items():
        if up_status is None:
            continue
        updates = {"status": _file_status_from_upload_status(up_status)}
        stat = (getattr(node, "upload_stat_dict", {}) or {}).get(message_id)
        if stat is not None:
            updates["uploaded_size"] = int(getattr(stat, "upload_size", 0) or 0)
            updates["upload_speed"] = int(getattr(stat, "upload_speed", 0) or 0)
            if getattr(stat, "total_size", 0):
                updates["total_size"] = int(stat.total_size)
            if getattr(stat, "file_name", ""):
                updates["filename"] = stat.file_name
        get_task_store().upsert_file(task.task_id, message_id, **updates)
```

Run: `pytest tests/test_web_upload_progress.py -v` → PASS。

- [ ] **Step 7: `get_total_upload_speed` + `/get_upload_list`(基于活跃节点,TDD)**

失败测试(追加,monkeypatch 活跃节点表):

```python
def test_get_upload_list_returns_uploading_files(monkeypatch):
    import json
    import module.web as web
    from module.app import UploadStatus, UploadProgressStat

    class _Node:
        pass
    node = _Node()
    node.chat_id = -100
    node.upload_status = {5: UploadStatus.Uploading}
    node.upload_stat_dict = {5: UploadProgressStat(
        file_name="/d/wall_31.jpg", total_size=1000, upload_size=740,
        start_time=0.0, last_stat_time=0.0, upload_speed=200)}
    monkeypatch.setattr(web, "get_active_task_nodes", lambda: {"up-1": node}, raising=False)

    app = web.get_flask_app(); app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["login"] = True
        resp = client.get("/get_upload_list")
    assert resp.status_code == 200
    rows = json.loads(resp.data)
    assert rows and rows[0]["filename"] == "wall_31.jpg"
    assert rows[0]["upload_progress"] == 74.0
```

> 先核对登录 session 键(`grep -n "session\[" module/web.py`)与 `web.get_active_task_nodes` 是否已 import(web.py 顶部若无则 `from module.download_stat import ... get_active_task_nodes`)。

实现 —— `module/download_stat.py`(`get_total_download_speed` 附近):

```python
def get_total_upload_speed() -> int:
    """sum live per-file upload speed across active task nodes"""
    from module.app import UploadStatus
    total = 0
    for node in get_active_task_nodes().values():
        for message_id, stat in (getattr(node, "upload_stat_dict", {}) or {}).items():
            if node.upload_status.get(message_id) is UploadStatus.Uploading:
                total += int(getattr(stat, "upload_speed", 0) or 0)
    return total
```

`module/web.py` 新路由(确保 `get_active_task_nodes`、`get_total_upload_speed` 已从 `module.download_stat` import):

```python
@_flask_app.route("/get_upload_list")
@login_required
def get_upload_list():
    from module.app import UploadStatus
    result = []
    for node in get_active_task_nodes().values():
        for message_id, stat in (getattr(node, "upload_stat_dict", {}) or {}).items():
            if node.upload_status.get(message_id) is not UploadStatus.Uploading:
                continue
            total = getattr(stat, "total_size", 0) or 1
            result.append({
                "chat": f"{getattr(node, 'chat_id', '')}",
                "id": f"{message_id}",
                "filename": os.path.basename(stat.file_name),
                "total_size": format_byte(getattr(stat, "total_size", 0)),
                "upload_progress": round(getattr(stat, "upload_size", 0) / total * 100, 1),
                "upload_speed": format_byte(int(getattr(stat, "upload_speed", 0))) + "/s",
            })
    return jsonify(result)
```

> **执行顺序说明**:本任务(T3)在 T2 之前执行。T2 的 `/api/system` 会直接调用 `get_total_upload_speed()`,**无占位**。本任务无需回填 T2。

- [ ] **Step 8: 运行全部 + Commit**

Run: `pytest tests/test_web_upload_progress.py tests/test_web_system_api.py -v`
Expected: PASS。

在 `docs/web-control-console.md` 加:`- GET /get_upload_list: 正在上传的文件行(会话/ID/文件名/大小/上传进度/上传速度)。` 并注明 dashboard 任务新增 `upload_progress`/`upload_speed`。

```bash
git add module/task_state.py module/web.py tests/test_web_upload_progress.py docs/web-control-console.md
git commit -m "feat(web): expose upload progress in task payloads and /get_upload_list"
```

---

### Task 4: 预扫描确认后保留包状态(修复 packages 404)

**Files:**
- Modify: `module/web.py`(`confirm_task` 不再 pop prescan;`prescan_packages`/`select*` 生命周期;下载中写入每包/每文件进度;`clear`/`cancel`/terminal 时清理)
- Create: `tests/test_web_prescan_retention.py`
- Modify: `docs/web-control-console.md`

**Interfaces:**
- Consumes:现有 `_pending_web_prescans[task_id]`(dict:`packages`, `selected_package_ids:set`, `node`, `task_type`…)、`_run_confirmed_prescan_download`。
- Produces(供 T6 预扫描下载中详情):confirm 后 `GET /api/prescans/<id>/packages` 仍 200,`items[].selected` 反映确认时的选择;下载推进时包/文件进度可读。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_web_prescan_retention.py
"""Prescan package state must survive confirm so the download detail stays populated."""
import json
from unittest import mock
import module.web as web


def _client():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_packages_available_after_confirm(monkeypatch):
    task_id = "prescan-1"
    pkg = mock.Mock(package_id=1, title="pkg", start_message_id=1,
                    end_message_id=9, media_count=3)
    pkg.size_summary = mock.Mock(known_total_size=1000)
    web._pending_web_prescans[task_id] = {
        "packages": [pkg], "selected_package_ids": {1},
        "node": mock.Mock(), "task_type": "prescan",
    }
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))
    monkeypatch.setattr(web, "_schedule_web_coroutine", lambda app, coro: coro.close())
    monkeypatch.setattr(web, "_run_confirmed_prescan_download", lambda prescan: mock.Mock(close=lambda: None))
    with _client() as client:
        with client.session_transaction() as sess:
            sess["login"] = True
        confirm = client.post(f"/api/tasks/{task_id}/confirm")
        packages = client.get(f"/api/prescans/{task_id}/packages")
    assert confirm.status_code == 200
    assert packages.status_code == 200, "packages must remain after confirm"
    body = json.loads(packages.data)
    assert body["total"] == 1
    assert body["items"][0]["selected"] is True
    web._pending_web_prescans.pop(task_id, None)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_web_prescan_retention.py -v`
Expected: FAIL(confirm 后 packages 返回 404 —— 因 `confirm_task` 已 pop)。

- [ ] **Step 3: 改 `confirm_task` 保留 prescan**

`module/web.py` `confirm_task`(约 1038 行)把 `prescan = _pending_web_prescans.pop(task_id, None)` 改为 `get`,并在成功调度后**保留**条目(标记已确认,便于后续区分「待确认/下载中」):

```python
    preview = _pending_web_task_previews.pop(task_id, None)
    prescan = _pending_web_prescans.get(task_id)          # 不再 pop
    if not preview and not prescan:
        return jsonify({"ok": False, "error": "task is not waiting for confirmation"}), 404

    try:
        if prescan:
            selected_ids = set(prescan.get("selected_package_ids") or set())
            if not selected_ids:
                return jsonify({"ok": False, "error": "select at least one package"}), 400
            prescan["confirmed"] = True                    # 标记已确认
            coroutine = _run_confirmed_prescan_download(prescan)
        elif preview["task_type"] == "comment":
            ...
        else:
            ...
        _schedule_web_coroutine(app, coroutine)
    except RuntimeError as error:
        if prescan:
            prescan.pop("confirmed", None)                 # 回滚标记(条目本就保留)
        else:
            _pending_web_task_previews[task_id] = preview
        return jsonify({"ok": False, "error": str(error)}), 503
```

> 原「select at least one」分支里的 `_pending_web_prescans[task_id] = prescan` 回填可删(现在不再 pop,条目一直在)。核对该分支删除后逻辑仍正确。

- [ ] **Step 4: 确认清理路径仍生效**

`cancel_task`(约 1070 行)仍 `_pending_web_prescans.pop(task_id, None)` —— 保留(取消要清)。检查 `clear`(`/api/tasks/<id>/clear`)与任务进入 terminal 状态时是否清理 prescan 条目;若否,在 `clear` 路由里补 `_pending_web_prescans.pop(task_id, None)`,避免已清任务残留内存。用 `grep -n "_pending_web_prescans\|def clear_task\|clear-completed" module/web.py` 定位并核对。若 clear 已覆盖则不改。

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_web_prescan_retention.py -v`
Expected: PASS。

- [ ] **Step 6: 回归 + Commit**

Run: `pytest tests/ -k "prescan or web or upload or system" -v`
Expected: 全 PASS(确认未回归 cancel/select 行为)。

在 `docs/web-control-console.md` 注明:预扫描确认后包清单保留,`/api/prescans/<id>/packages` 在下载中仍可用;取消/清除时清理。

```bash
git add module/web.py tests/test_web_prescan_retention.py docs/web-control-console.md
git commit -m "fix(web): keep prescan packages after confirm so download detail stays populated"
```

---

### Task 5: 任务页 —— 状态/轮询骨架 + 命令栏 + 汇总卡 + 系统监控卡 + 任务表

**Files:**
- Modify: `module/templates/index.html`(填充 `#tab_tasks` markup + 内联脚本骨架)
- Verify: `scratchpad/harness/tasks.html` + `scratchpad/harness/mock.js`

**Interfaces:**
- Consumes:T1 外壳;T2 `/api/system`;T3 dashboard 上传字段。
- Produces(供 T6):
  - 全局 state:`state = {selectedTaskId, selectedTaskType, lastTasksById:{}, prescanRows:{}, prescanSelected:Set, sys:null, timers:{}}`。
  - `TASK_STATUS_TAG(status)` → `{cls, label, icon}`;`taskActions(task)` → 操作按钮 HTML;`icon(name)` → Lucide SVG 字符串;`renderTaskTable(tasks)`;`selectTask(id,type)`(T6 实现详情渲染,T5 留空钩子)。
  - `startPolling(tab)` / `stopPolling()`。

- [ ] **Step 1: 填充 `#tab_tasks` markup**

逐字结构参照 `prototype.html`:命令栏 89–111、汇总卡 113–135、系统监控卡 137–170、任务表卡 172–256。把静态示例值替换为带 id 的空容器。要点:
- 命令栏 `.card.blueprint`:`#web_task_link`(`.input.nums`)、`.seg` 两 `seg-opt`(radio name=`web_task_mode`,值 `preview`/`prescan`)、`#web_task_count`(`.input`,默认 2000,预扫描时显示)、`#submit_task_btn`(`.btn.btn-primary.blueprint` + plus 图标 + 四角标)、`#task_submit_status`。
- 汇总卡:4 个 `.card.blueprint`,数字 span id `#sum_active`/`#sum_completed`/`#sum_state`(含 `.live-dot`)/`#sum_speed`,数字用标题字 26px + `.nums`。
- 系统监控卡:`.card.blueprint`,头部「系统监控 · 每秒刷新」;一行 flex 分块(块间 `border-left:1px solid var(--color-divider)`):`#sys_dl`、`#sys_ul`(accent-700 高亮)、磁盘块(flex:1.9,内含 `#sys_disk_track` 8px track、`#sys_disk_warn` 描边告警标签默认 hidden、`#sys_disk_text`)、`#sys_cpu`+5px track、`#sys_mem`+5px track。
- 任务表 `.card.blueprint` 包 `.table-scroll > table.table`:头部「下载任务」+ `#task_count` tag + 过滤按钮(全部/进行中/已完成,`data-filter=all|active|done`);`<tbody id="task_rows">` 空。列头:任务 ID·来源·类型·状态·标题·进度·成/败/跳·当前文件·操作。

- [ ] **Step 2: 内联脚本 —— icon 库 + 状态映射 + 工具**

在 `index.html` 底部 `<script>` 写(**完整**,后续任务扩展同一脚本):

```javascript
const $ = (sel, root=document) => root.querySelector(sel);
const state = { selectedTaskId:null, selectedTaskType:null, lastTasksById:{},
  prescanRows:{}, prescanSelected:new Set(), sys:null, timers:{} };

const ICONS = {
  download:'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
  upload:'<path d="M12 13V2l4 4"/><path d="M12 6 8 2"/><path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7"/>',
  scan:'<circle cx="11" cy="11" r="7"/><path d="m21 21-3.5-3.5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check:'<path d="M20 6 9 17l-5-5"/>',
  alert:'<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  plus:'<path d="M12 5v14"/><path d="M5 12h14"/>',
  chevron:'<path d="m9 18 6-6-6-6"/>',
};
const icon = (name, sz=11, sw=1.5) =>
  `<svg width="${sz}" height="${sz}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]||''}</svg>`;

// status → tag (单色;告警不用红)
const TASK_STATUS_TAG = {
  downloading:{cls:'tag-accent', label:'下载中', ic:'download'},
  scanning:{cls:'tag-accent', label:'扫描中', ic:'scan'},
  uploading:{cls:'tag-accent', label:'上传中', ic:'upload'},
  waiting_confirmation:{cls:'tag-outline', label:'待确认', ic:'clock'},
  queued:{cls:'tag-neutral', label:'排队中', ic:'clock'},
  cancelled:{cls:'tag-neutral', label:'已取消', ic:null},
  completed:{cls:'tag-accent', label:'已完成', ic:'check'},
  completed_with_errors:{cls:'tag-outline', label:'完成·有错误', ic:'alert'},
  failed:{cls:'tag-outline', label:'失败', ic:'alert'},
  created:{cls:'tag-neutral', label:'新建', ic:null},
};
const statusTag = (s) => {
  const t = TASK_STATUS_TAG[s] || {cls:'tag-neutral', label:s, ic:null};
  return `<span class="tag ${t.cls}" style="gap:5px">${t.ic?icon(t.ic):''}${t.label}</span>`;
};

// operation buttons — 严格对应后端
function taskActions(task) {
  const s = task.status;
  if (task.needs_confirmation || s === 'waiting_confirmation')
    return `<button class="btn btn-primary" data-act="confirm" data-id="${task.task_id}">开始</button>`
         + `<button class="btn btn-secondary" data-act="cancel" data-id="${task.task_id}">取消</button>`;
  if (s === 'scanning')
    return `<button class="btn btn-secondary" data-act="cancel" data-id="${task.task_id}">取消</button>`;
  if (s === 'completed' || s === 'completed_with_errors' || s === 'cancelled' || s === 'failed')
    return `<button class="btn btn-ghost" data-act="clear" data-id="${task.task_id}">清除</button>`;
  return '—';  // downloading / uploading / queued
}
```

- [ ] **Step 3: 内联脚本 —— 渲染任务表 + 系统监控**

```javascript
function renderTaskTable(tasks) {
  const tbody = $('#task_rows');
  $('#task_count').textContent = tasks.length;
  tbody.innerHTML = tasks.map(t => {
    const prog = t.total_count ? Math.round((t.success_count + t.skipped_count) / t.total_count * 100) : 0;
    const fail = t.failed_count > 0 ? `<b>${t.failed_count}</b>` : '0';
    const cur = t.current_file ? (t.current_file.filename || '') : '—';
    const sel = t.task_id === state.selectedTaskId ? ' style="background:color-mix(in srgb,var(--color-accent) 8%,transparent)"' : '';
    return `<tr data-id="${t.task_id}" data-type="${t.task_type}"${sel}>
      <td class="nums">${t.task_id}</td><td>${t.source||''}</td><td>${t.task_type||''}</td>
      <td>${statusTag(t.status)}</td><td>${t.title||''}</td>
      <td><div class="track" style="width:120px"><i style="width:${prog}%"></i></div><span class="nums text-muted" style="font-size:11px">${t.success_count}/${t.total_count}</span></td>
      <td class="nums">${t.success_count} / ${fail} / ${t.skipped_count}</td>
      <td class="text-muted" style="font-size:12px">${cur}</td>
      <td style="display:flex;gap:4px">${taskActions(t)}</td></tr>`;
  }).join('');
}

function renderSystem(sys) {
  state.sys = sys;
  const mb = (b) => (b/1048576).toFixed(0), gb = (b) => (b/1073741824).toFixed(0);
  $('#sys_dl').textContent = sys.download_speed;
  $('#sys_ul').textContent = sys.upload_speed;
  const diskPct = Math.round(sys.disk_used / sys.disk_total * 100);
  $('#sys_disk_track').firstElementChild.style.width = diskPct + '%';
  $('#sys_disk_text').textContent = `已用 ${gb(sys.disk_used)} GB / ${gb(sys.disk_total)} GB · 剩 ${gb(sys.disk_free)} GB`;
  const warn = $('#sys_disk_warn');
  warn.hidden = diskPct <= 80;
  warn.innerHTML = `${icon('alert',11)} 偏满 ${diskPct}%`;
  $('#sys_cpu_track').firstElementChild.style.width = Math.round(sys.cpu_percent) + '%';
  $('#sys_cpu').textContent = `CPU ${sys.cpu_percent}%`;
  const memPct = Math.round(sys.mem_used / sys.mem_total * 100);
  $('#sys_mem_track').firstElementChild.style.width = memPct + '%';
  $('#sys_mem').textContent = `内存 ${mb(sys.mem_used)} / ${mb(sys.mem_total)} MB`;
}
```

- [ ] **Step 4: 内联脚本 —— 轮询骨架 + 命令栏/操作接线**

```javascript
async function getJSON(url){ const r = await fetch(url); return r.json(); }
async function postJSON(url){ const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'}}); return r.json(); }

async function pollTasks() {
  const dash = await getJSON('/api/task-dashboard');
  const tasks = dash.tasks || [];
  state.lastTasksById = Object.fromEntries(tasks.map(t=>[t.task_id,t]));
  renderTaskTable(tasks);
  $('#sum_active').textContent = tasks.filter(t=>['downloading','uploading','scanning','queued'].includes(t.status)).length;
  $('#sum_completed').textContent = tasks.filter(t=>t.status.startsWith('completed')).length;
  $('#sum_speed').textContent = dash.download_speed;
  $('#foot_speed').textContent = '⬇ ' + dash.download_speed;
  setStateChip(dash.download_state);
  if (state.selectedTaskId && state.lastTasksById[state.selectedTaskId]) renderDetail(state.lastTasksById[state.selectedTaskId]); // T6
  const sys = await getJSON('/api/system'); renderSystem(sys);
}
function renderDetail(){ /* T6 */ }
function setStateChip(dstate){
  const chip = $('#download_state'), on = dstate === 'Downloading';
  $('#download_state_text').textContent = on ? '运行中' : '已暂停';
  chip.dataset.value = on ? 'pause' : 'continue';
}

function startPolling(tab){
  stopPolling();
  if (tab==='tasks'){ pollTasks(); state.timers.tasks = setInterval(pollTasks, 1000); }
  else if (tab==='files'){ pollFiles(); state.timers.files = setInterval(pollFiles, 1000); }  // T7
  else if (tab==='config'){ loadConfig(); }  // T8
}
function stopPolling(){ Object.values(state.timers).forEach(clearInterval); state.timers={}; }

// tab switching
document.querySelectorAll('.app-nav a[data-tab]').forEach(a => a.addEventListener('click', e => {
  e.preventDefault();
  const tab = a.dataset.tab;
  document.querySelectorAll('.app-nav a[data-tab]').forEach(x=>x.removeAttribute('aria-current'));
  a.setAttribute('aria-current','page');
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  $('#tab_'+tab).classList.add('active');
  $('#nav_total_speed').style.display = tab==='files' ? '' : 'none';
  startPolling(tab);
}));

// command bar
$('#web_task_link').addEventListener('keydown', e => { if (e.key==='Enter') submitTask(); });
$('#submit_task_btn').addEventListener('click', submitTask);
document.querySelectorAll('input[name="web_task_mode"]').forEach(r => r.addEventListener('change', () => {
  $('#web_task_count').style.display = document.querySelector('input[name="web_task_mode"]:checked').value==='prescan' ? '' : 'none';
}));
async function submitTask(){
  const link = $('#web_task_link').value.trim();
  const mode = document.querySelector('input[name="web_task_mode"]:checked').value;
  const body = mode==='prescan' ? {mode:'prescan', max_messages:Number($('#web_task_count').value)||2000} : {link};
  const r = await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mode==='prescan'?{...body}:{link})});
  const res = await r.json();
  $('#task_submit_status').textContent = res.error ? res.error : '已提交';
  if (res.task_id){ state.selectedTaskId = res.task_id; state.selectedTaskType = res.task_type||null; }
  pollTasks();
}
// task action buttons (event delegation)
$('#task_rows').addEventListener('click', async e => {
  const btn = e.target.closest('button[data-act]');
  if (btn){ e.stopPropagation();
    const id = btn.dataset.id, act = btn.dataset.act;
    const url = act==='confirm'?`/api/tasks/${id}/confirm`:act==='cancel'?`/api/tasks/${id}/cancel`:`/api/tasks/${id}/clear`;
    await postJSON(url); pollTasks(); return; }
  const tr = e.target.closest('tr[data-id]');
  if (tr) selectTask(tr.dataset.id, tr.dataset.type);
});
function selectTask(id, type){ state.selectedTaskId=id; state.selectedTaskType=type;
  const t = state.lastTasksById[id]; if (t) renderDetail(t); pollTasks(); }

// state chip + logout + version
$('#download_state').addEventListener('click', async () => {
  const next = $('#download_state').dataset.value;
  await fetch('/set_download_state?state='+next, {method:'POST'}); pollTasks();
});
$('#logout_btn').addEventListener('click', async () => { await fetch('/logout',{method:'POST'}); location.href='/'; });
getJSON('/get_app_version').then(v=>{}).catch(()=>{}); // version already in template; optional
startPolling('tasks');
```

> **提交任务的 body**:预扫描发 `{mode,max_messages}`,普通发 `{link}` —— 见 spec §5.1。`dash.tasks` 的键名以 `/api/task-dashboard` 实际返回为准(执行时 `curl` 或读 `TaskStateStore.dashboard`,若为 `summaries`/其它则改)。

- [ ] **Step 5: 浏览器 harness 保真验证**

建 `scratchpad/harness/mock.js`(导出 mock dashboard / system JSON,含各状态任务、磁盘 82% 触发告警)与 `scratchpad/harness/tasks.html`(引 `index.css` + 粘贴 `#tab_tasks` markup + 用 mock 替换 fetch,调用 renderTaskTable/renderSystem)。浏览器核对(对照 `prototype.html:67-256`):
- [ ] 命令栏角标、分段控件选中态 accent 实底、预扫描时消息数出现;
- [ ] 汇总卡 26px 标题字数字 + live-dot;
- [ ] 系统监控:上行速度 accent-700 高亮;磁盘 82% 时描边告警「偏满 82%」+ 三角图标出现,≤80% 隐藏;CPU/内存 track;
- [ ] 任务表:每种状态标签的 cls/图标/文案符合映射;失败>0 加粗;操作按钮 —— 待确认=开始+取消、扫描中=取消、completed*=清除、下载中/上传中=「—」;
- [ ] 选中行 accent 8% 高亮。

- [ ] **Step 6: Commit**

```bash
git add module/templates/index.html
git commit -m "feat(web): tasks screen — polling skeleton, command bar, summary, system monitor, task table"
```

---

### Task 6: 任务详情面板(按 selectedTaskType 三态渲染)

**Files:**
- Modify: `module/templates/index.html`(`#tab_tasks` 内追加 `#task_detail` 容器 + 实现 `renderDetail`)
- Verify: `scratchpad/harness/detail.html`

**Interfaces:**
- Consumes:T5 `state`、`icon`、`statusTag`、`renderDetail` 钩子;`/api/tasks/<id>`(含 files)、`/api/prescans/<id>/packages`、`.../<pkg>/select`、`.../select-all`、`/api/tasks/<id>/confirm`。
- Produces:`renderDetail(task)` 完整实现,三分支 —— `renderFileTable`、`renderPrescanPackages`(待确认)、`renderPrescanDownloading`(确认后)。

- [ ] **Step 1: markup 容器**

在任务表卡之后加 `#task_detail`(`.card.blueprint`,结构参照 `prototype.html:258-333` 包列表 与 `:344-397` 下载中详情):头部 kicker「任务详情」+ `#detail_title` + `#detail_meta`;`#prescan_controls`(选择控件条,默认 hidden);`#detail_body`(表格容器)。

- [ ] **Step 2: `renderDetail` 分派 + 普通任务文件表**

```javascript
function renderDetail(task){
  const box = $('#task_detail'); box.hidden = false;
  $('#detail_title').innerHTML = (task.title||'任务') + ' ' + statusTag(task.status);
  if (task.task_type === 'prescan'){
    if (task.status === 'waiting_confirmation') renderPrescanPackages(task);
    else renderPrescanDownloading(task);
  } else {
    $('#prescan_controls').hidden = true;
    getJSON(`/api/tasks/${task.task_id}`).then(full => renderFileTable(full.files||[]));
  }
}
function fileStatusLabel(s){ return ({queued:'待下载',downloading:'下载中',downloaded:'已下载',
  uploading:'上传中',uploaded:'已上传',upload_failed:'上传失败',skipped:'跳过',failed:'失败'})[s]||s; }
function renderFileTable(files){
  $('#detail_meta').textContent = `${files.length} 个文件`;
  $('#detail_body').innerHTML = `<div class="table-scroll"><table class="table" style="font-size:13px">
    <thead><tr><th>消息 ID</th><th>状态</th><th>文件名</th><th>大小</th><th>进度</th><th>备注</th></tr></thead>
    <tbody>${files.map(f=>`<tr><td class="nums">${f.message_id}</td><td>${fileStatusLabel(f.status)}</td>
      <td>${f.filename||''}</td><td class="nums">${f.total_size}</td>
      <td><div class="track" style="width:90px"><i style="width:${f.download_progress}%"></i></div></td>
      <td class="text-muted" style="font-size:12px">${f.error||f.download_speed||''}</td></tr>`).join('')}</tbody></table></div>`;
}
```

- [ ] **Step 3: 预扫描包列表(待确认)+ 选择控件条 + 展开**

```javascript
async function renderPrescanPackages(task){
  const data = await getJSON(`/api/prescans/${task.task_id}/packages?page=1&page_size=200`);
  state.prescanRows[task.task_id] = data.items;
  $('#detail_meta').textContent = `${data.total} 个包同属此任务 · 点击包名展开其文件`;
  const ctrl = $('#prescan_controls'); ctrl.hidden = false;
  const selCount = data.items.filter(p=>p.selected).length;
  const selMedia = data.items.filter(p=>p.selected).reduce((a,p)=>a+p.media_count,0);
  ctrl.innerHTML = `<button class="btn btn-secondary" data-pact="all">全选</button>
    <button class="btn btn-secondary" data-pact="none">清空</button>
    <span class="text-muted nums" style="font-size:12px">已选 ${selCount} / ${data.total} 包 · ${selMedia} 媒体</span>
    <button class="btn btn-primary" data-pact="confirm">下载所选</button>`;
  $('#detail_body').innerHTML = `<div class="table-scroll"><table class="table" style="font-size:13px">
    <thead><tr><th></th><th>包</th><th>选择</th><th>消息区间</th><th>媒体</th><th>已知大小</th><th>标题</th><th>操作</th></tr></thead>
    <tbody>${data.items.map(p=>`<tr data-pkg="${p.package_id}">
      <td><button class="btn btn-ghost" data-expand="${p.package_id}" style="padding:2px">${icon('chevron',12)}</button></td>
      <td class="nums">#${p.package_id}</td>
      <td>${p.selected?'<span class="tag tag-accent">已选</span>':'—'}</td>
      <td class="nums">${p.start_message_id}–${p.end_message_id}</td>
      <td class="nums">${p.media_count}</td><td class="nums">${p.known_total_size}</td><td>${p.title}</td>
      <td><button class="btn btn-secondary" data-toggle="${p.package_id}" data-sel="${p.selected?0:1}">${p.selected?'排除':'加入'}</button></td>
    </tr>`).join('')}</tbody></table></div>`;
}
// controls + toggle + expand delegation
$('#task_detail').addEventListener('click', async e => {
  const id = state.selectedTaskId;
  const c = e.target.closest('[data-pact]');
  if (c){ const a=c.dataset.pact;
    if (a==='all') await postJSON(`/api/prescans/${id}/packages/select-all`, {selected:true});
    if (a==='none') await postJSON(`/api/prescans/${id}/packages/select-all`, {selected:false});
    if (a==='confirm'){ const r=await postJSON(`/api/tasks/${id}/confirm`); if(r.error) alert(r.error); }
    return renderDetail(state.lastTasksById[id]); }
  const t = e.target.closest('[data-toggle]');
  if (t){ await fetch(`/api/prescans/${id}/packages/${t.dataset.toggle}/select`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected:t.dataset.sel==='1'})});
    return renderDetail(state.lastTasksById[id]); }
  const x = e.target.closest('[data-expand]');
  if (x) return togglePackageFiles(id, x.dataset.expand);
});
async function togglePackageFiles(taskId, pkgId){
  const row = $(`#task_detail tr[data-pkg="${pkgId}"]`);
  const next = row.nextElementSibling;
  if (next && next.dataset.filesFor===pkgId){ next.remove(); return; }
  const full = await getJSON(`/api/tasks/${taskId}`);
  const files = (full.files||[]).filter(f=>true); // 若后端按包分组则按 package 过滤;否则展示全部
  const tr = document.createElement('tr'); tr.dataset.filesFor = pkgId;
  tr.innerHTML = `<td></td><td colspan="7" style="padding-left:24px"><table class="table" style="font-size:12px">
    ${files.map(f=>`<tr><td class="nums">${f.message_id}</td><td>${f.filename||''}</td><td class="nums">${f.total_size}</td><td>${fileStatusLabel(f.status)}</td></tr>`).join('')}</table></td>`;
  row.after(tr);
}
```

> `postJSON` 需支持 body。把 T5 的 `postJSON` 改为 `postJSON(url, body)`:`fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined})`。**包内文件按包过滤**:确认后端 `/api/tasks/<id>/files` 或 `.../<id>` 是否带 package 归属字段;若无,展开显示该任务全部文件并在计划执行时记录此限制(spec §6.1 期望逐包文件,能力取决于后端是否暴露包-文件映射)。

- [ ] **Step 4: 预扫描下载中(确认后)**

```javascript
async function renderPrescanDownloading(task){
  $('#prescan_controls').hidden = true;
  const data = await getJSON(`/api/prescans/${task.task_id}/packages?page=1&page_size=200`);
  const selected = data.items.filter(p=>p.selected);  // 仅选中的包参与下载
  const prog = task.total_count ? Math.round((task.success_count+task.skipped_count)/task.total_count*100) : 0;
  $('#detail_meta').innerHTML = `<div class="track" style="width:260px;display:inline-block;vertical-align:middle"><i style="width:${prog}%"></i></div>
    <span class="nums text-muted" style="font-size:11.5px;margin-left:8px">整体 ${task.success_count} / ${task.total_count} 媒体</span>
    <button class="btn btn-secondary" data-act="cancel" data-id="${task.task_id}" style="margin-left:10px">暂停</button>`;
  $('#detail_body').innerHTML = `<div class="table-scroll"><table class="table" style="font-size:13px">
    <thead><tr><th></th><th>包</th><th>状态</th><th>进度</th><th>媒体</th><th>大小</th><th>标题</th></tr></thead>
    <tbody>${selected.map(p=>`<tr data-pkg="${p.package_id}">
      <td><button class="btn btn-ghost" data-expand="${p.package_id}" style="padding:2px">${icon('chevron',12)}</button></td>
      <td class="nums">#${p.package_id}</td><td>${statusTag(task.status)}</td>
      <td><div class="track" style="width:100px"><i style="width:0%"></i></div></td>
      <td class="nums">${p.media_count}</td><td class="nums">${p.known_total_size}</td><td>${p.title}</td></tr>`).join('')}</tbody></table></div>`;
}
```

> 逐包进度依赖 T4 后端在下载中写入每包进度;若后端仅给任务级进度,包级进度轨用任务级近似并在执行记录中注明(spec §5.3.3 目标是逐包/逐文件写入)。

- [ ] **Step 5: 浏览器 harness 验证**

`scratchpad/harness/detail.html` 用三组 mock(普通任务含 files、prescan+waiting_confirmation+packages、prescan+downloading+selected packages)分别调用 `renderDetail`。核对(对照 `prototype.html:258-397`):
- [ ] 普通任务 → 文件表列齐、状态中文、进度轨;
- [ ] 预扫描待确认 → 包列表 + 选择控件条(全选/清空/已选统计/下载所选)+ 已选包「已选」标签 + 加入/排除;chevron 展开包内文件缩进;
- [ ] 预扫描下载中 → 整体进度 + 暂停 + 仅选中包出现 + 逐包行;
- [ ] 「下载所选」未选任何包时后端返回 400,前端 alert 提示。

- [ ] **Step 6: Commit**

```bash
git add module/templates/index.html
git commit -m "feat(web): type-aware task detail — file table, prescan packages, prescan downloading"
```

---

### Task 7: 文件页(下载中 / 上传中 / 已完成 三段堆叠)

**Files:**
- Modify: `module/templates/index.html`(填充 `#tab_files` + `pollFiles`)
- Verify: `scratchpad/harness/files.html`

**Interfaces:**
- Consumes:T3 `/get_upload_list`;现有 `/get_download_list?already_down=false|true`;T5 `state`/`pollFiles` 钩子/`icon`。
- Produces:`pollFiles()` 完整实现;`#nav_total_speed` 在文件页显示。

- [ ] **Step 1: markup**（结构参照 `prototype.html:412-457`,三张 `.card.blueprint`）

`#tab_files` 内三卡:下载中(头部「下载中」+ `#dl_count` tag + 右侧 `#dl_total_speed`;表 `#dl_rows` 列:会话·ID·文件名·大小·下载进度·下载速度)、上传中(头部「上传中」+ `#ul_count` + 右侧「rclone → tg-media/incoming」;表 `#ul_rows` 列:会话·ID·文件名·大小·上传进度·上传速度)、已完成(头部「已完成」+ `#done_count` + `#clear_done_btn` ghost;表 `#done_rows` 列:会话·ID·文件名·大小·保存路径)。进度列用 `.track` + %。

- [ ] **Step 2: `pollFiles` 实现**

```javascript
async function pollFiles(){
  const [dl, ul, done] = await Promise.all([
    getJSON('/get_download_list?already_down=false'),
    getJSON('/get_upload_list'),
    getJSON('/get_download_list?already_down=true'),
  ]);
  const dash = await getJSON('/api/task-dashboard');
  $('#nav_total_speed').textContent = '⬇ ' + dash.download_speed;
  $('#dl_total_speed').textContent = '总速度 ' + dash.download_speed;
  $('#foot_speed').textContent = '⬇ ' + dash.download_speed;
  $('#dl_count').textContent = dl.length; $('#ul_count').textContent = ul.length; $('#done_count').textContent = done.length;
  $('#dl_rows').innerHTML = dl.map(r=>`<tr><td>${r.chat}</td><td class="nums">${r.id}</td><td>${r.filename}</td>
    <td class="nums">${r.total_size}</td><td><div class="track" style="width:120px"><i style="width:${r.download_progress}%"></i></div><span class="nums text-muted" style="font-size:11px">${r.download_progress}%</span></td>
    <td class="nums">${r.download_speed}</td></tr>`).join('');
  $('#ul_rows').innerHTML = ul.map(r=>`<tr><td>${r.chat}</td><td class="nums">${r.id}</td><td>${r.filename}</td>
    <td class="nums">${r.total_size}</td><td><div class="track" style="width:120px"><i style="width:${r.upload_progress}%"></i></div><span class="nums text-muted" style="font-size:11px">${r.upload_progress}%</span></td>
    <td class="nums">${r.upload_speed}</td></tr>`).join('');
  $('#done_rows').innerHTML = done.map(r=>`<tr><td>${r.chat}</td><td class="nums">${r.id}</td><td>${r.filename}</td>
    <td class="nums">${r.total_size}</td><td class="nums text-muted" style="font-size:12px">${r.save_path}</td></tr>`).join('');
}
$('#clear_done_btn').addEventListener('click', async () => { await postJSON('/api/tasks/clear-completed'); pollFiles(); });
```

- [ ] **Step 3: harness 验证** — `files.html` 用 mock 三列表核对(对照 `prototype.html:412-457`):三段堆叠、上传中头部 rclone 目标、已完成清空按钮、进度轨与 %、等宽保存路径。

- [ ] **Step 4: Commit**

```bash
git add module/templates/index.html
git commit -m "feat(web): files screen — downloading / uploading / completed stacked tables"
```

---

### Task 8: 高级配置页(分区卡片 + 保存)

**Files:**
- Modify: `module/templates/index.html`(填充 `#tab_config` + `loadConfig`/`saveConfig`)
- Verify: `scratchpad/harness/config.html`

**Interfaces:**
- Consumes:`GET/POST /api/settings`(字段见 spec §5.2);T5 `state.settingsCache`、`.sw` 样式。
- Produces:`loadConfig()`/`saveConfig()`;chip 多选、`.sw` 开关交互。

- [ ] **Step 1: markup**（分区卡片参照 `prototype.html:477-560`;每分区 `.card.blueprint` + `.cfg-title`)

七张卡:存储 / 并发(2 列)/ Web 服务 / 媒体 / 命名 / 上传 / 会话(`.table`),底部「保存配置」primary + `#config_status`。字段 id 对齐 spec §6.3(`#save_path`、`#date_format`、`#start_timeout`、`#max_download_task`、`#max_concurrent_transmissions`、`#web_host`、`#web_port`、chip 容器 `#media_type_chips`/`#path_prefix_chips`/`#name_prefix_chips`、`#file_name_prefix_split`、`#format_audio`/`#format_document`/`#format_video`、`#upload_adapter`(select)、`#remote_dir`、`#rclone_path`、开关 `#sw_*`、会话表 `#chat_rows`)。

- [ ] **Step 2: chip + switch 组件辅助**

```javascript
function chip(label, on){ return `<span class="tag ${on?'tag-accent':'tag-outline'}" data-chip="${label}" data-on="${on?1:0}" style="cursor:pointer;gap:4px">${on?icon('check',10,2):''}${label}</span>`; }
function renderChips(container, options, selected){
  container.innerHTML = options.map(o=>chip(o, selected.includes(o))).join('');
  container.onclick = e => { const c=e.target.closest('[data-chip]'); if(!c) return;
    const on=c.dataset.on==='1'; c.dataset.on=on?0:1; c.className=`tag ${on?'tag-outline':'tag-accent'}`;
    c.innerHTML = (on?'':icon('check',10,2))+c.dataset.chip; };
}
function chipValues(container){ return [...container.querySelectorAll('[data-chip][data-on="1"]')].map(c=>c.dataset.chip); }
function setSwitch(el, on){ el.classList.toggle('on',on); el.classList.toggle('off',!on); el.dataset.on=on?1:0; el.onclick=()=>{ const v=el.dataset.on==='1'; setSwitch(el,!v); }; }
```

- [ ] **Step 3: loadConfig / saveConfig**

```javascript
async function loadConfig(){
  const s = await getJSON('/api/settings'); state.settingsCache = s;
  $('#save_path').value=s.save_path; $('#date_format').value=s.date_format; $('#start_timeout').value=s.start_timeout;
  $('#max_download_task').value=s.max_download_task; $('#max_concurrent_transmissions').value=s.max_concurrent_transmissions;
  $('#web_host').value=s.web.web_host; $('#web_port').value=s.web.web_port;
  $('#format_audio').value=(s.file_formats.audio||[]).join(', ');
  $('#format_document').value=(s.file_formats.document||[]).join(', ');
  $('#format_video').value=(s.file_formats.video||[]).join(', ');
  $('#file_name_prefix_split').value=s.file_name_prefix_split;
  $('#upload_adapter').value=s.upload_drive.upload_adapter;
  $('#remote_dir').value=s.upload_drive.remote_dir; $('#rclone_path').value=s.upload_drive.rclone_path;
  renderChips($('#media_type_chips'), s.options.media_types, s.media_types);
  renderChips($('#path_prefix_chips'), s.options.file_path_prefix, s.file_path_prefix);
  renderChips($('#name_prefix_chips'), s.options.file_name_prefix, s.file_name_prefix);
  setSwitch($('#sw_drop_no_audio_video'), s.drop_no_audio_video);
  setSwitch($('#sw_enable_download_txt'), s.enable_download_txt);
  setSwitch($('#sw_hide_file_name'), s.hide_file_name);
  setSwitch($('#sw_enable_web'), s.web.enable_web);
  setSwitch($('#sw_enable_upload_file'), s.upload_drive.enable_upload_file);
  setSwitch($('#sw_before_upload_file_zip'), s.upload_drive.before_upload_file_zip);
  setSwitch($('#sw_after_upload_file_delete'), s.upload_drive.after_upload_file_delete);
  setSwitch($('#sw_after_upload_telegram_delete'), s.after_upload_telegram_delete);
  $('#chat_rows').innerHTML = s.chats.map(c=>`<tr><td class="nums">${c.chat_id}</td><td class="nums">${c.last_read_message_id}</td><td>${c.download_filter}</td><td class="nums">${c.upload_telegram_chat_id}</td></tr>`).join('');
}
async function saveConfig(){
  const swOn = id => $(id).dataset.on==='1';
  const csv = id => $(id).value.split(',').map(x=>x.trim()).filter(Boolean);
  const payload = {
    save_path:$('#save_path').value, date_format:$('#date_format').value, start_timeout:Number($('#start_timeout').value),
    max_download_task:Number($('#max_download_task').value), max_concurrent_transmissions:Number($('#max_concurrent_transmissions').value),
    media_types:chipValues($('#media_type_chips')), file_path_prefix:chipValues($('#path_prefix_chips')),
    file_name_prefix:chipValues($('#name_prefix_chips')), file_name_prefix_split:$('#file_name_prefix_split').value,
    file_formats:{audio:csv('#format_audio'), document:csv('#format_document'), video:csv('#format_video')},
    drop_no_audio_video:swOn('#sw_drop_no_audio_video'), enable_download_txt:swOn('#sw_enable_download_txt'),
    hide_file_name:swOn('#sw_hide_file_name'), after_upload_telegram_delete:swOn('#sw_after_upload_telegram_delete'),
    web:{enable_web:swOn('#sw_enable_web'), web_host:$('#web_host').value, web_port:Number($('#web_port').value)},
    upload_drive:{enable_upload_file:swOn('#sw_enable_upload_file'), upload_adapter:$('#upload_adapter').value,
      rclone_path:$('#rclone_path').value, remote_dir:$('#remote_dir').value,
      before_upload_file_zip:swOn('#sw_before_upload_file_zip'), after_upload_file_delete:swOn('#sw_after_upload_file_delete')},
  };
  const r = await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const res = await r.json();
  $('#config_status').textContent = res.ok ? '已保存 · 主机/端口修改后需重启' : (res.error||'保存失败');
}
$('#save_config_btn').addEventListener('click', saveConfig);
```

> POST payload 的键结构须与 `_apply_settings` 期望一致 —— 执行前读 `module/web.py:1378 _apply_settings` 确认嵌套键(`web.*`、`upload_drive.*`),按其实际接受结构对齐(上面按 `_settings_from_app` 的对称结构;若 `_apply_settings` 扁平接收则拍平)。

- [ ] **Step 3-verify: harness** — `config.html` 用 mock settings 核对:七卡布局、字段回填、chip 选中(accent+对勾)/未选(描边)、`.sw` 开关方角滑块、保存后状态文案。范围/最小值(1–32 / 1–200 / 1–65535)由 input `min`/`max` 约束。

- [ ] **Step 4: Commit**

```bash
git add module/templates/index.html
git commit -m "feat(web): advanced config screen — sectioned cards, chips, switches, save"
```

---

### Task 9: 登录页分栏重构

**Files:**
- Rewrite: `module/templates/login.html`（沿用 AES,重排版式）
- Verify: `scratchpad/harness/login.html`

**Interfaces:**
- Consumes:现有 `login` POST + CryptoJS AES(key/iv 见 Global Constraints);`module/static/css/index.css`;`module/static/aes/...`。
- Produces:分栏登录页。

- [ ] **Step 1: 先读现有 login.html 保留加密逻辑**

`cat module/templates/login.html` —— 摘出其 `<script>` 里的 AES 加密 + POST + `code==='1'` 跳转逻辑,**原样保留**。

- [ ] **Step 2: 重写版式**（结构参照 `prototype.html:569-585`）

`<body>` 用 `.app`(min-height 520,grid place-items center)包一张分栏 `.card.blueprint`(宽 820,横向,无填充,含四角标):
- 左栏 320px `background:var(--color-accent-900);color:var(--color-bg)`:品牌(download 图标 26 + 「TG 媒体下载器」)· 大标题「私有部署 / 下载控制台」· 说明段(`opacity:.72`)· 底部「v2.2.0 · localhost:5000」。
- 右栏 padding 大:kicker「欢迎回来」+ 标题「登录」· 密码 `.input`(`type=password`,`id=password`,min-height 40)· 「确认登录」`.btn.btn-primary.btn-block.blueprint`(42 高,四角标)· 提示「密码在服务端 config.yaml 中设置 · 提交时经 AES 加密」· `#login_error`(描边告警,默认 hidden)。

引 `static/css/index.css` + `static/aes/crypto-js-master/crypto-js.js`(按现有 login.html 实际引用路径)。把 Step 1 的加密逻辑接到「确认登录」按钮与密码框回车。错误时 `#login_error` 显示(描边 + 三角图标,不用红)。

- [ ] **Step 3: harness 验证** — `scratchpad/harness/login.html` 复制 login body(去 Jinja)核对:左栏深蓝实底反白、右栏表单、角标、primary block 按钮、错误提示样式。**加密逻辑不改**(仅核对按钮触发 POST 的代码路径未动)。

- [ ] **Step 4: Commit**

```bash
git add module/templates/login.html
git commit -m "feat(web): split-panel login in Industry style, AES logic unchanged"
```

---

### Task 10: 全屏联调 + 保真核对 + 部署

**Files:**
- Create: `progress.md`(若不存在则建,末尾追加)
- Verify: 全套 `scratchpad/harness/*` + `pytest`

- [ ] **Step 1: 后端全绿**

Run: `pytest tests/ -q`
Expected: 全 PASS(至少 T2/T3/T4 新测试 + 未回归既有)。若既有测试因 layui 移除/模板变更失败,定位修正。

- [ ] **Step 2: 四屏保真终检**

用一个综合 harness(或依次打开各 `scratchpad/harness/*.html`),浏览器逐屏对照 `docs/design/frontend-redesign/prototype.html` 的四屏 + 两监控状态,逐条走 spec §6 的每个规格点(状态映射、操作按钮、告警阈值、三段文件表、配置七卡、登录分栏)。记录任何像素/交互偏差并修正。

- [ ] **Step 3: 语法/引用自检**

- [ ] `grep -rn "layui" module/templates/ module/static/css/index.css` → 应无残留(登录/index 不再引 layui)。
- [ ] `grep -rn "TODO" module/web.py` → T2 的占位 TODO 已被 T3 清除。
- [ ] 浏览器 console 无报错(harness 各页)。

- [ ] **Step 4: 追加 progress.md**

按用户模板追加一轮(## 日期 - Task / What was done / Testing / Notes: Changed files + Rollback)。

- [ ] **Step 5: 合并 + 部署(用户标准流程)**

```bash
git checkout master && git merge --no-ff feature/web-industry-redesign -m "feat(web): Industry blueprint redesign of the web console"
git push origin master
ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && pip install -r requirements.txt && systemctl restart tg-downloader.service'
curl -sI https://tgdn.wyichuan.cc/ | head -1   # 期望 302 → /login
```

> **部署机需装 psutil**:`pip install -r requirements.txt` 覆盖(已含新依赖)。若部署机用独立 venv,确认在该 venv 内安装。

- [ ] **Step 6: 记录部署结果到 progress.md 的 Testing,提交(若 progress.md 在 master)**

---

## Self-Review(计划自检)

**Spec coverage(逐节核对):**
- §2 架构 A + 全量后端 → T1(A/去 layui)、T2–T4(后端)✓
- §3 设计系统/保真 → T1(CSS+shell)+ 各屏 harness 核对 ✓
- §4 全局框架(顶栏/底栏/轮询/切 Tab) → T1(外壳)+ T5(轮询/切 Tab/state chip/logout)✓
- §5.3.1 `/api/system` → T2 ✓;§5.3.2 上传进度 → T3 ✓;§5.3.3 预扫描保留 → T4 ✓
- §6.1 任务屏(命令栏/汇总/监控/任务表/详情三态) → T5 + T6 ✓
- §6.2 文件屏三段 → T7 ✓;§6.3 配置七卡 → T8 ✓;§6.4 登录分栏 → T9 ✓
- §7 状态管理(selectedTaskId/Type、lastTasksById、prescanRows、sys、定时器) → T5 ✓
- §9 验证(pytest + harness) → 各任务 verify + T10 ✓;§10 部署 → T10 ✓
- §11 约束(psutil、非阻塞 cpu、AES 不改、脱敏后端) → Global Constraints + T2/T9 ✓

**已知能力边界(非计划占位,执行时按后端实际决定并记录):**
- 逐包/逐文件进度(T6 Step 3/4)取决于 T4 后端是否暴露包-文件映射与逐包进度;若仅任务级,退化近似并在 progress 记录。
- `/get_upload_list` 上传进度数据源(T3 Step 6)在实现时定位真实统计结构后定断言。
- `/api/task-dashboard` 任务数组键名、`_apply_settings` 接收结构(T5/T8)执行时以源码为准对齐。

**Placeholder scan:** 无「TBD/稍后实现」;T2 的 upload_speed 占位是**显式跨任务接口顺序**(T3 Step 7 清除),已在 T10 Step 3 校验。

**Type consistency:** `state`/`icon`/`statusTag`/`taskActions`/`postJSON(url,body)`/`renderDetail`/`pollFiles`/`loadConfig` 跨任务签名一致(T5 定义,T6–T8 复用;T6 Step 3 已注明把 `postJSON` 扩展为带 body)。
