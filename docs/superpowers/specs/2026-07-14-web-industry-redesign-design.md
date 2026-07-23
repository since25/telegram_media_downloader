# Spec: Web 控制台 Industry 蓝图风格前端重构

**日期:** 2026-07-14
**分支:** `feature/web-industry-redesign`
**交接来源:** `前端重构与设计规划.zip` → `design_handoff_frontend_redesign/`(README + `design/ds/styles.css` + `design/TG Downloader Redesign.dc.html`)

---

## 1. 目标

把现有 layui + jQuery 的 Web 控制台重构为统一的 **Industry 蓝图风格**(钢蓝 + 方角 + 十字定位标记 + Barlow 字体),全中文、桌面优先。覆盖四屏 **任务 / 文件 / 高级配置 / 登录**,并新增 **上传进度** 与 **系统资源监控**。

需求方三个核心目标:
1. 任务流程清晰可见:扫描 → 待确认 → 队列 → 下载 → 上传 → 完成。
2. Web 端承担比 bot 更复杂的交互(每个下载任务可配更多选项)。
3. 补齐监控盲区:上传到网盘的进度、磁盘/CPU/内存等系统资源。

## 2. 架构决策(已定)

- **路线 A(原地替换 layui)**:保留 Flask + Jinja2 + 现有轮询接口,手写 Industry CSS 替换 layui,原生 `<table>` 替代 layui table。改动集中在 `module/templates/index.html`、`module/templates/login.html`、`module/static/`。
- **不选 SPA(路线 B)的理由**:部署目标是 **1 vCPU / 1 GiB RackNerd**,且 Flask web 与下载器(Pyrogram 客户端 + 下载事件循环 + rclone)**同进程共享 1 核 1G**。构建好的静态 SPA 运行时开销与 A 相近,但 B 会引入构建/部署复杂度;当前部署链是 `git pull --ff-only + systemctl restart`、**无 CI**,B 要么在 1G 机上构建(下载高峰有 OOM 风险)要么新搭 CI。A 无构建步骤、去掉 layui 后比现状更轻,故选 A。
- **全量后端改动纳入本次**:`GET /api/system`(新)、上传进度接入、预扫描确认后保留包状态(修复现有缺口)。

## 3. 设计系统与保真度

- **唯一样式源**:`design/ds/styles.css`(token + 组件类)。开发直接引用其 CSS 变量,不另造数值/颜色。
- **像素参考**:`design/TG Downloader Redesign.dc.html`(四屏 + 两监控状态高保真原型)。其中标注 `1a` 为交付方向,同文件内 `1b 流水线` 为早期备选,忽略。
- **保真度**:高保真(hi-fi),颜色/字体/间距/圆角/交互态均为最终值。

### 关键 token(摘自 styles.css)
- 配色:`--color-bg #f2f2f3`、`--color-surface #e9e9ea`、`--color-text #1d1f20`、单一强调色 `--color-accent #5980a6`;强调色阶 `--color-accent-100…900`(正文蓝 `--color-accent-700 #416180`,深实底 `--color-accent-900 #1d2d3d`);中性 `--color-neutral-100…900`;分隔线 `--color-divider = color-mix(in srgb,#1d1f20 16%,transparent)`。
- **单色方案,无第二强调色。错误/告警不用红色**——用 `.tag-outline`(描边标签)+ 三角感叹号图标。
- 字体:标题 `--font-heading "Barlow Condensed"`(600),正文 `--font-body "Barlow"`(400/500/700)。Google Fonts `@import` 已在 styles.css 顶部;可自托管以离线。
- 形状:**一律方角**(组件 radius 覆盖为 0);卡片/图形是透明线框(1px `--color-divider`、无填充);唯一实底对象是 primary 按钮(accent 填充)。
- 间距:`--space-1..8`(3.4 / 6.8 / 10.2 / 13.6 / 20.4 / 27.2px);阴影 `--shadow-sm/md/lg`。
- 交互态:`:focus-visible` 2px accent outline;`::selection` accent 30%;禁用态 45% 透明度。

### 组件类(styles.css 已提供)
`.btn`+变体、`.tag`+变体、`.field>label`+`.input`、`.seg`+`.seg-opt`、`.radio`+`.dot`、`.card`+`.card-*`+`.elev-*`、`.table`、`.nav`+`.nav-brand`、`.dialog-backdrop`+`.dialog`、`.blueprint`+`.corner`。

### 设计稿内自定义样式(非 DS,需一并实现)
- `.app`:应用外壳,宽 1240px、`--color-bg` 底、1px divider 边、`--shadow-lg`、`overflow:hidden`。
- `.app-nav`:顶栏,`display:flex; gap:26px; padding:15px 24px; border-bottom:1px solid divider`;`.brand` 标题字 18px;导航 `a` 14px,当前项 `aria-current="page"` → accent + 2px accent 下边框。
- `.app-body`:`padding:22px 24px 26px; display:flex; flex-direction:column; gap:18px`。
- `.app-foot`:底栏,`padding:11px 24px; border-top:1px solid divider; font-size:12px; neutral-600`,左「Telegram Media Downloader v2.2.0」右「⬇ 6.88 MB/s」。
- `.state-chip`:运行状态开关,方角描边按钮 + `.live-dot`(7px accent 圆点 + 3px accent-100 光环)。
- `.track`:进度条轨道 `height:6px; background:neutral-200`,内层 `> i` 为 accent 填充,`width:%` 表进度,`transition: width .3s`。
- `.nums`:`font-variant-numeric: tabular-nums`(所有数字/ID/大小/速度用等宽数字)。
- `.sw`:方角开关,`i` 为 34×19 轨道、`::after` 为 15×15 方形滑块;`.sw.on` 时轨道 accent、滑块靠右;`.off` 文本用 neutral-600。
- `.screen-cap`:仅设计画布分屏标注,实现时忽略。

### 图标
Lucide(lucide.dev),**stroke-width 1.5**,内联 SVG,`stroke="currentColor"`。需要:download / upload / activity / scan / clock / layers / check / alert-triangle / folder / sliders / log-out / pause / plus / chevron 等。无位图资源;登录不再用原 `login.svg`。

## 4. 全局框架

- **顶栏(任务/文件/配置三屏共用)**:品牌(download 图标 + 「TG 媒体下载器」)· 三 Tab(任务 / 文件 / 高级配置)· 右侧运行状态开关(`.state-chip`,运行中/已暂停,点击切换 → `POST set_download_state?state=...`)· 「退出」ghost 按钮(log-out 图标 → `POST logout`)。**文件页顶栏额外在开关左侧显示实时总速度**。
- **底栏**:版本号 + 实时下载速度。
- **轮询**:任务页每 1s 拉 `/api/task-dashboard`;文件页每 1s 拉 下载/已下载/上传 列表;系统监控每 1s 拉 `/api/system`(新增)。切 Tab 时切换定时器(沿用现有逻辑)。

## 5. 后端契约

### 5.1 现有接口(保持不变,前端消费)
- `GET /api/task-dashboard`:任务摘要 + `download_state` + `download_speed` + `download_speed_bytes`。
- `GET /api/tasks`、`GET /api/tasks/<id>`、`GET /api/tasks/<id>/files?page&page_size`。
- `POST /api/tasks {link}` / `{mode:"prescan", max_messages}`。
- `POST /api/tasks/<id>/confirm|cancel|clear`、`POST /api/tasks/clear-completed`。
- `GET /api/prescans/<id>/packages?page&page_size`、`.../<pkg>/select {selected}`、`.../select-all {selected}`。
- `GET/POST /api/settings`、`GET /get_download_list?already_down=true|false`、`GET /get_download_status`、`POST set_download_state`、`GET /get_app_version`、`login`、`logout`。

### 5.2 现有数据形状(实现依据,已核对源码)

**TaskSnapshot.to_dict**(`module/task_state.py`):`task_id, source, task_type, chat_id, title, status, created_at, updated_at, total_count, success_count, failed_count, skipped_count, upload_success_count, current_file, workflow, error, needs_confirmation`,`include_files=True` 时附 `files[]`。

**任务状态枚举**(`TaskStatus`):`created, scanning, waiting_confirmation, queued, downloading, uploading, completed, completed_with_errors, cancelled, failed`。

**文件状态枚举**(`FileStatus`):`queued, downloading, downloaded, uploading, uploaded, upload_failed, skipped, failed`。

**FileSnapshot.to_dict**:`message_id, status, filename, total_size, total_size_bytes, downloaded_size, downloaded_size_bytes, download_progress, download_speed, download_speed_bytes, save_path, error, updated_at`。

**`_package_summary`**(预扫描包):`package_id, title, start_message_id, end_message_id, media_count, known_total_size, known_total_size_bytes, selected`。

**`GET /api/settings`** 返回:`save_path, media_types[], file_formats{audio/document/video}, file_path_prefix[], file_name_prefix[], file_name_prefix_split, max_download_task, max_concurrent_transmissions, start_timeout, date_format, hide_file_name, drop_no_audio_video, enable_download_txt, after_upload_telegram_delete, upload_drive{enable_upload_file, upload_adapter, rclone_path, remote_dir, before_upload_file_zip, after_upload_file_delete}, web{enable_web, web_host, web_port}, chats[]{chat_id, last_read_message_id, download_filter, upload_telegram_chat_id}, options{media_types, file_path_prefix, file_name_prefix}`。

**`get_download_list`**(每项):`chat, id, filename, total_size, download_progress, download_speed, save_path`。

### 5.3 新增 / 调整(本次范围)

1. **`GET /api/system`(新增)**:返回
   `{cpu_percent, mem_used, mem_total, disk_used, disk_total, disk_free, download_speed, upload_speed}`。
   - CPU/内存用 `psutil`(需加入依赖);磁盘针对 `app.save_path` 所在卷用 `shutil.disk_usage`。
   - `download_speed` 复用 `get_total_download_speed()`;`upload_speed` 见第 2 项。
   - `@login_required`,与其它 API 一致。
2. **上传进度接入**:
   - `FileSnapshot` 增补上传字段(`upload_progress`、`upload_speed` / bytes);任务级在 `TaskSnapshot`/dashboard 输出 `upload_progress`、`upload_speed`(`upload_success_count` 已存在)。
   - 新增「上传中」文件列表:**新增 `GET /get_upload_list`**(返回 uploading 状态文件:会话/ID/文件名/大小/上传进度/上传速度),与 `get_download_list` 形状对齐、不改后者契约。上传进度数据源在实现阶段定位(下载器/上传器统计),spec 只固定接口名与返回字段。
   - 状态枚举 `uploading/uploaded/upload_failed` 后端已有,前端需消费。
3. **预扫描确认后保留包状态(修复缺口)**:当前 `confirm_task`(`module/web.py:1038`)`_pending_web_prescans.pop(task_id)`,导致 `/api/prescans/<id>/packages` 在下载开始后 404、详情变空。
   - 改为**确认后保留**包清单(仅在 clear/cancel/terminal 时清理),并在下载过程中持续写入每包/每文件进度,使「预扫描下载中」详情可用。
   - 注意保持 `cancel_task`、「select at least one package」400 校验、RuntimeError 回滚等现有行为不回归。

## 6. 屏幕规格

### 6.1 任务(Tasks)——主屏
自上而下:
1. **命令栏**(`.card.blueprint` 横向):粘贴链接 `.input`(等宽)· 模式分段 `.seg`(预览 / 预扫描)· 消息数 `.input`(仅预扫描显示,默认 2000,1–10000)· 「提交任务」primary(+ 图标)。**回车即提交**。
2. **汇总卡**(4 个 `.card.blueprint`,grid 四等分):进行中 · 已完成 · 状态(live-dot + 运行中/已暂停)· 当前速度。数字用标题字 26px。
3. **系统监控卡**(`.card.blueprint`,头部「系统监控 · 每秒刷新」+ 一行分块,竖分隔线):下行速度 · **上行速度·上传**(accent-700 高亮,来自 `/api/system.upload_speed`)· **磁盘·/downloads**(flex:1.9;8px `.track` 占用%,右上描边告警「偏满 N%」当 >80% 时显示 + 三角感叹号;下方「已用 X / Y · 剩 Z」)· CPU%(5px track)· 内存 used/total MB(5px track)。
4. **任务表**(`.card.blueprint` 包 `.table`):头部「下载任务」+ 计数标签 + 过滤(全部/进行中/已完成)。列:任务 ID · 来源 · 类型 · 状态(`.tag`)· 标题 · 进度(`.track` + n/总)· 成功/失败/跳过(等宽,失败>0 加粗)· 当前文件 · 操作。
   - **状态→标签映射**(单色):下载中/扫描中/上传中 → `.tag-accent`(带图标);待确认 → `.tag-outline`;排队中/已取消 → `.tag-neutral`;已完成 → `.tag-accent`+对勾;完成·有错误/失败 → `.tag-outline`+三角感叹号。
   - **操作按钮**(严格对应后端):`needs_confirmation`/待确认 → 「开始」primary(confirm)+「取消」secondary(cancel);`scanning` → 「取消」;`completed*` → 「清除」ghost(clear);其余 → 「—」。**下载中/上传中无操作按钮(显示 —)**。
   - 选中行加 accent 8% 底色高亮,并联动下方任务详情。
   - 上传中行示例:进度轨 100%,副文本「下载 40/40 · 上传 30/40」,当前文件「↑ wall_31.jpg · 74%」。
5. **任务详情(按类型区分)**:见 §7 前端状态管理的 `selectedTaskType` 分支。
   - **普通任务**(合集/评论/单条)→ 扁平文件表:消息 ID · 状态 · 文件名 · 大小 · 进度 · 备注(速度/错误)。
   - **预扫描任务**(`task_type==="prescan"`)→ 包列表(所有包挂同一任务):头部「N 个包同属此任务 · 点击包名展开其文件」;`waiting_confirmation` 时显示选择控件条(全选 / 清空 / 「已选 X / Y 包 · N 媒体 · Z」/ 「下载所选」primary = confirm);包表列 包序号(chevron 展开)· 选择(`已选` 标签 / —)· 消息区间 · 媒体数 · 已知大小 · 标题 · 操作(加入/排除);展开某包 → 缩进「包内文件」列表(消息 ID · 文件名 · 大小 · 状态)。
   - **预扫描下载中**(confirm 后)→ 包表列改为 包 · 状态(已完成/下载中/待下载)· 进度(`.track` n/总)· 媒体 · 大小 · 标题;顶部整体进度条 + 当前速度 + 「暂停」;展开正在下载的包 → 逐文件进度。**仅被选中的包出现在下载中**。

### 6.2 文件(Files)——三段堆叠 `.card.blueprint` 表
- **下载中**(tag 计数 + 头部右侧「总速度」):会话 · ID · 文件名 · 大小 · 下载进度(`.track`+%)· 下载速度。
- **上传中**(新增;头部右侧「rclone → tg-media/incoming」):会话 · ID · 文件名 · 大小 · 上传进度 · 上传速度。
- **已完成**(头部「清空已完成」ghost):会话 · ID · 文件名 · 大小 · 保存路径(等宽)。
> 原界面用「下载中/已完成」两子 Tab;重构改为同页堆叠三段(含新增「上传中」)。

### 6.3 高级配置(Advanced Config)——分区卡片
每分区一张 `.card.blueprint`(标题=图标+标题字 15.5px)。字段 `.field>label`+`.input`;开关 `.sw`;多选项 `.tag`(选中 `.tag-accent`+对勾 / 未选 `.tag-outline`)。分区(对应 `/api/settings`):
- 存储:保存路径 · 日期格式 · 启动超时(秒)。
- 并发(2 列):工作线程 max_download_task(1–32)· TG 传输通道 max_concurrent_transmissions(1–200)· 开关 drop_no_audio_video / enable_download_txt / hide_file_name。
- Web 服务:web_host · web_port(1–65535)· 开关 enable_web。
- 媒体:media_types chip(音频/文档/图片/视频/视频笔记/语音)· file_formats 音频/文档/视频(逗号分隔)。
- 命名:file_path_prefix chip · file_name_prefix chip · file_name_prefix_split。
- 上传:upload_adapter `<select>`(rclone/aligo)· remote_dir · rclone_path · 开关 enable_upload_file / before_upload_file_zip / after_upload_file_delete / after_upload_telegram_delete。
- 会话(`.table`):chat_id(等宽)· last_read_message_id · download_filter · upload_telegram_chat_id。
- 底部:「保存配置」primary + 状态文案「已保存 · 主机/端口修改后需重启」。

### 6.4 登录(Login)——分栏卡片(宽 820 横向)
- 左栏(320px,`--color-accent-900` 实底、文字反白 `--color-bg`):品牌(download 图标 26 + 「TG 媒体下载器」)· 大标题「私有部署 / 下载控制台」· 一句说明(72% 透明)· 底部「v2.2.0 · localhost:5000」。
- 右栏：kicker「欢迎回来」+ 标题「登录」· 密码 `.input`(type=password,min-height 40)· 「确认登录」primary block(42 高)· 提示「密码由服务端验证」。
- 行为：密码以标准表单 POST 提交给 `login`，由服务端验证；`code==='1'` 跳首页，否则提示错误。非本机访问必须通过 HTTPS 保护传输。

## 7. 前端状态管理

维护:`settingsCache`、`selectedTaskId` / `selectedTaskType`、`lastTasksById`、各定时器句柄、预扫描 `prescanRows` 与已选集合、系统监控快照。详情面板依 `selectedTaskType` 在「文件表 / 包列表 / 包-下载中」间切换渲染。进度条 `width` 随进度更新(`transition: width .3s`)。

**响应式**:桌面优先;`.app` 固定 1240;窄屏时表格可横向滚动、汇总卡降为 2 列(参考原 `index.css` 760px 断点)。

## 8. 任务拆分(依赖顺序,subagent-driven 执行)

**阶段 0 · 前端地基**
- **T1 设计系统 CSS + 应用外壳**:把 styles.css 的 token/组件类**重写进 `module/static/css/index.css`**(单一手写 Industry 样式表,复用现有 include 路径、最小改模板);实现 `.app/.app-nav/.app-body/.app-foot/.blueprint/.state-chip/.track/.nums/.sw`;内联 Lucide 图标集;顶栏(品牌+三 Tab+运行开关+退出)+ 底栏;移除 index.html/login.html 对 layui CSS/JS 的引用。

**阶段 1 · 后端使能(先于消费它的前端)**
- **T2 `GET /api/system`**:psutil + shutil.disk_usage,返回 §5.3.1 字段;加 psutil 依赖。
- **T3 上传进度接入**:§5.3.2 —— dashboard/文件级上传字段 + 上传中列表。
- **T4 预扫描确认后保留包状态**:§5.3.3 —— 修复 confirm 后 packages 404。

**阶段 2 · 前端各屏**
- **T5 任务页(含状态/轮询骨架)**:§7 state + 轮询骨架 + §6.1 命令栏 + 汇总卡 + 系统监控卡 + 任务表(状态→标签、操作映射、行选中联动)。
- **T6 任务详情面板**:§6.1.5 按 `selectedTaskType` 三态渲染。
- **T7 文件页**:§6.2 三段堆叠表。
- **T8 高级配置页**:§6.3 分区卡片 + 保存,映射 `/api/settings`。
- **T9 登录页**：§6.4 分栏重构，使用标准表单提交并由服务端验证。

**阶段 3 · 交付**
- **T10 全屏联调 + 保真核对 + pytest 全绿 + 部署 RackNerd + progress/docs 记录**。

## 9. 验证策略

- **后端(T2–T4)**:`pytest`。用 mock 任务/文件/预扫描状态断言 payload 字段与状态流转;`/api/system` 断言字段齐全、磁盘/内存为合理值。
- **前端(T1、T5–T9)**:**不启本地下载服务**(需真 Telegram 客户端)。用 scratchpad 静态 HTML harness + mock JSON 数据,在浏览器中逐屏核对与设计稿的像素保真(颜色/字体/间距/圆角/角标/状态标签/告警/交互态)。
- **T10**:pytest 全绿 + 四屏保真核对通过 + 部署后 `https://tgdn.wyichuan.cc/` 返回 302 跳登录。

## 10. 部署与交付流程

按标准交付流程(用户 2026-07-14 标准动作):feature 分支 → 每任务实施+审查(subagent-driven,implementer + reviewer)→ 全分支终审 → 合并 master、`git push origin master` → `ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && systemctl restart tg-downloader.service'` → 验证 302 → 记录 `progress.md`。设计/计划批准后免二次确认、一路执行。

## 11. 约束与风险

- **资源天花板**:1 vCPU / 1 GiB,web 与下载器同进程。前端保持轻量(纯静态、去 layui);`/api/system` 用 `psutil.cpu_percent(interval=None)`(非阻塞)避免占核。
- **psutil 依赖**:新增运行时依赖,需同步 requirements 并在部署机安装(`git pull` 后确认 venv 装了 psutil)。
- **预扫描状态保留**:触及 confirm/cancel/清理生命周期,属较高风险区,改动须保证 cancel/clear/terminal 时正确清理,不泄漏内存,不破坏 400/503 回滚行为。
- **登录传输**：不使用客户端固定密钥；密码由服务端验证，非本机访问必须经 HTTPS。
- **hide_file_name**:文件名脱敏由后端 `mask_display_name` 负责,前端直接展示后端返回值,不自行还原。

## 12. 参考文件

- 设计:`design_handoff_frontend_redesign/README.md`、`design/ds/styles.css`、`design/TG Downloader Redesign.dc.html`、`reference/original_web_ui.gif`。
- 目标仓库:`module/templates/index.html`、`module/templates/login.html`、`module/static/css/index.css`、`module/static/request/index.js`、`module/web.py`、`module/task_state.py`。
- 既有文档:`docs/web-control-console.md`。
