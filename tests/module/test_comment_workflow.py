"""Tests for Telegram comment-link media workflow planning."""
import datetime
import unittest

from tests.test_common import MockDocument, MockMessage, MockPhoto, MockUser, MockVideo

from module.comment_workflow import (
    COMMENT_WORKFLOW_PREFIX,
    NamingStrategy,
    build_callback_data,
    build_comment_workflow_request,
    filter_media_comments,
    summarize_comments,
)


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

    def test_filter_media_comments_skips_text_and_empty_messages(self):
        comments = [
            MockMessage(id=1, text="hello"),
            MockMessage(id=2, media="photo", photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="p1")),
            MockMessage(id=3, empty=True),
            MockMessage(id=4, media="video", video=MockVideo(file_name="clip.mp4", mime_type="video/mp4")),
        ]

        media_comments = filter_media_comments(comments)

        self.assertEqual([comment.id for comment in media_comments], [2, 4])

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


if __name__ == "__main__":
    unittest.main()
