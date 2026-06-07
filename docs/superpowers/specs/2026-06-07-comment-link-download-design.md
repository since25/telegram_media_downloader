# Comment Link Media Download Design

## Goal

Improve the Telegram bot workflow for comment links such as:

```text
https://t.me/zhyseseb/422?comment=4978
```

The bot should turn this single pasted link into a guided workflow that scans the original post's comment thread, filters media comments, previews naming options, downloads selected media, uploads through the existing rclone flow, and deletes local files after successful upload when configured.

## Current Context

The project already supports:

- `/download <link> <start> <end> [filter] [tag]` style downloads.
- Direct `https://t.me...` link handling in `module/bot.py`.
- Comment range downloads via `get_discussion_message` and `download_comments`.
- `TaskNode.file_name_tag` for batch/manual naming tags.
- Caption-based filename enrichment in `media_downloader.py`.
- rclone upload and local deletion controlled by existing upload configuration.

The current pain point is that comment downloads require too much manual typing, for example:

```text
/download https://t.me/zhyseseb/422?comment= 4978 4998 lost
```

This also forces the user to decide naming upfront, even though title/caption quality varies per post.

## Proposed User Flow

1. User sends a comment link directly to the bot:

   ```text
   https://t.me/zhyseseb/422?comment=4978
   ```

2. Bot detects this as a comment-thread media workflow, not just a single-message download.

3. Bot parses:
   - Source chat/channel: `zhyseseb`.
   - Original post ID: `422`.
   - Starting comment ID: `4978`.

4. Bot resolves the linked discussion group with `get_discussion_message`.

5. Bot scans comments from the starting comment ID to the newest discoverable comment.

6. Bot filters out non-media comments and prepares a scan summary:
   - Comment range.
   - Total scanned comments.
   - Media comment count.
   - Media type breakdown: photo, video, document, audio, voice, etc.
   - Original post title/caption fallback.
   - Current upload and delete-after-upload behavior.

7. Bot generates naming previews from several media samples.

8. Bot asks the user to confirm a naming strategy before downloading.

9. User selects a naming strategy with an inline button.

10. Bot downloads media comments, uploads through existing rclone logic, and deletes local files after confirmed upload if `after_upload_file_delete` is enabled.

## Naming Preview Options

The bot should show 3-4 naming strategies with concrete examples before download. All examples must pass through deterministic filename cleanup before display.

### Option A: Post Title + Comment Author

```text
<post_title>/<comment_id> - <comment_author> - <original_file_name>.<ext>
```

Example:

```text
夏日合集 Vol.12/4978 - user123 - IMG_8821.jpg
```

Trade-off: readable when author data is available, but unstable for anonymous or missing users.

### Option B: Post Title + Caption Summary

```text
<post_title>/<comment_id> - <caption_summary> - <original_file_name>.<ext>
```

Example:

```text
夏日合集 Vol.12/4978 - 第三张是重点 - IMG_8821.jpg
```

Trade-off: best when captions are meaningful, noisy when captions are long or inconsistent.

### Option C: Channel + Post ID + Post Title

```text
<channel>/<post_id>-<post_title>/<comment_id> - <original_file_name>.<ext>
```

Example:

```text
zhyseseb/422-夏日合集 Vol.12/4978 - IMG_8821.jpg
```

Trade-off: most stable and traceable. This is the recommended default.

### Option D: Channel + Month + Caption Summary

```text
<channel>/<yyyy_mm>/<post_title>/<comment_id> - <caption_summary>.<ext>
```

Example:

```text
zhyseseb/2026_06/夏日合集 Vol.12/4978 - 第三张是重点.jpg
```

Trade-off: useful for chronological browsing, but depends more on caption quality.

## Confirmation UI

After scan and preview, the bot sends a message similar to:

```text
识别到评论媒体下载任务：
频道：zhyseseb
原帖：422
原帖标题：夏日合集 Vol.12
评论范围：4978 → 最新
扫描评论：128
媒体评论：37
类型：photo 20 / video 12 / document 5
上传：rclone enabled
上传后删除本地：enabled

请选择本次命名方案：
```

Inline buttons:

- `采用推荐C`
- `采用A`
- `采用B`
- `采用D`
- `仅统计`
- `取消`

The bot must not start downloading before the user confirms a naming option.

## Filename Cleanup Rules

Filename cleanup is required for every preview and final path.

Rules:

- Remove or replace filesystem-illegal characters using the existing `validate_title` style behavior.
- Collapse excessive whitespace.
- Trim leading/trailing separators.
- Limit long title/caption segments before composing the final filename.
- Preserve file extension where possible.
- Fall back deterministically when fields are empty.

Fallbacks:

- Empty post title: `post-<post_id>`.
- Empty caption: omit the caption segment or use `no-caption` only when the selected template requires it.
- Empty original filename: `comment-<comment_id>-<media_type>.<ext>`.
- Empty author: `anonymous`.
- Duplicate final path: append a short sequence or reuse the existing copy-name behavior.

## Comment Counting and Media Filtering

The bot should distinguish three counts:

1. **Approximate total comments** if Telegram exposes reply/comment count metadata on the original post.
2. **Scanned comments** discovered by walking the discussion group history or probing message IDs.
3. **Media comments** after filtering comments that contain supported media.

The user-facing summary should prefer accurate scanned/media counts. Approximate totals can be labeled as approximate if used.

Media filtering should include the media types already supported by the downloader and skip pure text, stickers, unsupported service messages, deleted/empty messages, and inaccessible messages.

## Error Handling

- If the link cannot be parsed, show the existing download help plus a comment-link example.
- If `get_discussion_message` fails, explain that the post may not have an accessible discussion thread.
- If scanning hits rate limits or API errors, show partial scan results and offer cancel/retry.
- If no media comments are found, show a clear “no media comments” result and do not create a download task.
- If rclone upload fails, keep the local file and report the failed upload.
- If upload succeeds but delete fails, report the local path that still needs cleanup.

## Scope for First Implementation

Included:

- Direct comment-link guided workflow.
- Scan summary.
- Media-only filtering.
- A/B/C/D naming previews.
- Inline confirmation before download.
- Deterministic filename cleanup and fallbacks.
- Reuse of existing rclone upload/delete behavior.

Excluded from first implementation:

- AI-based title rewriting.
- Persistent per-channel naming rules.
- Fully custom user-defined filename templates.
- Automatic download without confirmation.

These can be added later once the guided flow is stable.

## Testing Strategy

Add focused tests for parsing and planning logic before touching Telegram network behavior:

- Parse `https://t.me/zhyseseb/422?comment=4978` into source chat, post ID, and starting comment ID.
- Build scan summaries from mocked comments.
- Filter media versus non-media comments.
- Generate A/B/C/D preview paths with missing title, caption, author, and original filename.
- Confirm illegal character cleanup and length handling.
- Ensure download execution is not started until a naming option is selected.

Integration testing can use mocked Pyrogram client methods for `get_discussion_message` and `get_messages` to avoid live Telegram dependency.
