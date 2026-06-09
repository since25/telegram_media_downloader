# Prescan Mode Design

## Goal

Add a Telegram bot "prescan mode" for bulk package discovery.

The user should be able to open the bot menu, tap a prescan entry, send one ordinary channel message link such as:

```text
https://t.me/c/1446289027/156439
```

The bot then scans forward from that message, detects multiple continuous media packages, lets the user select which packages to download, and downloads selected packages using the existing recommended C naming format.

## User Decisions

- Entry should be available from the Telegram bot menu. The user should not need to type `/prescan` manually.
- C naming is the default and only exposed naming behavior.
- A/B/D naming choices should be removed from bot-facing interactions. They may remain as internal code during the first implementation if that reduces risk.
- Prescan can take time. Fast feedback is less important than avoiding aggressive Telegram/server request spikes.
- Bulk selected packages must not all start as parallel downloads.

## Scope

### In Scope

- Add a menu command for prescan mode.
- Track per-user prescan session state after the menu command is triggered.
- Accept the next ordinary Telegram message link as the prescan start point.
- Reuse existing private `/c/<internal>/<message_id>` parsing.
- Reuse existing package boundary detection based on captions and inherited captions.
- Scan forward slowly, handling Telegram `FloodWait` by sleeping and resuming.
- Detect and summarize multiple packages.
- Show a paginated package list with selectable packages.
- Download selected packages using C naming:

```text
频道名/起始ID-包标题/消息ID - 原文件名.ext
```

- Queue selected packages serially, in message order.
- Simplify existing guided comment-link and package-link confirmation flows so they expose only C naming.

### Out of Scope

- Web UI or browser-based package selection.
- User-defined naming templates.
- Parallel package downloads.
- Persistent prescan recovery across bot process restarts.
- Rewriting the existing downloader internals beyond what is required for C-only guided flows and serial package execution.

## Telegram Menu Entry

Telegram bot menu commands require a slash command internally, so the implementation should register an English command such as:

```text
/prescan - 预扫模式
```

The user-facing path is tapping the menu item. If a user types `/prescan` manually, it should behave the same way.

When triggered, the bot stores a prescan session keyed by user id:

```text
mode = awaiting_prescan_link
created_at = now
```

The bot replies:

```text
已进入预扫模式，请发送起始频道消息链接。
例如：https://t.me/c/1446289027/156439
```

The existing direct-link single-package behavior should continue when no prescan session is active.

## Prescan User Flow

1. User taps the bot menu item "预扫模式".
2. Bot enters `awaiting_prescan_link` for that user.
3. User sends an ordinary channel message link.
4. Bot parses the link into `chat_id` and `start_message_id`.
5. Bot starts a slow background scan and sends a status message.
6. The status message is periodically edited with progress:

```text
预扫中...
起点：156439
已扫描：850 条消息
已识别：7 个包
最近包：156821 - 156900 / 课程 第07章
```

7. When scanning completes or reaches a safety stop, bot shows package selection pages.
8. User toggles packages on/off with inline buttons.
9. User taps `下载已选`.
10. Bot downloads selected packages one after another using C naming.

## Package Detection

The current single-package planning logic should remain the source of truth for package boundaries:

- The first meaningful media caption becomes the package title.
- Media without captions inherit the active package caption.
- Telegram albums share their group caption.
- Captions are normalized before boundary comparison.
- A clearly different caption starts the next package.

For prescan, the scanner should repeatedly discover packages rather than stopping at the first package:

1. Fetch a bounded batch of messages.
2. Feed the growing message window into package detection.
3. When a next-package boundary is found, finalize the current package.
4. Continue scanning from the boundary message as the next package start.
5. Preserve per-package `PackageMediaItem` metadata for final C naming.

Non-media messages should not form packages, but they can be scanned through while looking for the next media package.

## Scan Limits And Rate Control

The desired behavior is "scan toward newest", but the implementation needs safety limits.

Recommended defaults:

- Fetch batch size: 50 message ids.
- Delay between successful batches: 1 second.
- Max message window per prescan: 5000 message ids.
- Max packages per prescan: 50 packages.
- Missing/empty streak stop: 200 consecutive missing, empty, or inaccessible messages after at least one package has been found.
- Session timeout: 30 minutes for awaiting-link and selection states.

These should be constants first, with config options only if they prove necessary.

If Pyrogram raises `FloodWait`, the scanner must sleep for the requested wait time plus a small buffer, then continue. The status message should say the scan is paused for rate limiting instead of failing immediately.

If a scan reaches a safety limit before proving it reached the newest message, the package selection message should include a warning:

```text
提示：预扫已达到安全上限，结果可能不是频道最新消息。
```

## Package Selection UI

Package selection should be compact for mobile.

Each page should show up to 8 packages:

```text
预扫完成：
频道：Private Course
起点：156439
扫描：4300 条消息
识别：23 个包
已选：0 个

1. 156439-156480｜38 个｜12.4 GB
   课程 第01章
2. 156481-156520｜24 个｜8.1 GB
   课程 第02章
```

Buttons:

- `☐ 1`
- `☐ 2`
- `☑ 3`
- `上一页`
- `下一页`
- `全选本页`
- `清空选择`
- `下载已选`
- `取消`

If checkmark glyphs are unreliable in Telegram clients, plain text alternatives such as `[ ] 1` and `[x] 1` are acceptable.

The selection state should live in memory, keyed by a short callback token. Restart recovery is not required for the first version.

## C-Only Guided Download Changes

Existing comment-link and single-package guided previews should stop exposing A/B/D choices.

The first version should keep underlying strategy code if that avoids a risky refactor, but bot-facing UI should show only:

- C naming preview, using the existing compact parent-folder plus filename display.
- `开始下载`
- `取消`

The callback can still pass `NamingStrategy.RECOMMENDED` internally. The important behavioral change is that the user no longer has to choose among A/B/C/D.

## Serial Download Queue

When the user selects multiple packages, the bot should create one parent bulk task and execute selected packages serially.

Serial means:

1. Start package 1.
2. Download/upload/delete according to existing downloader behavior.
3. Mark package 1 finished.
4. Start package 2.
5. Continue until all selected packages finish or the user stops the task.

The implementation should not create 20 active package download tasks at once.

The status message should report package-level progress:

```text
批量下载中：
包：3 / 20
当前：156821-156900 课程 第03章
当前包媒体：17 / 42
成功：58
失败：1
```

If the existing `TaskNode` progress reporting cannot represent package-level progress cleanly, the first implementation can send simple package start/finish messages and keep detailed per-media progress in the existing downloader status.

## Architecture

Add pure workflow helpers to `module/comment_workflow.py` or a new adjacent module if the file becomes too large:

- `PrescanSession`: per-user state.
- `PrescanPackage`: package id, title, start id, end id, media count, size summary, package plan, messages, failed ids.
- `PrescanPlan`: chat, channel, start id, scanned count, packages, warnings.
- `plan_prescan_packages(messages, start_message_id, limits)`: pure multi-package planner.
- `format_prescan_progress(...)`: status formatter.
- `format_prescan_selection_page(...)`: package selection formatter.
- `build_prescan_callback_data(...)` and parser.

Bot-level additions in `module/bot.py`:

- Register `/prescan` in `set_bot_commands`.
- Add a handler for `/prescan`.
- Store `pending_prescan_sessions`.
- Route ordinary `https://t.me...` links into prescan when a user is awaiting a prescan link.
- Add callback handling for selection toggles, pagination, download confirmation, and cancellation.
- Launch the background scan with the app event loop.

Downloader-level additions in `media_downloader.py`:

- Add a slow multi-package scan wrapper that can reuse `get_messages`, existing media filtering, and existing package planning.
- Add a serial bulk package download function that calls the existing prepared-message download path one package at a time, or reuse that path through a thin orchestrator.

## Error Handling

- Invalid prescan link: keep the session active and ask the user to send a valid ordinary message link.
- Comment link during prescan: explain that prescan currently expects an ordinary channel message link, not `?comment=`.
- Chat access failure: report that the account cannot access the channel.
- No packages found: report no downloadable media packages and end the session.
- FloodWait: sleep and update status.
- Scan safety limit hit: show partial results with a warning.
- Callback token expired: ask the user to run prescan again.
- Selected package download failure: continue with the next selected package, and include failures in the final summary.

## Testing

Unit tests:

- `/prescan` creates an awaiting-link session.
- Direct links are routed to prescan only when a session is active.
- Comment links are rejected inside prescan mode.
- Multi-package planner splits consecutive packages at caption boundaries.
- Planner preserves inherited captions and `PackageMediaItem` metadata.
- Scan limit warning appears when safety limits are hit.
- Selection pagination toggles package ids without losing state.
- `下载已选` rejects empty selections.
- Existing comment and package previews expose only C naming and no A/B/D buttons.
- Bulk package download executes packages serially.

Integration-style tests with mocked Pyrogram:

- Slow scanner fetches batches, sleeps between batches, and handles `FloodWait`.
- Prescan status messages are sent/edited during scanning.
- Confirming selected packages creates a serial queue and passes `NamingStrategy.RECOMMENDED`.

Regression tests:

- Existing direct comment-link workflow still works.
- Existing direct single-package link workflow still works.
- Existing single-message link download still works when prescan is not active.
- Existing malformed private-link handling remains intact.

## Success Criteria

- The bot menu exposes a "预扫模式" entry.
- Tapping that menu entry and sending `https://t.me/c/1446289027/156439` starts a prescan.
- The bot can discover multiple media packages after the starting message.
- The user can select packages from inline buttons.
- Selected packages download in sequence, not in parallel.
- All selected package files use C naming.
- A/B/D choices no longer appear in bot-facing guided download interactions.
- Scanning and downloading remain bounded and rate-limit aware.
