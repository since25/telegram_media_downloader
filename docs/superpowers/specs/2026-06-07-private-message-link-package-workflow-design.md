# Private Message Link Package Workflow Design

## Goal

Let a user paste a private Telegram message link such as:

```text
https://t.me/c/1298283297/126711
```

The bot should convert the private `/c/` link into the correct internal chat id, scan forward from the starting message, detect one continuous media package by caption continuity, preview the package with media sizes and naming examples, and only download/upload after user confirmation.

This removes the need to manually type:

```text
/download https://t.me/c/1298283297/126711 126711 126777 tag
```

## Scope

### In Scope

- Direct pasted ordinary message links, including private `/c/<internal>/<message_id>` links.
- Automatic package scanning from the pasted starting message id.
- Media-only filtering before download.
- Caption inheritance for media messages without captions.
- Similar-caption boundary detection after cleaning numbering, episode markers, and whitespace.
- Next-package boundary preview when a new different caption is found.
- Total and example file-size preview before confirmation.
- Reuse of the existing A/B/C/D naming preview and confirmation flow.
- Adding the same size preview to the existing comment-link workflow.
- Existing rclone upload and after-upload local deletion behavior.

### Out of Scope

- Downloading multiple detected packages in one confirmation.
- A browser or Web UI for selecting arbitrary ranges.
- Manual editing of the detected end id in the first version.
- Persisting scan history across bot restarts.

## User Flow

1. User sends a plain Telegram message link to the bot.
2. Bot detects that the link is an ordinary post/message link, not a comment link.
3. Bot parses the link:
   - `https://t.me/c/1298283297/126711`
   - `chat_id = -1001298283297`
   - `start_message_id = 126711`
4. Bot scans forward from `start_message_id`.
5. Bot builds one package candidate:
   - supported media messages are included;
   - text-only or empty messages are skipped;
   - messages without captions inherit the current package caption;
   - messages in the same `media_group_id` share the group caption.
6. Bot stops when it sees a new caption that is clearly different from the current package caption.
7. Bot shows a preview and confirmation buttons.
8. If confirmed, bot downloads only the detected package media, uploads through the configured adapter, and deletes local files only when the existing config says to do so.

## Caption Continuity Rules

The package title is determined from captions while scanning forward.

- If the starting message has a caption, it becomes the initial package caption.
- If the starting message has no caption, scanning continues until the first media caption is found.
- Media without captions inherit the latest package caption.
- For a Telegram album, all media sharing the same `media_group_id` inherit the group caption if any item in the group has one.
- A new non-empty caption is compared with the current package caption.
- Comparison uses normalized text:
  - trim whitespace;
  - collapse repeated whitespace;
  - remove common numbering and episode markers such as `01`, `1/40`, `第1集`, `EP01`, and bracketed sequence fragments when they are at the edges;
  - validate illegal filename/path characters before showing or using the caption.
- If normalized captions are equal or highly similar, scanning continues in the same package.
- If normalized captions are clearly different, scanning stops before that message.

The boundary message with the new caption is shown as the next-package preview but is not downloaded.

## Scan Limits and Safety

The scanner needs bounded behavior so a single pasted link cannot scan an entire large channel.

- Default max scan window: 500 message ids after the start id.
- If no package boundary is found before the limit, preview the detected media and show a warning:

```text
未发现下一包边界，已达到扫描上限 500 条。
```

- If no media is found, tell the user no downloadable media was detected.
- If every media item lacks a caption and no package title can be inferred, use a deterministic fallback such as `message-126711` and show that fallback in the preview.

## Preview Content

The preview should be compact enough for Telegram but informative enough to avoid accidental large downloads.

Example:

```text
识别到连续资源包：
标题：某某课程 第01章
范围：126711 - 126777
媒体：38 个 video
预计大小：12.4 GB
继承 caption：31 个
最大文件：126735 video 1.2 GB

大小示例：
- 126711 video 421 MB
- 126712 video 388 MB
- 126713 video 402 MB

下一包起点预览：
126778 - 某某课程 第02章
不会纳入本次下载。

命名预览：
A ...
B ...
C 推荐 ...
D ...
```

Confirmation buttons should match the existing comment workflow:

- `采用推荐C`
- `采用A`
- `采用B`
- `采用D`
- `取消`

## Size Preview

Size preview should use Telegram metadata without downloading files.

- For each supported media message, read `file_size` from the selected media object when available.
- Sum known sizes for the package total.
- Count media with unknown sizes and show a warning only when non-zero.
- Show a few example files, preferably the first three media items.
- Show the largest known file.
- Add equivalent size summary to the existing comment-link preview.

If all sizes are unknown, show:

```text
预计大小：未知
```

If some sizes are unknown, show:

```text
预计大小：12.4 GB + 3 个未知大小文件
```

## Naming

The first version should reuse the comment workflow naming strategy enum and preview style.

For ordinary message packages, the naming context should represent:

- channel or chat title;
- start message id;
- package caption/title;
- selected naming strategy.

Recommended naming keeps the detected package together:

```text
频道名/起始ID-包标题/消息ID - 原文件名.ext
```

All path segments and filenames must pass illegal-character cleanup.

## Architecture

Add a pure workflow module or extend the existing `module/comment_workflow.py` into a more general guided media workflow module. The preferred implementation is to keep pure scan planning and preview formatting testable without Telegram network access.

Suggested units:

- `MessagePackageWorkflowRequest`: parsed ordinary message-link request.
- `PackageScanSummary`: scanned count, media count, media type counts, inherited-caption count, known total size, unknown-size count, largest file, next-package preview.
- `PackageMediaItem`: message id, media type, caption used for naming, original caption, inherited-caption flag, file size, original filename.
- `build_message_package_workflow_request(text)`: parse direct ordinary message links and reject comment links.
- `scan_message_package(...)`: Telegram I/O wrapper to fetch messages and detect the package.
- `format_package_preview_message(...)`: pure formatter for Telegram preview text.
- Existing bot pending-confirmation state should store the prepared media messages, package summary, and selected naming context.

The existing comment workflow should gain size summary fields and preview rendering, without changing its confirmation semantics.

## Error Handling

- Invalid link: fall back to the existing help text.
- Private `/c/` parse failure: explain that the link cannot be parsed.
- Chat not found or access denied: report that the bot/client cannot access the chat.
- Message fetch failures inside the scan window: continue when possible, count failed ids, and show a partial-scan warning.
- No downloadable media: send a clear no-media message and do not create a pending confirmation.
- Confirmation token expired: reuse the current expired-token behavior.
- Download enqueue failure: keep the pending state when possible, matching the hardened comment workflow behavior.

## Testing

Unit tests should cover:

- `/c/<internal>/<message_id>` parsing into `-100<internal>` and start id.
- Rejection of comment links by the ordinary package workflow parser.
- Caption inheritance across media messages without captions.
- Album `media_group_id` caption sharing.
- Similar-caption continuation after cleaning numbering and whitespace.
- Different-caption boundary detection with next-package preview excluded from downloads.
- Size summary with all known sizes, some unknown sizes, and all unknown sizes.
- Preview message includes total size, sample sizes, largest file, inherited-caption count, and next-package preview.
- Bot direct-link routing sends ordinary message links into package preview, while comment links still go into comment workflow.
- Confirm callback starts prepared package download with the selected naming context.
- Existing comment workflow preview now includes size summary.

Focused integration tests should verify:

- A package scan can collect prepared messages and download only those messages.
- Existing `/download ... start end tag` behavior remains unchanged.
- Existing direct single-message download remains available for non-guided paths if the bot receives unsupported or ambiguous input.

## Success Criteria

- Pasting `https://t.me/c/1298283297/126711` no longer requires manually typing start id, end id, and tag.
- The bot detects one continuous media package and previews the next package boundary without downloading it.
- Media without captions inherit the correct package caption for preview and naming.
- The user can see estimated total size before confirming.
- Comment-link downloads also show estimated size before confirming.
- Existing tests pass with the project `.venv`.
