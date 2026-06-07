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
    build_size_summary,
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

    def test_build_message_package_workflow_request_from_private_link(self):
        from module.comment_workflow import build_message_package_workflow_request

        request = build_message_package_workflow_request(
            "https://t.me/c/1298283297/126711"
        )

        self.assertEqual(request.source_chat, -1001298283297)
        self.assertEqual(request.start_message_id, 126711)
        self.assertEqual(request.url, "https://t.me/c/1298283297/126711")

    def test_build_message_package_workflow_request_rejects_comment_link(self):
        from module.comment_workflow import build_message_package_workflow_request

        self.assertIsNone(
            build_message_package_workflow_request(
                "https://t.me/zhyseseb/422?comment=4978"
            )
        )

    def test_build_message_package_workflow_request_rejects_empty_comment_query(self):
        from module.comment_workflow import build_message_package_workflow_request

        self.assertIsNone(
            build_message_package_workflow_request(
                "https://t.me/zhyseseb/422?comment="
            )
        )

    def test_build_message_package_workflow_request_rejects_empty_comment_query_for_private_link(self):
        from module.comment_workflow import build_message_package_workflow_request

        self.assertIsNone(
            build_message_package_workflow_request(
                "https://t.me/c/1298283297/126711?comment="
            )
        )

    def test_build_message_package_workflow_request_accepts_comment_substring_in_path(self):
        from module.comment_workflow import build_message_package_workflow_request

        request = build_message_package_workflow_request(
            "https://t.me/commentaryhub/422"
        )

        self.assertEqual(request.source_chat, "commentaryhub")
        self.assertEqual(request.start_message_id, 422)

    def test_build_message_package_workflow_request_rejects_malformed_private_group_id(self):
        from module.comment_workflow import build_message_package_workflow_request

        self.assertIsNone(
            build_message_package_workflow_request(
                "https://t.me/c/notanint/126711"
            )
        )

    def test_build_message_package_workflow_request_rejects_malformed_private_message_id(self):
        from module.comment_workflow import build_message_package_workflow_request

        self.assertIsNone(
            build_message_package_workflow_request(
                "https://t.me/c/1298283297/notanint"
            )
        )

    def test_build_size_summary_counts_known_unknown_and_largest(self):
        from module.comment_workflow import build_size_summary, format_size_summary

        messages = [
            MockMessage(
                id=126711,
                media="video",
                video=MockVideo(
                    file_name="a.mp4",
                    file_size=421 * 1024 * 1024,
                    mime_type="video/mp4",
                ),
            ),
            MockMessage(
                id=126712,
                media="video",
                video=MockVideo(
                    file_name="b.mp4",
                    file_size=388 * 1024 * 1024,
                    mime_type="video/mp4",
                ),
            ),
            MockMessage(
                id=126713,
                media="photo",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p1",
                ),
            ),
        ]
        delattr(messages[2].photo, "file_size")

        summary = build_size_summary(messages)

        self.assertEqual(summary.known_total_size, 809 * 1024 * 1024)
        self.assertEqual(summary.unknown_size_count, 1)
        self.assertEqual(summary.largest.message_id, 126711)
        self.assertEqual(summary.samples[0].message_id, 126711)
        self.assertIn("809.0MB", format_size_summary(summary))
        self.assertIn("1 个未知大小文件", format_size_summary(summary))

    def test_plan_message_package_inherits_caption_and_excludes_next_package(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=126711,
                media="video",
                caption="某某课程 第01章 01/40",
                video=MockVideo(
                    file_name="001.mp4", mime_type="video/mp4", file_size=100
                ),
            ),
            MockMessage(
                id=126712,
                media="video",
                video=MockVideo(
                    file_name="002.mp4", mime_type="video/mp4", file_size=200
                ),
            ),
            MockMessage(
                id=126713,
                media="video",
                caption="某某课程 第01章 02/40",
                video=MockVideo(
                    file_name="003.mp4", mime_type="video/mp4", file_size=300
                ),
            ),
            MockMessage(
                id=126714,
                media="video",
                caption="某某课程 第02章",
                video=MockVideo(
                    file_name="004.mp4", mime_type="video/mp4", file_size=400
                ),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=126711)

        self.assertEqual([item.message.id for item in plan.items], [126711, 126712, 126713])
        self.assertEqual(plan.package_title, "某某课程 第01章 01_40")
        self.assertEqual(plan.inherited_caption_count, 1)
        self.assertEqual(plan.next_package_message.id, 126714)
        self.assertEqual(plan.summary.media_count, 3)
        self.assertEqual(plan.size_summary.known_total_size, 600)

    def test_plan_message_package_shares_album_caption_by_media_group(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=10,
                media="photo",
                media_group_id="album1",
                caption="相册标题 EP01",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p10",
                    file_size=10,
                ),
            ),
            MockMessage(
                id=11,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p11",
                    file_size=11,
                ),
            ),
            MockMessage(
                id=12,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p12",
                    file_size=12,
                ),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=10)

        self.assertEqual(
            [item.caption_for_naming for item in plan.items],
            ["相册标题 EP01", "相册标题 EP01", "相册标题 EP01"],
        )
        self.assertEqual(plan.inherited_caption_count, 2)

    def test_plan_message_package_warns_when_scan_reaches_exact_limit(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=20,
                media="video",
                caption="某某课程 第01章 01/40",
                video=MockVideo(
                    file_name="001.mp4", mime_type="video/mp4", file_size=100
                ),
            ),
            MockMessage(
                id=21,
                media="video",
                video=MockVideo(
                    file_name="002.mp4", mime_type="video/mp4", file_size=200
                ),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=20, max_scan_count=2)

        self.assertEqual([item.message.id for item in plan.items], [20, 21])
        self.assertIsNone(plan.next_package_message)
        self.assertEqual(plan.scan_warning, "未发现下一包边界，已达到扫描上限 2 条。")

    def test_build_package_naming_previews_and_preview_message(self):
        from module.comment_workflow import (
            build_package_naming_previews,
            format_package_preview_message,
            plan_message_package,
        )

        messages = [
            MockMessage(
                id=126711,
                media="video",
                caption="某某课程 第01章",
                video=MockVideo(
                    file_name="001/bad?.mp4",
                    mime_type="video/mp4",
                    file_size=421 * 1024 * 1024,
                ),
            ),
            MockMessage(
                id=126712,
                media="video",
                video=MockVideo(
                    file_name="002.mp4",
                    mime_type="video/mp4",
                    file_size=388 * 1024 * 1024,
                ),
            ),
            MockMessage(
                id=126713,
                media="video",
                caption="某某课程 第02章",
                video=MockVideo(
                    file_name="003.mp4",
                    mime_type="video/mp4",
                    file_size=402 * 1024 * 1024,
                ),
            ),
        ]
        package_plan = plan_message_package(messages, start_message_id=126711)
        previews = build_package_naming_previews(
            package_plan.items,
            channel="私密频道",
            start_message_id=126711,
            package_title=package_plan.package_title,
        )
        package_plan.scan_warning = "未发现下一包边界，已达到扫描上限 2 条。"
        preview_text = format_package_preview_message(
            channel="私密频道",
            start_message_id=126711,
            package_plan=package_plan,
            previews=previews,
            upload_enabled=True,
            delete_after_upload=True,
        )

        self.assertIn("识别到连续资源包", preview_text)
        self.assertIn("标题：某某课程 第01章", preview_text)
        self.assertIn("范围：126711 - 126712", preview_text)
        self.assertIn("媒体：2 个（video 2 个）", preview_text)
        self.assertIn("预计大小：809.0MB", preview_text)
        self.assertIn("最大文件：126711 video 421.0MB", preview_text)
        self.assertIn("大小示例：", preview_text)
        self.assertIn("- 126711 video 421.0MB", preview_text)
        self.assertIn("继承 caption：1 个", preview_text)
        self.assertIn("rclone上传：开启", preview_text)
        self.assertIn("上传后删除本地：开启", preview_text)
        self.assertIn("提示：未发现下一包边界，已达到扫描上限 2 条。", preview_text)
        self.assertIn("下一包起点预览：", preview_text)
        self.assertIn("126713 - 某某课程 第02章", preview_text)
        self.assertIn("不会纳入本次下载。", preview_text)
        self.assertIn("推荐C：频道/起始ID-标题/消息ID - 原文件名", preview_text)
        self.assertIn(
            "推荐C：频道/起始ID-标题/消息ID - 原文件名（采用推荐C）",
            preview_text,
        )
        self.assertIn("A：标题/消息ID - 作者 - 原文件名", preview_text)
        self.assertIn("B：标题/消息ID - caption摘要 - 原文件名", preview_text)
        self.assertIn("D：频道/年月/标题/消息ID - caption摘要", preview_text)
        self.assertIn(
            "私密频道/126711-某某课程 第01章/126711 - 001_bad_.mp4",
            preview_text,
        )

    def test_format_package_preview_inherits_next_album_caption(self):
        from module.comment_workflow import (
            build_package_naming_previews,
            format_package_preview_message,
            plan_message_package,
        )

        messages = [
            MockMessage(
                id=10,
                media="photo",
                media_group_id="album1",
                caption="当前相册 EP01",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p10",
                    file_size=10,
                ),
            ),
            MockMessage(
                id=11,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p11",
                    file_size=11,
                ),
            ),
            MockMessage(
                id=20,
                media="photo",
                media_group_id="album2",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p20",
                    file_size=20,
                ),
            ),
            MockMessage(
                id=21,
                media="photo",
                media_group_id="album2",
                caption="下一相册 EP02",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p21",
                    file_size=21,
                ),
            ),
        ]

        package_plan = plan_message_package(messages, start_message_id=10)
        previews = build_package_naming_previews(
            package_plan.items,
            channel="私密频道",
            start_message_id=10,
            package_title=package_plan.package_title,
        )

        preview_text = format_package_preview_message(
            channel="私密频道",
            start_message_id=10,
            package_plan=package_plan,
            previews=previews,
            upload_enabled=True,
            delete_after_upload=False,
        )

        self.assertEqual([item.message.id for item in package_plan.items], [10, 11])
        self.assertEqual(package_plan.next_package_message.id, 20)
        self.assertIn("20 - 下一相册 EP02", preview_text)
        self.assertNotIn("20 - message-20", preview_text)

    def test_package_naming_previews_use_extension_fallbacks(self):
        from module.comment_workflow import (
            build_package_naming_previews,
            media_file_name_for_message,
            plan_message_package,
        )

        messages = [
            MockMessage(
                id=200,
                media="video",
                caption="资源包",
                video=MockVideo(mime_type="video/mp4", file_size=200),
            ),
            MockMessage(
                id=201,
                media="photo",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p201",
                    file_size=201,
                ),
            ),
        ]

        package_plan = plan_message_package(messages, start_message_id=200)
        previews = build_package_naming_previews(
            package_plan.items,
            channel="私密频道",
            start_message_id=200,
            package_title=package_plan.package_title,
        )

        self.assertEqual(
            media_file_name_for_message(messages[0]), "message-200-video.mp4"
        )
        self.assertEqual(
            media_file_name_for_message(messages[1]), "message-201-photo.jpg"
        )
        self.assertEqual(
            previews[0].examples,
            [
                "私密频道/200-资源包/200 - message-200-video.mp4",
                "私密频道/200-资源包/201 - message-201-photo.jpg",
            ],
        )

    def test_plan_message_package_shares_album_caption_when_caption_appears_later(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=10,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p10",
                    file_size=10,
                ),
            ),
            MockMessage(
                id=11,
                media="photo",
                media_group_id="album1",
                caption="相册标题 EP01",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p11",
                    file_size=11,
                ),
            ),
            MockMessage(
                id=12,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(
                    date=datetime.datetime(2026, 6, 7),
                    file_unique_id="p12",
                    file_size=12,
                ),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=10)

        self.assertEqual(
            [item.caption_for_naming for item in plan.items],
            ["相册标题 EP01", "相册标题 EP01", "相册标题 EP01"],
        )
        self.assertEqual([item.inherited_caption for item in plan.items], [True, False, True])
        self.assertEqual(plan.inherited_caption_count, 2)

    def test_plan_message_package_treats_chinese_episode_markers_as_same_package(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=30,
                media="video",
                caption="剧名 第1集",
                video=MockVideo(
                    file_name="001.mp4", mime_type="video/mp4", file_size=100
                ),
            ),
            MockMessage(
                id=31,
                media="video",
                caption="剧名 第2集",
                video=MockVideo(
                    file_name="002.mp4", mime_type="video/mp4", file_size=200
                ),
            ),
            MockMessage(
                id=32,
                media="video",
                caption="剧名 第3集",
                video=MockVideo(
                    file_name="003.mp4", mime_type="video/mp4", file_size=300
                ),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=30)

        self.assertEqual([item.message.id for item in plan.items], [30, 31, 32])
        self.assertIsNone(plan.next_package_message)
        self.assertEqual(plan.inherited_caption_count, 0)

    def test_plan_message_package_backfills_leading_captionless_media(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=100,
                media="video",
                video=MockVideo(
                    file_name="001.mp4", mime_type="video/mp4", file_size=100
                ),
            ),
            MockMessage(
                id=101,
                media="video",
                caption="课程 第01章 01/40",
                video=MockVideo(
                    file_name="002.mp4", mime_type="video/mp4", file_size=200
                ),
            ),
            MockMessage(
                id=102,
                media="video",
                video=MockVideo(
                    file_name="003.mp4", mime_type="video/mp4", file_size=300
                ),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=100)

        self.assertEqual(plan.package_title, "课程 第01章 01_40")
        self.assertEqual(
            [item.caption_for_naming for item in plan.items],
            ["课程 第01章 01_40", "课程 第01章 01_40", "课程 第01章 01_40"],
        )
        self.assertEqual([item.inherited_caption for item in plan.items], [True, False, True])
        self.assertEqual(plan.inherited_caption_count, 2)

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
                video=MockVideo(
                    file_name="clip.mp4",
                    file_size=123 * 1024 * 1024,
                    mime_type="video/mp4",
                ),
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
            size_summary=build_size_summary(comments),
            upload_enabled=True,
            delete_after_upload=True,
        )

        self.assertIn("频道：zhyseseb", message)
        self.assertIn("原帖：422", message)
        self.assertIn("原帖标题：夏日合集", message)
        self.assertIn("评论范围：4978 → 4978", message)
        self.assertIn("扫描评论：1", message)
        self.assertIn("媒体评论：1", message)
        self.assertIn("类型：video 1", message)
        self.assertIn("预计大小：", message)
        self.assertIn("最大文件：", message)
        self.assertIn("大小示例：", message)
        self.assertIn("上传：enabled", message)
        self.assertIn("上传后删除本地：enabled", message)
        self.assertIn("采用推荐C", message)
        self.assertIn("zhyseseb/422-夏日合集/4978 - clip.mp4", message)

    def test_format_preview_message_includes_scan_warnings(self):
        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(
                    file_name="clip.mp4",
                    file_size=123 * 1024 * 1024,
                    mime_type="video/mp4",
                ),
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
            size_summary=build_size_summary(comments),
            upload_enabled=True,
            delete_after_upload=True,
            failed_comment_ids=[4980, 4981],
            scan_warning="最新评论定位失败，预览范围可能不完整。",
        )

        self.assertIn("扫描警告：最新评论定位失败，预览范围可能不完整。", message)
        self.assertIn("扫描失败评论：2", message)

    def test_format_preview_message_preserves_legacy_optional_positions(self):
        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(
                    file_name="clip.mp4",
                    file_size=123 * 1024 * 1024,
                    mime_type="video/mp4",
                ),
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
            "zhyseseb",
            422,
            "夏日合集",
            4978,
            summary,
            previews,
            True,
            True,
            [4980, 4981],
            "最新评论定位失败，预览范围可能不完整。",
        )

        self.assertIn("扫描警告：最新评论定位失败，预览范围可能不完整。", message)
        self.assertIn("扫描失败评论：2", message)
        self.assertNotIn("预计大小：", message)

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

    async def test_download_prepared_comments_uses_module_app_for_filtering(self):
        from module.app import TaskNode
        from media_downloader import download_prepared_comments
        import media_downloader

        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip-a.mp4", mime_type="video/mp4"),
                caption="keep",
            ),
            MockMessage(
                id=4979,
                media="video",
                video=MockVideo(file_name="clip-b.mp4", mime_type="video/mp4"),
                caption="drop",
            ),
        ]
        node = TaskNode(chat_id=-1001, bot=None, task_id=9)
        node.is_running = True
        queued_ids = []

        def fake_exec_filter(config, meta_data):
            return meta_data.caption == "keep"

        def fake_set_meta_data(meta_data, comment, caption):
            meta_data.caption = caption

        async def fake_add_download_task(comment, task_node):
            queued_ids.append(comment.id)
            task_node.total_task += 1
            task_node.total_download_task += 1
            task_node.success_download_task += 1
            return True

        async def fake_report_bot_status(bot, task_node):
            return None

        async def fake_sleep(seconds):
            raise AssertionError("download_prepared_comments should not wait after filtered success")

        with patch.object(
            media_downloader.app, "exec_filter", new=fake_exec_filter
        ), patch(
            "media_downloader.add_download_task", new=fake_add_download_task
        ), patch(
            "module.pyrogram_extension.set_meta_data", new=fake_set_meta_data
        ), patch(
            "module.pyrogram_extension.report_bot_status", new=fake_report_bot_status
        ), patch(
            "module.download_stat.remove_active_task_node"
        ), patch(
            "media_downloader.asyncio.sleep", new=fake_sleep
        ):
            await download_prepared_comments(
                comments,
                download_filter="caption == keep",
                node=node,
            )

        self.assertEqual(queued_ids, [4978])
        self.assertEqual(node.success_download_task, 1)
        self.assertEqual(node.total_download_task, 1)


class BotPreviewWorkflowTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_download_from_link_routes_direct_comment_link_to_preview(self):
        from module import bot as bot_module

        preview_calls = []

        async def fake_preview_comment_workflow(client, message, workflow_request):
            preview_calls.append((client, message, workflow_request))

        bot_client = SimpleNamespace()
        message = MockMessage(
            id=88,
            text="https://t.me/zhyseseb/422?comment=4978",
            from_user=MockUser(id=123),
        )

        with patch(
            "module.bot.preview_comment_workflow", new=fake_preview_comment_workflow
        ), patch("module.bot.parse_link") as parse_link:
            await bot_module.download_from_link(bot_client, message)

        self.assertEqual(len(preview_calls), 1)
        self.assertIs(preview_calls[0][0], bot_client)
        self.assertIs(preview_calls[0][1], message)
        self.assertEqual(preview_calls[0][2].source_chat, "zhyseseb")
        self.assertEqual(preview_calls[0][2].post_id, 422)
        self.assertEqual(preview_calls[0][2].start_comment_id, 4978)
        parse_link.assert_not_called()

    async def test_download_from_link_does_not_route_normal_link_to_preview(self):
        from module import bot as bot_module

        preview_calls = []
        sent_messages = []

        class FakeBotClient:
            async def send_message(self, chat_id, text, **kwargs):
                sent_messages.append((chat_id, text, kwargs))

        async def fake_preview_comment_workflow(client, message, workflow_request):
            preview_calls.append((client, message, workflow_request))

        async def fake_parse_link(client, url):
            return None, None, None

        old_client = bot_module._bot.client
        try:
            bot_module._bot.client = object()
            message = MockMessage(
                id=89,
                text="https://t.me/zhyseseb/422",
                from_user=MockUser(id=123),
            )

            with patch(
                "module.bot.preview_comment_workflow",
                new=fake_preview_comment_workflow,
            ), patch("module.bot.parse_link", new=fake_parse_link):
                await bot_module.download_from_link(FakeBotClient(), message)

            self.assertEqual(preview_calls, [])
            self.assertEqual(len(sent_messages), 1)
        finally:
            bot_module._bot.client = old_client

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

    async def test_preview_persists_failed_comment_ids_and_shows_warning(self):
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

        class FakeUserClient:
            async def get_chat(self, chat_id):
                return source_entity

            async def get_messages(self, chat_id, message_id):
                return base_message

            async def get_discussion_message(self, chat_id, message_id):
                return discussion_message

        class FakeBotClient:
            def __init__(self):
                self.sent_messages = []

            async def send_message(self, chat_id, text, **kwargs):
                self.sent_messages.append((chat_id, text, kwargs))

        async def fake_get_chat_history_v2(client, chat_id, limit=0, reverse=False):
            yield MockMessage(id=4981)

        async def fake_scan_comment_range(*args, **kwargs):
            return SimpleNamespace(
                comments=scanned_comments,
                failed_comment_ids=[4980, 4981],
            )

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

            pending = next(iter(bot_module._bot.pending_comment_workflows.values()))
            self.assertEqual(pending["failed_comment_ids"], [4980, 4981])
            self.assertEqual(
                pending["scan_warning"], "部分评论扫描失败，预览结果可能不完整。"
            )
            self.assertEqual(pending["latest_comment_id"], 4981)
            self.assertIn("扫描警告：部分评论扫描失败，预览结果可能不完整。", bot_client.sent_messages[0][1])
            self.assertIn("扫描失败评论：2", bot_client.sent_messages[0][1])
        finally:
            bot_module._bot.client = old_client
            bot_module._bot.app = old_app
            bot_module._bot.pending_comment_workflows = old_pending

    async def test_preview_warns_when_latest_history_lookup_fails(self):
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
        captured_scan = {}
        scanned_comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
            )
        ]

        class FakeUserClient:
            async def get_chat(self, chat_id):
                return source_entity

            async def get_messages(self, chat_id, message_id):
                return base_message

            async def get_discussion_message(self, chat_id, message_id):
                return discussion_message

        class FakeBotClient:
            def __init__(self):
                self.sent_messages = []

            async def send_message(self, chat_id, text, **kwargs):
                self.sent_messages.append((chat_id, text, kwargs))

        async def fake_get_chat_history_v2(client, chat_id, limit=0, reverse=False):
            if False:
                yield None

        async def fake_scan_comment_range(
            client, chat_id, base_message_id, start_comment_id, end_comment_id
        ):
            captured_scan["end_comment_id"] = end_comment_id
            return SimpleNamespace(comments=scanned_comments, failed_comment_ids=[])

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

            pending = next(iter(bot_module._bot.pending_comment_workflows.values()))
            self.assertEqual(captured_scan["end_comment_id"], 4978)
            self.assertEqual(pending["latest_comment_id"], 4978)
            self.assertIsNotNone(pending["scan_warning"])
            self.assertIn("扫描警告：", bot_client.sent_messages[0][1])
        finally:
            bot_module._bot.client = old_client
            bot_module._bot.app = old_app
            bot_module._bot.pending_comment_workflows = old_pending

    async def test_preview_warns_when_latest_history_lookup_raises(self):
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

        class FakeUserClient:
            async def get_chat(self, chat_id):
                return source_entity

            async def get_messages(self, chat_id, message_id):
                return base_message

            async def get_discussion_message(self, chat_id, message_id):
                return discussion_message

        class FakeBotClient:
            def __init__(self):
                self.sent_messages = []

            async def send_message(self, chat_id, text, **kwargs):
                self.sent_messages.append((chat_id, text, kwargs))

        async def fake_get_chat_history_v2(client, chat_id, limit=0, reverse=False):
            raise RuntimeError("history unavailable")
            yield

        async def fake_scan_comment_range(*args, **kwargs):
            return SimpleNamespace(comments=scanned_comments, failed_comment_ids=[])

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

            pending = next(iter(bot_module._bot.pending_comment_workflows.values()))
            self.assertEqual(pending["latest_comment_id"], 4978)
            self.assertEqual(
                pending["scan_warning"], "最新评论定位失败，预览范围可能不完整。"
            )
            self.assertIn("扫描警告：", bot_client.sent_messages[0][1])
        finally:
            bot_module._bot.client = old_client
            bot_module._bot.app = old_app
            bot_module._bot.pending_comment_workflows = old_pending


class BotCommentWorkflowCallbackTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_callback_removes_pending_workflow_and_edits_message(self):
        from module import bot as bot_module

        class FakeClient:
            def __init__(self):
                self.edits = []

            async def edit_message_text(self, chat_id, message_id, text, **kwargs):
                self.edits.append((chat_id, message_id, text, kwargs))

        token = "abc123"
        old_pending = bot_module._bot.pending_comment_workflows
        try:
            bot_module._bot.pending_comment_workflows = {token: {"comments": []}}
            query = SimpleNamespace(
                data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:cancel",
                message=MockMessage(id=10, from_user=MockUser(id=123)),
            )
            client = FakeClient()

            handled = await bot_module.handle_comment_workflow_callback(client, query)

            self.assertTrue(handled)
            self.assertEqual(bot_module._bot.pending_comment_workflows, {})
            self.assertEqual(client.edits[0][0], 123)
            self.assertEqual(client.edits[0][1], 10)
            self.assertIn("已取消评论媒体下载。", client.edits[0][2])
        finally:
            bot_module._bot.pending_comment_workflows = old_pending

    async def test_confirm_callback_starts_prepared_download_with_naming_context(self):
        from module import bot as bot_module

        class FakeClient:
            def __init__(self):
                self.edits = []
                self.sent_messages = []

            async def edit_message_text(self, chat_id, message_id, text, **kwargs):
                self.edits.append((chat_id, message_id, text, kwargs))

            async def send_message(self, chat_id, text, **kwargs):
                message = MockMessage(id=77, chat_id=chat_id, text=text)
                self.sent_messages.append((chat_id, text, kwargs, message))
                return message

        class FakeLoop:
            def __init__(self):
                self.created = []

            def create_task(self, coroutine):
                self.created.append(coroutine)
                return coroutine

        token = "abc123"
        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )
        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
            )
        ]
        pending = {
            "request": request,
            "entity_id": -1001,
            "channel": "zhyseseb",
            "post_title": "夏日合集",
            "comments": comments,
            "failed_comment_ids": [4980],
            "source_message_id": 88,
        }
        recorded = {}

        async def fake_download_prepared_comments(
            prepared_comments, download_filter, node, failed_comment_ids=None
        ):
            recorded["comments"] = prepared_comments
            recorded["download_filter"] = download_filter
            recorded["node"] = node
            recorded["failed_comment_ids"] = failed_comment_ids

        active_nodes = []

        def fake_add_active_task_node(node):
            active_nodes.append(node)

        old_pending = bot_module._bot.pending_comment_workflows
        old_app = bot_module._bot.app
        old_bot = bot_module._bot.bot
        old_task_node = bot_module._bot.task_node
        old_task_id = bot_module._bot.task_id
        try:
            fake_loop = FakeLoop()
            bot_module._bot.pending_comment_workflows = {token: pending}
            bot_module._bot.app = SimpleNamespace(loop=fake_loop)
            bot_module._bot.bot = object()
            bot_module._bot.task_node = {}
            bot_module._bot.task_id = 0
            client = FakeClient()
            query = SimpleNamespace(
                data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:C",
                message=MockMessage(id=10, from_user=MockUser(id=123)),
                from_user=MockUser(id=123),
            )

            with patch(
                "media_downloader.download_prepared_comments",
                new=fake_download_prepared_comments,
            ), patch("module.bot.add_active_task_node", new=fake_add_active_task_node):
                handled = await bot_module.handle_comment_workflow_callback(
                    client, query
                )
                await fake_loop.created[0]

            self.assertTrue(handled)
            self.assertEqual(bot_module._bot.pending_comment_workflows, {})
            node = recorded["node"]
            self.assertIs(recorded["comments"], comments)
            self.assertIsNone(recorded["download_filter"])
            self.assertEqual(recorded["failed_comment_ids"], [4980])
            self.assertTrue(node.is_running)
            self.assertEqual(node.chat_id, -1001)
            self.assertEqual(node.from_user_id, 123)
            self.assertEqual(node.reply_message_id, 77)
            self.assertEqual(node.comment_naming_context.strategy, NamingStrategy.RECOMMENDED)
            self.assertEqual(node.comment_naming_context.channel, "zhyseseb")
            self.assertEqual(node.comment_naming_context.post_id, 422)
            self.assertEqual(node.comment_naming_context.post_title, "夏日合集")
            self.assertEqual(active_nodes, [node])
            self.assertIn(node.task_id, bot_module._bot.task_node)
        finally:
            bot_module._bot.pending_comment_workflows = old_pending
            bot_module._bot.app = old_app
            bot_module._bot.bot = old_bot
            bot_module._bot.task_node = old_task_node
            bot_module._bot.task_id = old_task_id

    async def test_confirm_callback_keeps_pending_when_task_registration_fails(self):
        from module import bot as bot_module

        class FakeClient:
            async def edit_message_text(self, chat_id, message_id, text, **kwargs):
                return None

            async def send_message(self, chat_id, text, **kwargs):
                return MockMessage(id=77, chat_id=chat_id, text=text)

        class FailingLoop:
            def create_task(self, coroutine):
                coroutine.close()
                raise RuntimeError("cannot schedule task")

        token = "abc123"
        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )
        pending = {
            "request": request,
            "entity_id": -1001,
            "channel": "zhyseseb",
            "post_title": "夏日合集",
            "comments": [
                MockMessage(
                    id=4978,
                    media="video",
                    video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
                )
            ],
            "failed_comment_ids": [4980],
            "source_message_id": 88,
        }

        async def fake_download_prepared_comments(*args, **kwargs):
            return None

        old_pending = bot_module._bot.pending_comment_workflows
        old_app = bot_module._bot.app
        old_bot = bot_module._bot.bot
        old_task_node = bot_module._bot.task_node
        old_task_id = bot_module._bot.task_id
        try:
            bot_module._bot.pending_comment_workflows = {token: pending}
            bot_module._bot.app = SimpleNamespace(loop=FailingLoop())
            bot_module._bot.bot = object()
            bot_module._bot.task_node = {}
            bot_module._bot.task_id = 0
            query = SimpleNamespace(
                data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:C",
                message=MockMessage(id=10, from_user=MockUser(id=123)),
                from_user=MockUser(id=123),
            )

            with patch(
                "media_downloader.download_prepared_comments",
                new=fake_download_prepared_comments,
            ):
                with self.assertRaises(RuntimeError):
                    await bot_module.handle_comment_workflow_callback(
                        FakeClient(), query
                    )

            self.assertIs(bot_module._bot.pending_comment_workflows[token], pending)
            self.assertEqual(bot_module._bot.task_node, {})
        finally:
            bot_module._bot.pending_comment_workflows = old_pending
            bot_module._bot.app = old_app
            bot_module._bot.bot = old_bot
            bot_module._bot.task_node = old_task_node
            bot_module._bot.task_id = old_task_id

    async def test_confirm_callback_keeps_pending_when_start_message_fails(self):
        from module import bot as bot_module

        class FakeClient:
            async def edit_message_text(self, chat_id, message_id, text, **kwargs):
                return None

            async def send_message(self, chat_id, text, **kwargs):
                raise RuntimeError("cannot send start message")

        class FakeLoop:
            def __init__(self):
                self.created = []

            def create_task(self, coroutine):
                self.created.append(coroutine)
                return coroutine

        token = "abc123"
        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )
        pending = {
            "request": request,
            "entity_id": -1001,
            "channel": "zhyseseb",
            "post_title": "夏日合集",
            "comments": [
                MockMessage(
                    id=4978,
                    media="video",
                    video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
                )
            ],
            "failed_comment_ids": [4980],
            "source_message_id": 88,
        }
        active_nodes = []

        def fake_add_active_task_node(node):
            active_nodes.append(node)

        old_pending = bot_module._bot.pending_comment_workflows
        old_app = bot_module._bot.app
        old_bot = bot_module._bot.bot
        old_task_node = bot_module._bot.task_node
        old_task_id = bot_module._bot.task_id
        try:
            fake_loop = FakeLoop()
            bot_module._bot.pending_comment_workflows = {token: pending}
            bot_module._bot.app = SimpleNamespace(loop=fake_loop)
            bot_module._bot.bot = object()
            bot_module._bot.task_node = {}
            bot_module._bot.task_id = 0
            query = SimpleNamespace(
                data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:C",
                message=MockMessage(id=10, from_user=MockUser(id=123)),
                from_user=MockUser(id=123),
            )

            with patch(
                "module.bot.add_active_task_node", new=fake_add_active_task_node
            ):
                with self.assertRaises(RuntimeError):
                    await bot_module.handle_comment_workflow_callback(
                        FakeClient(), query
                    )

            self.assertIs(bot_module._bot.pending_comment_workflows[token], pending)
            self.assertEqual(bot_module._bot.task_node, {})
            self.assertEqual(active_nodes, [])
            self.assertEqual(fake_loop.created, [])
        finally:
            bot_module._bot.pending_comment_workflows = old_pending
            bot_module._bot.app = old_app
            bot_module._bot.bot = old_bot
            bot_module._bot.task_node = old_task_node
            bot_module._bot.task_id = old_task_id

    async def test_confirm_callback_falls_back_when_preview_edit_fails(self):
        from module import bot as bot_module

        class FakeClient:
            def __init__(self):
                self.sent_messages = []

            async def edit_message_text(self, chat_id, message_id, text, **kwargs):
                raise RuntimeError("edit failed")

            async def send_message(self, chat_id, text, **kwargs):
                message = MockMessage(
                    id=70 + len(self.sent_messages),
                    chat_id=chat_id,
                    text=text,
                )
                self.sent_messages.append((chat_id, text, kwargs, message))
                return message

        class FakeLoop:
            def __init__(self):
                self.created = []

            def create_task(self, coroutine):
                self.created.append(coroutine)
                return coroutine

        token = "abc123"
        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )
        pending = {
            "request": request,
            "entity_id": -1001,
            "channel": "zhyseseb",
            "post_title": "夏日合集",
            "comments": [
                MockMessage(
                    id=4978,
                    media="video",
                    video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
                )
            ],
            "failed_comment_ids": [],
            "source_message_id": 88,
        }
        recorded = {}

        async def fake_download_prepared_comments(
            prepared_comments, download_filter, node, failed_comment_ids=None
        ):
            recorded["node"] = node

        old_pending = bot_module._bot.pending_comment_workflows
        old_app = bot_module._bot.app
        old_bot = bot_module._bot.bot
        old_task_node = bot_module._bot.task_node
        old_task_id = bot_module._bot.task_id
        try:
            fake_loop = FakeLoop()
            bot_module._bot.pending_comment_workflows = {token: pending}
            bot_module._bot.app = SimpleNamespace(loop=fake_loop)
            bot_module._bot.bot = object()
            bot_module._bot.task_node = {}
            bot_module._bot.task_id = 0
            client = FakeClient()
            query = SimpleNamespace(
                data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:C",
                message=MockMessage(id=10, from_user=MockUser(id=123)),
                from_user=MockUser(id=123),
            )

            with patch(
                "media_downloader.download_prepared_comments",
                new=fake_download_prepared_comments,
            ), patch("module.bot.add_active_task_node"):
                handled = await bot_module.handle_comment_workflow_callback(
                    client, query
                )
                await fake_loop.created[0]

            self.assertTrue(handled)
            self.assertEqual(bot_module._bot.pending_comment_workflows, {})
            self.assertEqual(len(client.sent_messages), 2)
            self.assertTrue(recorded["node"].is_running)
        finally:
            bot_module._bot.pending_comment_workflows = old_pending
            bot_module._bot.app = old_app
            bot_module._bot.bot = old_bot
            bot_module._bot.task_node = old_task_node
            bot_module._bot.task_id = old_task_id

    async def test_expired_token_callback_is_handled_without_starting_download(self):
        from module import bot as bot_module

        class FakeClient:
            def __init__(self):
                self.edits = []

            async def edit_message_text(self, chat_id, message_id, text, **kwargs):
                self.edits.append((chat_id, message_id, text, kwargs))

        started = False

        async def fake_download_prepared_comments(*args, **kwargs):
            nonlocal started
            started = True

        old_pending = bot_module._bot.pending_comment_workflows
        try:
            bot_module._bot.pending_comment_workflows = {}
            query = SimpleNamespace(
                data=f"{COMMENT_WORKFLOW_PREFIX}:missing:C",
                message=MockMessage(id=10, from_user=MockUser(id=123)),
                from_user=MockUser(id=123),
            )
            client = FakeClient()

            with patch(
                "media_downloader.download_prepared_comments",
                new=fake_download_prepared_comments,
            ):
                handled = await bot_module.handle_comment_workflow_callback(
                    client, query
                )

            self.assertTrue(handled)
            self.assertFalse(started)
            self.assertIn("任务已过期，请重新发送链接", client.edits[0][2])
        finally:
            bot_module._bot.pending_comment_workflows = old_pending

    async def test_non_comment_workflow_callback_is_not_handled(self):
        from module import bot as bot_module

        query = SimpleNamespace(
            data="stop task all",
            message=MockMessage(id=10, from_user=MockUser(id=123)),
        )

        handled = await bot_module.handle_comment_workflow_callback(object(), query)

        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()
