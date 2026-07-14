# 交接文档：Telegram Media Downloader 前端重构（Web 控制台）

## 概述
把现有几乎无设计的 layui 管理界面，重构为统一的 **Industry 蓝图风格**（钢蓝 + 方角 + 十字定位标记 + Barlow 字体）Web 控制台，全中文、桌面优先。覆盖四个界面：**任务（Tasks）/ 文件（Files）/ 高级配置（Advanced Config）/ 登录（Login）**，并新增**上传进度**与**系统资源监控**。

核心目标（来自需求方）：
1. 让**任务流程清晰**——扫描 → 待确认 → 队列 → 下载 → 上传 → 完成，每一步可见。
2. Web 端承担比 bot 更复杂的交互：**每个下载任务可配更多选项**。
3. 补齐监控盲区：**上传到网盘的进度**、**磁盘/CPU/内存等系统资源**（下载对磁盘负载大）。

## 关于设计文件（重要）
本包内的 HTML 是**设计参考稿**（用 HTML 表达最终外观与交互的原型），**不是**可直接照搬上线的生产代码。任务是：**在目标代码库的现有环境中重建这些设计**。

当前目标环境是本仓库的 **Flask + Jinja2 模板 + layui + jQuery**（`module/templates/index.html`、`login.html`，`module/static/`）。建议二选一：
- **A（推荐、改动小）**：保留 Flask 后端与轮询接口，用本设计的 Industry 视觉语言**替换 layui**——重写 `index.html` / `login.html` 的结构 + 一份手写 CSS（照抄 `design/ds/styles.css` 的 token 与组件类），表格用原生 `<table>` 或轻量渲染替代 layui table。
- **B**：前端换成一个 SPA（React/Vue），后端提供本文「API」一节列出的 JSON 接口。

无论哪种，**视觉必须像素级还原本设计**（见下「设计 tokens」与各屏规格）。

## 保真度
**高保真（hi-fi）**。颜色、字体、间距、圆角、交互状态均为最终值，全部来自 `design/ds/styles.css` 的 CSS 变量。开发时请直接引用这些变量，不要另造数值或颜色。

---

## 设计系统：Industry
所有视觉取自 `design/ds/styles.css`（唯一样式源）。要点：

- **配色**：浅灰底 `--color-bg #f2f2f3`、正文 `--color-text #1d1f20`、单一钢蓝强调色 `--color-accent #5980a6`。单色（mono）方案，无第二强调色。错误/告警**不用红色**——用描边标签（`.tag-outline`）+ 告警图标表达。
- **强调色阶**：`--color-accent-100…900`（浅 `#eef6ff` → 深 `#1d2d3d`）。正文级蓝字用 `--color-accent-700 #416180`；深色实底用 `--color-accent-900 #1d2d3d`（如登录左栏，文字反白为 `--color-bg`）。
- **中性色阶**：`--color-neutral-100…900`。
- **分隔线**：`--color-divider = color-mix(in srgb, #1d1f20 16%, transparent)`。
- **字体**：标题 `--font-heading "Barlow Condensed"`（600），正文 `--font-body "Barlow"`（400/500/700）。Google Fonts：`Barlow:400,500,700` + `Barlow+Condensed:400,600`。
- **形状**：一律**方角**（组件圆角被覆盖为 0）。卡片/图形是**透明线框**（1px `--color-divider` 边框、无填充）；唯一实底对象是 **primary 按钮**（accent 填充）。
- **蓝图定位标记**：卡片、主按钮、对话框等「框」对象加 `.blueprint` 类 + 四个 `<i class="corner tl|tr|bl|br"></i>` 子元素，在四角画「+」十字标记（画在框外 -6px 处，父级勿 `overflow:hidden`）。
- **图标**：Lucide（https://lucide.dev），**stroke-width 1.5**，内联 SVG，`stroke="currentColor"`。
- **间距**：`--space-1..8`（3.4 / 6.8 / 10.2 / 13.6 / 20.4 / 27.2px，已含 0.85× 密度）。
- **阴影**：`--shadow-sm/md/lg`（如 `--shadow-lg: 0 12px 32px rgba(43,43,45,.22)`）。
- **交互态**：`:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px }`；`::selection` 为 accent 30% 淡色；禁用态 45% 透明度。

### 组件类（见 styles.css）
`.btn` + `.btn-primary/.btn-secondary/.btn-ghost/.btn-icon/.btn-block`；`.tag` + `.tag-accent/.tag-accent-2/.tag-neutral/.tag-outline`；`.field`>`label` + `.input`（也可用于 `<select>`）；`.seg` + `.seg-opt`（分段控件，原生 radio）；`.radio` + `.dot`；`.card` + `.card-kicker/.card-title/.card-body/.card-meta` + `.elev-sm/md/lg`；`.table`；`.nav` + `.nav-brand`；`.dialog-backdrop` + `.dialog`；`.blueprint` + `.corner`。

### 设计稿内自定义的少量样式（非 DS，一并实现）
- `.app`：应用外壳 —— 宽 1240px、`--color-bg` 底、1px `--color-divider` 边、`--shadow-lg`、`overflow:hidden`。
- `.app-nav`：顶栏，`display:flex; gap:26px; padding:15px 24px; border-bottom:1px solid --color-divider`。`.brand` 用标题字 18px；导航 `a` 14px，当前项 `aria-current="page"` → accent 色 + 2px accent 下边框。
- `.app-body`：`padding:22px 24px 26px; display:flex; flex-direction:column; gap:18px`。
- `.app-foot`：底栏，`padding:11px 24px; border-top:1px solid --color-divider; font-size:12px; --color-neutral-600`，左「Telegram Media Downloader v2.2.0」右「⬇ 6.88 MB/s」。
- `.state-chip`：运行状态开关，方角描边按钮 + `.live-dot`（7px 圆点 accent + 3px accent-100 光环）。
- `.track`：进度条轨道 `height:6px; background:--color-neutral-200`，内层 `> i` 为 accent 填充，用 `width:%` 表示进度。
- `.nums`：`font-variant-numeric: tabular-nums`（所有数字/ID/大小/速度用等宽数字）。
- `.sw`：开关（方角）——`i` 为 34×19 轨道，`::after` 为 15×15 方形滑块；`.sw.on` 时轨道 accent、滑块靠右；`.off` 文本用 neutral-600。
- `.screen-cap`：仅用于设计画布分屏标注，实现时忽略。

---

## 全局框架
- **顶栏**（任务/文件/配置三屏共用）：品牌（下载图标 + “TG 媒体下载器”）· 三个 Tab（任务 / 文件 / 高级配置）· 右侧「运行状态开关」（`.state-chip`，运行中/已暂停，点击切换，对应现有 `set_download_state`）·「退出」ghost 按钮（log-out 图标，对应 `logout`）。文件页顶栏额外在开关左侧显示实时总速度。
- **底栏**：版本号 + 实时下载速度。
- **轮询**：任务页每 1s 拉 `/api/task-dashboard`；文件页每 1s 拉下载/已下载/上传列表；系统监控每 1s 拉 `/api/system`（新增）。切 Tab 时切换定时器（沿用现有逻辑）。

---

## 屏幕规格

### 1) 任务（Tasks）—— 主屏
自上而下：
1. **命令栏**（`.card.blueprint`，横向）：粘贴链接 `.input`（等宽字体）· 模式分段控件 `.seg`（预览 / 预扫描）· 消息数 `.input`（仅预扫描时显示，默认 2000，1–10000）· 「提交任务」primary 按钮（+ 图标）。回车即提交。
2. **汇总卡**（4 个 `.card.blueprint`，`grid` 四等分）：进行中 3 · 已完成 128 · 状态（live-dot + 运行中）· 当前速度 6.88 MB/s。数字用标题字 26px。
3. **系统监控卡**（新增，`.card.blueprint`，头部「系统监控 · 每秒刷新」+ 一行分块，块间竖分隔线）：
   - 下行速度 6.88 MB/s
   - **上行速度 · 上传** 3.10 MB/s（accent-700 高亮，新增，来自 `/api/system.upload_speed`）
   - **磁盘 · /downloads**（更宽 flex:1.9）：`.track`(8px) 显示占用 82%，右上角描边告警标签「偏满 82%」（>80% 时显示，图标为三角感叹号）；下方「已用 412 GB / 500 GB · 剩 88 GB」。
   - CPU 34% + 5px track。
   - 内存 512 / 1024 MB + 5px track（50%）。
4. **任务表**（`.card.blueprint` 包 `.table`）：头部「下载任务」+ 计数标签 + 过滤（全部/进行中/已完成）。列：任务 ID · 来源（频道/私聊）· 类型（合集/评论/预扫描/单条）· 状态（`.tag`）· 标题 · 进度（`.track` + n/总）· 成功/失败/跳过（等宽，失败>0 加粗）· 当前文件 · 操作。
   - **状态→标签映射**（单色）：下载中/扫描中/上传中 → `.tag-accent`（带对应图标）；待确认 → `.tag-outline`；排队中/已取消 → `.tag-neutral`；已完成 → `.tag-accent` + 对勾；完成·有错误/失败 → `.tag-outline` + 三角感叹号。
   - **操作按钮**（严格对应后端）：`needs_confirmation`（待确认）→「开始」primary +「取消」secondary；`scanning`→「取消」；`completed*`→「清除」ghost；其余 → 「—」。**下载中/上传中无操作按钮**（显示 —）。
   - 选中行加 accent 8% 底色高亮，并联动下方「任务详情」。
   - 上传中任务行示例：进度轨 100%，副文本「下载 40/40 · 上传 30/40」，当前文件「↑ wall_31.jpg · 74%」。
5. **任务详情（按类型区分，关键）**：
   - **普通任务**（合集/评论/单条）→ 扁平**文件表**：消息 ID · 状态（已下载/下载中/跳过等）· 文件名 · 大小 · 进度 · 备注（速度/错误）。
   - **预扫描任务**（`task_type==="prescan"`）→ **包列表**（所有包挂在同一任务下！）：
     - 头部：任务标题 + 状态标签 + “N 个包同属此任务 · 点击包名展开其文件”。
     - **选择控件条**（`waiting_confirmation` 时）：全选 / 清空 / “已选 3 / 5 包 · 96 媒体 · 4.2 GB” / **下载所选**（primary，= confirm）。
     - 包表列：包序号（带展开箭头 chevron）· 选择（`已选` 标签 / —）· 消息区间 · 媒体数 · 已知大小 · 标题 · 操作（加入/排除）。
     - 展开某包 → 其下缩进一段「包内文件」列表（消息 ID · 文件名 · 大小 · 状态）。
   - **预扫描下载中**（confirm 后）：包表列改为 包 · 状态（已完成/下载中/待下载）· 进度（`.track` n/总）· 媒体 · 大小 · 标题；顶部整体进度条 + 当前速度 +「暂停」。展开正在下载的包 → 逐文件进度（下载中带 % 轨、已下载对勾、其余待下载）。**仅被选中的包会出现在下载中**（未选的不下载）。

### 2) 文件（Files）
三张 `.card.blueprint` 表，纵向堆叠：
- **下载中**（tag 计数 + 头部右侧「总速度 6.88 MB/s」）：会话 · ID · 文件名 · 大小 · 下载进度（`.track` + %）· 下载速度。
- **上传中**（新增；头部右侧「rclone → tg-media/incoming」）：会话 · ID · 文件名 · 大小 · 上传进度 · 上传速度。
- **已完成**（头部「清空已完成」ghost 按钮）：会话 · ID · 文件名 · 大小 · 保存路径（等宽）。

> 说明：原界面用「下载中/已完成」两个子 Tab 切换；重构改为**同页堆叠三段**（含新增「上传中」），信息更全，符合桌面场景。

### 3) 高级配置（Advanced Config）
每个环节一张 `.card.blueprint`（标题 = 图标 + 标题字 15.5px）。字段用 `.field`>`label` + `.input`；开关用 `.sw`；多选项用 `.tag`（选中 `.tag-accent`+对勾 / 未选 `.tag-outline`）。分区（对应现有 config）：
- **存储**：保存路径 · 日期格式 · 启动超时（秒）。
- **并发**（与 Web 并排 2 列）：工作线程（1–32）· TG 传输通道（1–200）· 开关：丢弃静音视频 / 下载文本消息 / 隐藏文件名。
- **Web 服务**：主机 · 端口（1–65535）· 开关：启用 Web。
- **媒体**：下载类型 chip（音频/文档/图片/视频/视频笔记/语音）· 音频/文档/视频 格式（逗号分隔）。
- **命名**：目录组成 chip · 文件名组成 chip · 分隔符。
- **上传**：适配器 `<select>`（rclone/aligo）· 远程目录 · rclone 路径 · 开关：启用上传 / 先压缩打包 / 上传后删本地 / 删除 TG 原消息。
- **会话**（`.table`）：会话 ID（等宽）· 最后已读 · 下载过滤 · 上传会话。
- 底部：「保存配置」primary + 状态文案「已保存 · 主机/端口修改后需重启」。

### 4) 登录（Login）
应用底色居中一张分栏 `.card.blueprint`（宽 820，横向，无填充）：
- **左栏**（320px，`--color-accent-900` 实底、文字反白 `--color-bg`）：品牌（下载图标 26 + “TG 媒体下载器”）· 大标题「私有部署 / 下载控制台」· 一句说明（72% 透明）· 底部「v2.2.0 · localhost:5000」。
- **右栏**：kicker「欢迎回来」+ 标题「登录」· 密码 `.input`（type=password，min-height 40）·「确认登录」primary block 按钮（42 高）· 提示「密码在服务端 config.yaml 中设置 · 提交时经 AES 加密」。
- 行为：沿用现有 `login.html` —— 密码经 CryptoJS AES（CBC/Pkcs7，key `1234123412ABCDEF`、iv `ABCDEF1234123412`）加密后 POST `login`，返回 `code==='1'` 跳转首页，否则提示错误。

---

## 交互与行为
- **提交任务**：`POST /api/tasks {link, mode}`；预扫描加 `max_messages`。成功后选中该任务、刷新看板。失败显示 `error`。
- **任务动作**：开始=`POST /api/tasks/<id>/confirm`；取消=`POST /api/tasks/<id>/cancel`；清除=`POST /api/tasks/<id>/clear`；清空已完成=`POST /api/tasks/clear-completed`。
- **预扫描选择**：`POST /api/prescans/<id>/packages/<pkg>/select {selected}`；`.../select-all {selected}`；分页 `GET /api/prescans/<id>/packages?page&page_size`。「下载所选」= confirm（至少选 1 个，否则 400）。
- **状态开关**：`POST set_download_state?state=...`。
- **轮询**：见「全局框架」。进度条 `width` 随进度更新，`.transition: width .3s`。
- **响应式**：桌面优先；`.app` 固定 1240，窄屏时表格可横向滚动、汇总卡降为 2 列（参考原 `index.css` 的 760px 断点）。

## 状态管理
需要维护：`settingsCache`、`selectedTaskId` / `selectedTaskType`、`lastTasksById`、各定时器句柄、预扫描 `prescanRows` 与已选集合、系统监控快照。详情面板依 `selectedTaskType` 在「文件表 / 包列表 / 包-下载中」间切换渲染。

## API（现有 + 需新增）
**现有**（见 `docs/web-control-console.md` 与 `module/web.py`）：
`GET /api/task-dashboard`、`GET /api/tasks`、`GET /api/tasks/<id>`、`GET /api/tasks/<id>/files`、`POST /api/tasks`、`.../confirm|cancel|clear`、`POST /api/tasks/clear-completed`、`GET /api/prescans/<id>/packages`、`.../select|select-all`、`GET/POST api/settings`、`get_download_list`、`get_download_status`、`set_download_state`、`get_app_version`、`login`、`logout`。

**建议新增 / 调整**（为支撑新监控与详情）：
1. **`GET /api/system`**（新增）：返回 `{cpu_percent, mem_used, mem_total, disk_used, disk_total, disk_free, download_speed, upload_speed}`（磁盘针对 `save_path` 所在卷；用 `psutil` 或 `shutil.disk_usage`）。前端系统监控卡消费此接口。
2. **上传进度纳入监控**：`/api/task-dashboard` 的任务里补充 `upload_progress / upload_speed / upload_success_count`；新增「上传中」文件列表（可扩展 `get_download_list` 或新增 `get_upload_list`）。任务状态含 `uploading`、文件状态含 `uploading/uploaded/upload_failed`（后端已有这些枚举）。
3. **预扫描确认后保留包状态**（重要缺口）：当前 `confirm_task` 会 `_pending_web_prescans.pop(task_id)`，导致 `/api/prescans/<id>/packages` 在下载开始后 404、详情变空。建议**确认后保留**包清单并持续写入每包/每文件进度，使「预扫描下载中」详情可用。

## 资源 / Assets
- **字体**：Google Fonts Barlow + Barlow Condensed（styles.css 顶部已 `@import`）。可自托管以离线。
- **图标**：Lucide 内联 SVG（download / upload / activity / scan / clock / layers / check / alert-triangle / folder / sliders / log-out / pause / plus / chevron 等），stroke-width 1.5。
- **样式**：`design/ds/styles.css`（唯一样式源，务必引用其变量）。
- **原界面参考**：`reference/original_web_ui.gif`（重构前的 layui 界面，仅作对比）。
- 无位图资源；登录不再使用原 `login.svg` 插画（改为 accent 分栏）。

## 文件清单
- `design/TG Downloader Redesign.dc.html` —— 高保真原型（四屏 + 两监控状态）。可读的 HTML：结构 + 内联样式 + DS 类；开发时按此还原。（注：`1a` 为交付方向；同文件内 `1b 流水线` 为早期备选看板方向，可忽略或作参考。）
- `design/ds/styles.css` —— Industry 设计系统 token 与组件类。
- `reference/original_web_ui.gif` —— 重构前界面。

> 目标仓库中对应文件：`module/templates/index.html`、`module/templates/login.html`、`module/static/css/index.css`、`module/static/request/index.js`、`module/web.py`。
