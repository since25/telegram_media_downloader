"""Tests for Telegram comment-link media workflow planning."""
import datetime
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_common import MockDocument, MockMessage, MockPhoto, MockUser, MockVideo

from module.comment_workflow import (
    COMMENT_WORKFLOW_PREFIX,
    NamingStrategy,
    build_callback_data,
    build_comment_workflow_request,
    build_naming_previews,
    build_workflow_token,
    clean_segment,
    format_preview_message,
    filter_media_comments,
    parse_callback_data,
    summarize_comments,
)


class FakeDiscussionClient:
    def __init__(self, comments, batch_failures=None, individual_failures=None):
        self.comments = {comment.id: comment for comment in comments}
        self.batch_failures = set(batch_failures or [])
        self.individual_failures = set(individual_failures or [])
        self.discussion_message = MockMessage(
            id=1, chat_id=-200, chat_title="Discussion"
        )

    async def get_discussion_message(self, chat_id, message_id):
        self.requested_chat_id = chat_id
        self.requested_message_id = message_id
        return self.discussion_message

    async def get_messages(self, chat_id, message_ids):
        if isinstance(message_ids, list):
            if any(message_id in self.batch_failures for message_id in message_ids):
                raise RuntimeError("batch failure")
            return [self.comments.get(message_id) for message_id in message_ids]
        if message_ids in self.individual_failures:
            raise RuntimeError("individual failure")
        return self.comments.get(message_ids)


class CommentWorkflowTestCase(unittest.TestCase):
    def test_build_comment_workflow_request_from_comment_link(self):
        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )

        self.assertEqual(request.source_chat, "zhyseseb")
        self.assertEqual(request.post_id, 422)
        self.assertEqual(request.start_comment_id, 4978)

    def test_build_comment_workflow_request_rejects_non_comment_link(self):
        self.assertIsNone(
            build_comment_workflow_request("https://t.me/zhyseseb/422")
        )

    def test_build_comment_workflow_request_does_not_reconstruct_post_id(self):
        with patch("module.comment_workflow.extract_info_from_link") as parser:
            parser.return_value.group_id = "zhyseseb"
            parser.return_value.post_id = None
            parser.return_value.comment_id = 4978

            self.assertIsNone(
                build_comment_workflow_request("https://t.me/zhyseseb/422?comment=4978")
            )

    def test_build_comment_workflow_request_rejects_empty_comment_id(self):
        self.assertIsNone(
            build_comment_workflow_request("https://t.me/zhyseseb/422?comment=")
        )

    def test_filter_media_comments_skips_text_and_empty_messages(self):
        comments = [
            MockMessage(id=1, text="hello"),
            MockMessage(id=2, media="photo", photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="p1")),
            MockMessage(id=3, empty=True),
            MockMessage(id=4, media="video", video=MockVideo(file_name="clip.mp4", mime_type="video/mp4")),
        ]

        media_comments = filter_media_comments(comments)

        self.assertEqual([comment.id for comment in media_comments], [2, 4])

    def test_filter_media_comments_supports_enum_like_media_value(self):
        comments = [
            MockMessage(id=1, media=SimpleNamespace(value="photo"), photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="p1")),
            MockMessage(id=2, media=SimpleNamespace(value="photo")),
            MockMessage(id=3, media=SimpleNamespace(value="sticker")),
        ]

        media_comments = filter_media_comments(comments)

        self.assertEqual([comment.id for comment in media_comments], [1])

    def test_summarize_comments_counts_media_types(self):
        comments = [
            MockMessage(id=4978, media="photo", photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="p1")),
            MockMessage(id=4979, text="skip"),
            MockMessage(id=4980, media="video", video=MockVideo(file_name="clip.mp4", mime_type="video/mp4")),
            MockMessage(id=4981, media="document", document=MockDocument(file_name="book.pdf", mime_type="application/pdf")),
        ]

        summary = summarize_comments(comments)

        self.assertEqual(summary.scanned_count, 4)
        self.assertEqual(summary.media_count, 3)
        self.assertEqual(summary.media_type_counts, {"photo": 1, "video": 1, "document": 1})
        self.assertEqual(summary.first_comment_id, 4978)
        self.assertEqual(summary.last_comment_id, 4981)

    def test_build_callback_data_keeps_payload_short(self):
        callback_data = build_callback_data("abc123", NamingStrategy.RECOMMENDED)

        self.assertEqual(callback_data, f"{COMMENT_WORKFLOW_PREFIX}:abc123:C")
        self.assertLessEqual(len(callback_data.encode("utf-8")), 64)

    def test_build_workflow_token_is_deterministic_and_short(self):
        url = "https://t.me/zhyseseb/422?comment=4978"
        user_id = MockUser(id=123).id
        token = build_workflow_token(url, user_id)

        self.assertEqual(
            token,
            hashlib.sha1(f"{user_id}:{url}".encode("utf-8")).hexdigest()[:12],
        )
        self.assertEqual(len(token), 12)

    def test_parse_callback_data_success_and_failures(self):
        self.assertEqual(
            parse_callback_data("cw:abc123:A"),
            ("abc123", NamingStrategy.AUTHOR),
        )
        self.assertIsNone(parse_callback_data("xx:abc123:A"))
        self.assertIsNone(parse_callback_data("cw:abc123:Z"))
        self.assertIsNone(parse_callback_data("cw::A"))
        self.assertIsNone(parse_callback_data("cw:abc123"))

    def test_clean_segment_cleans_and_falls_back(self):
        self.assertEqual(clean_segment("  hello \n world  ", "fallback"), "hello world")
        self.assertEqual(clean_segment("bad/name: title", "fallback"), "bad_name_ title")
        self.assertEqual(clean_segment(" / ", "fallback"), "fallback")
        self.assertEqual(clean_segment(" / ", " bad/name "), "bad_name")
        self.assertEqual(clean_segment("123456789", "fallback", max_len=5), "12345")

    def test_format_preview_message_contains_summary_and_examples(self):
        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
                date=datetime.datetime(2026, 6, 7),
            )
        ]
        summary = summarize_comments(comments)
        previews = build_naming_previews(
            comments,
            channel="zhyseseb",
            post_id=422,
            post_title="夏日合集",
            sample_size=1,
        )

        message = format_preview_message(
            channel="zhyseseb",
            post_id=422,
            post_title="夏日合集",
            start_comment_id=4978,
            summary=summary,
            previews=previews,
            upload_enabled=True,
            delete_after_upload=False,
        )

        self.assertIn("频道：zhyseseb", message)
        self.assertIn("原帖：422", message)
        self.assertIn("媒体评论：1", message)
        self.assertIn("上传：enabled", message)
        self.assertIn("采用推荐C", message)
        self.assertIn("zhyseseb/422-夏日合集/4978 - clip.mp4", message)

    def test_build_naming_previews_generates_four_clean_options(self):
        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
                caption="第三张是重点，后面还有说明",
                from_user=MockUser(username="user/name"),
                date=datetime.datetime(2026, 6, 7),
            )
        ]

        previews = build_naming_previews(
            comments,
            channel="zhyseseb",
            post_id=422,
            post_title="夏日/合集 Vol.12",
            sample_size=1,
        )

        self.assertEqual(
            [preview.strategy.value for preview in previews],
            ["C", "A", "B", "D"],
        )
        self.assertEqual(
            [preview.examples[0] for preview in previews],
            [
                "zhyseseb/422-夏日_合集 Vol.12/4978 - bad_name_.mp4",
                "夏日_合集 Vol.12/4978 - user_name - bad_name_.mp4",
                "夏日_合集 Vol.12/4978 - 第三张是重点，后面还有说明 - bad_name_.mp4",
                "zhyseseb/2026_06/夏日_合集 Vol.12/4978 - 第三张是重点，后面还有说明.mp4",
            ],
        )

    def test_build_naming_previews_uses_fallbacks(self):
        comments = [
            MockMessage(
                id=5000,
                media="photo",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="photo-id",
                ),
                date=datetime.datetime(2026, 6, 7),
            )
        ]

        previews = build_naming_previews(
            comments,
            channel="zhyseseb",
            post_id=422,
            post_title="",
            sample_size=1,
        )

        examples_by_strategy = {
            preview.strategy.value: preview.examples[0] for preview in previews
        }
        self.assertEqual(
            examples_by_strategy["C"],
            "zhyseseb/422-post-422/5000 - comment-5000-photo.jpg",
        )
        self.assertEqual(
            examples_by_strategy["D"],
            "zhyseseb/2026_06/post-422/5000 - no-caption.jpg",
        )

    def test_build_naming_previews_falls_back_for_extension_only_filename(self):
        comments = [
            MockMessage(
                id=1,
                media="video",
                video=MockVideo(file_name="?.mp4", mime_type="video/mp4"),
                date=datetime.datetime(2026, 6, 7),
            )
        ]

        previews = build_naming_previews(
            comments,
            channel="zhyseseb",
            post_id=422,
            post_title="post title",
            sample_size=1,
        )

        self.assertEqual(
            previews[0].examples[0],
            "zhyseseb/422-post title/1 - comment-1-video.mp4",
        )

    def test_build_naming_previews_keeps_options_for_non_media_comments(self):
        comments = [
            MockMessage(id=1, text="hello"),
            MockMessage(id=2, empty=True),
        ]

        previews = build_naming_previews(
            comments,
            channel="zhyseseb",
            post_id=422,
            post_title="post title",
            sample_size=1,
        )

        self.assertEqual(
            [preview.strategy.value for preview in previews],
            ["C", "A", "B", "D"],
        )
        self.assertEqual([preview.examples for preview in previews], [[], [], [], []])


class CommentScanExecutionTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_scan_comment_range_returns_comments_and_discussion_chat(self):
        from media_downloader import scan_comment_range

        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
            ),
            MockMessage(id=4979, text="skip"),
        ]
        client = FakeDiscussionClient(comments)

        scan_result = await scan_comment_range(
            client=client,
            chat_id=-1001,
            base_message_id=422,
            start_comment_id=4978,
            end_comment_id=4979,
        )

        self.assertEqual(scan_result.discussion_group_id, -200)
        self.assertEqual([comment.id for comment in scan_result.comments], [4978, 4979])
        self.assertEqual(scan_result.failed_comment_ids, [])

    async def test_scan_comment_range_returns_failed_ids_from_individual_retries(self):
        from media_downloader import scan_comment_range

        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
            ),
            MockMessage(id=4979, text="skip"),
        ]
        client = FakeDiscussionClient(
            comments,
            batch_failures={4978},
            individual_failures={4979},
        )

        scan_result = await scan_comment_range(
            client=client,
            chat_id=-1001,
            base_message_id=422,
            start_comment_id=4978,
            end_comment_id=4979,
        )

        self.assertEqual(scan_result.discussion_group_id, -200)
        self.assertEqual([comment.id for comment in scan_result.comments], [4978])
        self.assertEqual(scan_result.failed_comment_ids, [4979])

    async def test_download_comments_counts_scan_failures_in_progress_totals(self):
        from module.app import TaskNode
        from media_downloader import CommentScanResult, download_comments

        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip-a.mp4", mime_type="video/mp4"),
            ),
            MockMessage(
                id=4979,
                media="video",
                video=MockVideo(file_name="clip-b.mp4", mime_type="video/mp4"),
            ),
        ]
        node = TaskNode(chat_id=-1001, bot=None, task_id=7)
        node.is_running = True
        report_calls = []

        async def fake_scan_comment_range(*args, **kwargs):
            return CommentScanResult(-200, comments, [4980])

        async def fake_add_download_task(comment, task_node):
            task_node.total_task += 1
            task_node.total_download_task += 1
            task_node.success_download_task += 1
            return True

        async def fake_report_bot_status(bot, task_node):
            report_calls.append(
                (
                    task_node.success_download_task,
                    task_node.failed_download_task,
                    task_node.total_download_task,
                )
            )

        async def fake_sleep(seconds):
            raise AssertionError("download_comments should not sleep after all expected tasks finish")

        with patch("media_downloader.scan_comment_range", new=fake_scan_comment_range), patch(
            "media_downloader.add_download_task", new=fake_add_download_task
        ), patch(
            "module.pyrogram_extension.report_bot_status", new=fake_report_bot_status
        ), patch(
            "module.download_stat.remove_active_task_node"
        ), patch(
            "media_downloader.asyncio.sleep", new=fake_sleep
        ):
            await download_comments(
                client=object(),
                chat_id=-1001,
                base_message_id=422,
                start_comment_id=4978,
                end_comment_id=4980,
                download_filter="",
                node=node,
            )

        self.assertEqual(node.failed_download_task, 1)
        self.assertEqual(node.success_download_task, 2)
        self.assertEqual(node.total_download_task, 3)
        self.assertEqual(node.total_task, 3)
        self.assertTrue(report_calls)
        self.assertEqual(report_calls[-1], (2, 1, 3))

    async def test_download_comments_counts_false_enqueue_as_failed_task(self):
        from module.app import TaskNode
        from media_downloader import CommentScanResult, download_comments

        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip-a.mp4", mime_type="video/mp4"),
            )
        ]
        node = TaskNode(chat_id=-1001, bot=None, task_id=8)
        node.is_running = True
        report_calls = []

        async def fake_scan_comment_range(*args, **kwargs):
            return CommentScanResult(-200, comments, [])

        async def fake_add_download_task(comment, task_node):
            return False

        async def fake_report_bot_status(bot, task_node):
            report_calls.append(
                (
                    task_node.success_download_task,
                    task_node.failed_download_task,
                    task_node.total_download_task,
                )
            )

        async def fake_sleep(seconds):
            raise AssertionError("download_comments should not sleep after enqueue failure")

        with patch("media_downloader.scan_comment_range", new=fake_scan_comment_range), patch(
            "media_downloader.add_download_task", new=fake_add_download_task
        ), patch(
            "module.pyrogram_extension.report_bot_status", new=fake_report_bot_status
        ), patch(
            "module.download_stat.remove_active_task_node"
        ), patch(
            "media_downloader.asyncio.sleep", new=fake_sleep
        ):
            await download_comments(
                client=object(),
                chat_id=-1001,
                base_message_id=422,
                start_comment_id=4978,
                end_comment_id=4978,
                download_filter="",
                node=node,
            )

        self.assertEqual(node.failed_download_task, 1)
        self.assertEqual(node.success_download_task, 0)
        self.assertEqual(node.total_download_task, 1)
        self.assertEqual(node.total_task, 1)
        self.assertTrue(report_calls)
        self.assertEqual(report_calls[-1], (0, 1, 1))


class BotPreviewWorkflowTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_preview_uses_latest_discussion_history_message_for_scan_end(self):
        from module import bot as bot_module

        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )
        source_entity = SimpleNamespace(
            id=-1001, username="zhyseseb", title="Channel Title"
        )
        base_message = MockMessage(id=422, text="夏日合集")
        discussion_message = MockMessage(
            id=5, chat_id=-200, chat_title="Discussion"
        )
        scanned_comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
            )
        ]
        captured_scan = {}

        class FakeUserClient:
            async def get_chat(self, chat_id):
                self.requested_chat_id = chat_id
                return source_entity

            async def get_messages(self, chat_id, message_id):
                self.requested_message = (chat_id, message_id)
                return base_message

            async def get_discussion_message(self, chat_id, message_id):
                self.requested_discussion = (chat_id, message_id)
                return discussion_message

        class FakeBotClient:
            def __init__(self):
                self.sent_messages = []

            async def send_message(self, chat_id, text, **kwargs):
                self.sent_messages.append((chat_id, text, kwargs))

        async def fake_get_chat_history_v2(client, chat_id, limit=0, reverse=False):
            self.assertEqual(chat_id, -200)
            self.assertEqual(limit, 1)
            self.assertFalse(reverse)
            yield MockMessage(id=4999)

        async def fake_scan_comment_range(
            client, chat_id, base_message_id, start_comment_id, end_comment_id
        ):
            captured_scan.update(
                {
                    "chat_id": chat_id,
                    "base_message_id": base_message_id,
                    "start_comment_id": start_comment_id,
                    "end_comment_id": end_comment_id,
                }
            )
            return SimpleNamespace(comments=scanned_comments)

        old_client = bot_module._bot.client
        old_app = bot_module._bot.app
        old_pending = bot_module._bot.pending_comment_workflows
        bot_client = FakeBotClient()
        try:
            bot_module._bot.client = FakeUserClient()
            bot_module._bot.app = SimpleNamespace(
                cloud_drive_config=SimpleNamespace(
                    enable_upload_file=True, after_upload_file_delete=False
                )
            )
            bot_module._bot.pending_comment_workflows = {}
            message = MockMessage(
                id=88,
                text="https://t.me/zhyseseb/422?comment=4978",
                from_user=MockUser(id=123),
            )

            with patch(
                "module.bot.get_chat_history_v2", new=fake_get_chat_history_v2
            ), patch("media_downloader.scan_comment_range", new=fake_scan_comment_range):
                await bot_module.preview_comment_workflow(bot_client, message, request)

            self.assertEqual(
                captured_scan,
                {
                    "chat_id": -1001,
                    "base_message_id": 422,
                    "start_comment_id": 4978,
                    "end_comment_id": 4999,
                },
            )
            self.assertEqual(len(bot_module._bot.pending_comment_workflows), 1)
            self.assertEqual(len(bot_client.sent_messages), 1)
            sent_text = bot_client.sent_messages[0][1]
            sent_kwargs = bot_client.sent_messages[0][2]
            self.assertIn("采用推荐C", sent_text)
            self.assertIn("reply_markup", sent_kwargs)
        finally:
            bot_module._bot.client = old_client
            bot_module._bot.app = old_app
            bot_module._bot.pending_comment_workflows = old_pending


if __name__ == "__main__":
    unittest.main()
