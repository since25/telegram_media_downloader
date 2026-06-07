"""Tests for Telegram comment-link media workflow planning."""
import datetime
import hashlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_common import MockDocument, MockMessage, MockPhoto, MockUser, MockVideo

from utils.format import Link

from module.comment_workflow import (
    COMMENT_WORKFLOW_PREFIX,
    NamingStrategy,
    build_callback_data,
    build_comment_workflow_request,
    build_workflow_token,
    clean_segment,
    filter_media_comments,
    parse_callback_data,
    summarize_comments,
)


class CommentWorkflowTestCase(unittest.TestCase):
    def test_build_comment_workflow_request_from_comment_link(self):
        with patch(
            "module.comment_workflow.extract_info_from_link",
            return_value=Link(group_id="zhyseseb", post_id=422, comment_id=4978),
        ):
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
        self.assertIsNone(
            build_comment_workflow_request("https://t.me/zhyseseb/422?comment=4978")
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


if __name__ == "__main__":
    unittest.main()
