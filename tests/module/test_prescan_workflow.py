"""Tests for prescan multi-package planning and selection helpers."""
import unittest

from tests.test_common import MockMessage, MockVideo


class PrescanWorkflowTestCase(unittest.TestCase):
    def test_plan_prescan_packages_splits_multiple_caption_packages(self):
        from module.prescan_workflow import PrescanLimits, plan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章 01/20",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=101,
                media="video",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
            MockMessage(
                id=120,
                media="video",
                caption="课程 第02章 01/20",
                video=MockVideo(file_name="03.mp4", mime_type="video/mp4", file_size=300),
            ),
            MockMessage(
                id=121,
                media="video",
                video=MockVideo(file_name="04.mp4", mime_type="video/mp4", file_size=400),
            ),
        ]

        plan = plan_prescan_packages(
            messages,
            start_message_id=100,
            limits=PrescanLimits(max_messages=5000, max_packages=50),
        )

        self.assertEqual(plan.scanned_count, 4)
        self.assertEqual(len(plan.packages), 2)
        self.assertEqual(plan.packages[0].start_message_id, 100)
        self.assertEqual(plan.packages[0].end_message_id, 101)
        self.assertEqual(plan.packages[0].title, "课程 第01章 01/20")
        self.assertEqual([item.message.id for item in plan.packages[0].items], [100, 101])
        self.assertEqual(plan.packages[1].start_message_id, 120)
        self.assertEqual(plan.packages[1].end_message_id, 121)

    def test_plan_prescan_packages_does_not_warn_on_exact_message_limit(self):
        from module.prescan_workflow import PrescanLimits, plan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=101,
                media="video",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
        ]

        plan = plan_prescan_packages(
            messages,
            start_message_id=100,
            limits=PrescanLimits(max_messages=2),
        )

        self.assertIsNone(plan.warning)

    def test_plan_prescan_packages_does_not_warn_when_package_limit_exact(self):
        from module.prescan_workflow import PrescanLimits, plan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=101,
                media="video",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
        ]

        plan = plan_prescan_packages(
            messages,
            start_message_id=100,
            limits=PrescanLimits(max_packages=1),
        )

        self.assertEqual(len(plan.packages), 1)
        self.assertIsNone(plan.warning)

    def test_plan_prescan_packages_warns_when_package_limit_truncates(self):
        from module.prescan_workflow import PrescanLimits, plan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=120,
                media="video",
                caption="课程 第02章",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
        ]

        plan = plan_prescan_packages(
            messages,
            start_message_id=100,
            limits=PrescanLimits(max_packages=1),
        )

        self.assertEqual(len(plan.packages), 1)
        self.assertEqual(plan.warning, "预扫已达到包数量上限，结果可能不是频道最新消息。")

    def test_plan_prescan_packages_ignores_no_media_without_warning(self):
        from module.prescan_workflow import PrescanLimits, plan_prescan_packages

        messages = [
            MockMessage(id=100, media=None, text="hello"),
            MockMessage(id=101, media=None, text="world"),
        ]

        plan = plan_prescan_packages(messages, 100, PrescanLimits())

        self.assertEqual(plan.packages, [])
        self.assertIsNone(plan.warning)

    def test_selection_page_formats_mobile_compact_rows(self):
        from module.prescan_workflow import (
            PrescanLimits,
            format_prescan_selection_page,
            plan_prescan_packages,
        )

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=120,
                media="video",
                caption="课程 第02章",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
        ]
        plan = plan_prescan_packages(messages, 100, PrescanLimits())

        text = format_prescan_selection_page(
            plan,
            channel="Private Course",
            page=0,
            selected_package_ids={2},
            page_size=8,
        )

        self.assertIn("预扫完成：", text)
        self.assertIn("频道：Private Course", text)
        self.assertIn("识别：2 个包", text)
        self.assertIn("已选：1 个", text)
        self.assertIn("1. 100-100｜1 个｜100.0B", text)
        self.assertIn("课程 第01章", text)

    def test_selection_page_negative_page_shows_first_page(self):
        from module.prescan_workflow import (
            PrescanLimits,
            format_prescan_selection_page,
            plan_prescan_packages,
        )

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
        ]
        plan = plan_prescan_packages(messages, 100, PrescanLimits())

        text = format_prescan_selection_page(
            plan,
            channel="Private Course",
            page=-1,
            selected_package_ids=set(),
            page_size=8,
        )

        self.assertIn("1. 100-100｜1 个｜100.0B", text)
        self.assertIn("课程 第01章", text)

    def test_prescan_callback_data_round_trips(self):
        from module.prescan_workflow import (
            build_prescan_callback_data,
            parse_prescan_callback_data,
        )

        data = build_prescan_callback_data("abc123", "toggle", 7)

        self.assertEqual(data, "ps:abc123:toggle:7")
        self.assertEqual(parse_prescan_callback_data(data), ("abc123", "toggle", "7"))
        self.assertIsNone(parse_prescan_callback_data("pw:abc123:C"))
        self.assertIsNone(parse_prescan_callback_data("ps::toggle:7"))

    def test_prescan_callback_data_rejects_empty_builder_inputs(self):
        from module.prescan_workflow import build_prescan_callback_data

        with self.assertRaises(ValueError):
            build_prescan_callback_data("", "toggle")
        with self.assertRaises(ValueError):
            build_prescan_callback_data("abc123", "")

    def test_prescan_callback_data_rejects_delimiters(self):
        from module.prescan_workflow import build_prescan_callback_data

        with self.assertRaises(ValueError):
            build_prescan_callback_data("a:b", "toggle")
        with self.assertRaises(ValueError):
            build_prescan_callback_data("abc123", "tog:gle")
        with self.assertRaises(ValueError):
            build_prescan_callback_data("abc123", "toggle", "1:2")
