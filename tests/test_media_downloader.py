"""Unittest module for media downloader."""
import asyncio
import os
import platform
import queue
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import List, Union

import mock
import pyrogram

from media_downloader import (
    _can_download,
    _check_config,
    _get_media_meta,
    _is_exist,
    _sanitize_monitor_cfg,
    app,
    download_all_chat,
    download_media,
    download_task,
    main,
    save_msg_to_file,
    worker,
)
from module.app import Application, DownloadStatus, TaskNode
from module.cloud_drive import CloudDriveConfig
from module.pyrogram_extension import (
    get_extension,
    record_download_status,
    reset_download_cache,
)

from .test_common import (
    Chat,
    Date,
    MockAudio,
    MockDocument,
    MockMessage,
    MockPhoto,
    MockUser,
    MockVideo,
    MockVideoNote,
    MockVoice,
    get_extension,
    platform_generic_path,
)

MOCK_DIR: str = "/root/project"
if platform.system() == "Windows":
    MOCK_DIR = "\\root\\project"
MOCK_CONF = {
    "api_id": 123,
    "api_hash": "hasw5Tgawsuj67",
    "chat": [{"chat_id": 8654123, "last_read_message_id": 0, "ids_to_retry": [1, 2]}],
    "media_types": ["audio", "voice", "document", "photo", "video", "video_note"],
    "file_formats": {"audio": ["all"], "voice": ["all"], "video": ["all"]},
    "save_path": MOCK_DIR,
    "file_name_prefix": ["message_id", "caption", "file_name"],
}

event_str = "asyncio.AbstractEventLoop.run_forever"
if sys.version_info > (3, 8):
    event_str = "asyncio.ProactorEventLoop.run_forever"


def os_remove(_: str):
    pass


def is_exist(file: str):
    if os.path.basename(file).find("313 - sucess_exist_down.mp4") != -1:
        return True
    elif os.path.basename(file).find("422 - exception.mov") != -1:
        raise Exception
    return False


def os_get_file_size(file: str) -> int:
    if os.path.basename(file).find("311 - failed_down.mp4") != -1:
        return 0
    elif os.path.basename(file).find("312 - sucess_down.mp4") != -1:
        return 1024
    elif os.path.basename(file).find("313 - sucess_exist_down.mp4") != -1:
        return 1024
    return 0


def rest_app(conf: dict):
    config_test = os.path.join(os.path.abspath("."), "config_test.yaml")
    data_test = os.path.join(os.path.abspath("."), "data_test.yaml")
    if os.path.exists(config_test):
        os.remove(config_test)
    if os.path.exists(data_test):
        os.remove(data_test)
    app.total_download_task = 0
    app.is_running = True
    app.chat_download_config: dict = {}
    # app.already_download_ids_set = set()
    app.save_path = os.path.abspath(".")
    app.api_id: str = ""
    app.api_hash: str = ""
    app.media_types: List[str] = []
    app.file_formats: dict = {}
    app.proxy: dict = {}
    app.restart_program = False
    app.config: dict = {}
    app.app_data: dict = {}
    app.file_path_prefix: List[str] = ["chat_title", "media_datetime"]
    app.file_name_prefix: List[str] = ["message_id", "file_name"]
    app.file_name_prefix_split: str = " - "
    app.log_file_path = os.path.join(os.path.abspath("."), "log")
    app.cloud_drive_config = CloudDriveConfig()
    app.hide_file_name = False
    app.caption_name_dict: dict = {}
    app.max_concurrent_transmissions: int = 1
    app.web_host: str = "localhost"
    app.web_port: int = 5000
    app.config_file = "config_test.yaml"
    app.app_data_file = "data_test.yaml"
    app.config = conf
    app.assign_config(conf)
    app.assign_app_data(conf)


def mock_manage_duplicate_file(file_path: str) -> str:
    return file_path


def raise_keyboard_interrupt():
    raise KeyboardInterrupt


async def new_upload_telegram_chat(
    client: pyrogram.Client,
    upload_user: pyrogram.Client,
    app: Application,
    node: TaskNode,
    message: pyrogram.types.Message,
    download_status: DownloadStatus,
    file_name: str = None,
):
    pass


def raise_exception():
    raise Exception


def load_config():
    raise ValueError("error load config")


class MyQueue:
    def __init__(self, queue_list_obj):
        self._queue = queue.Queue()
        for item in queue_list_obj:
            self._queue.put(item)

    async def get(self):
        if self._queue.empty():
            raise Exception
        return self._queue.get()


class MockEventLoop:
    def __init__(self):
        pass

    def run_until_complete(self, *args, **kwargs):
        return {"api_id": 1, "api_hash": "asdf", "ids_to_retry": [1, 2, 3]}


class MockAsync:
    def __init__(self):
        pass

    def get_event_loop(self):
        return MockEventLoop()


async def async_get_media_meta(chat_id, message, message_media, _type):
    result = await _get_media_meta(chat_id, message, message_media, _type)
    return result


async def async_download_media(
    client, message, media_types, file_formats, chat_id=-123
):
    node = TaskNode(chat_id=chat_id)
    return await download_media(client, message, media_types, file_formats, node)


def mock_move_to_download_path(temp_download_path: str, download_path: str):
    pass


def mock_check_download_finish(media_size: int, download_path: str, ui_file_name: str):
    pass


async def new_fetch_message(client: pyrogram.Client, message: pyrogram.types.Message):
    return message


async def get_chat_history(client, *args, **kwargs):
    items = [
        MockMessage(
            id=1213,
            media=True,
            voice=MockVoice(
                mime_type="audio/ogg",
                date=datetime(2019, 7, 25, 14, 53, 50),
            ),
        ),
        MockMessage(
            id=1214,
            media=False,
            text="test message 1",
        ),
        MockMessage(
            id=1215,
            media=False,
            text="test message 2",
        ),
        MockMessage(
            id=1216,
            media=False,
            text="test message 3",
        ),
    ]
    for item in items:
        yield item


class MockClient:
    def __init__(self, *args, **kwargs):
        pass

    def __aiter__(self):
        return self

    async def start(self):
        pass

    async def stop(self):
        pass

    async def get_messages(self, *args, **kwargs):
        if kwargs["message_ids"] == 7:
            return MockMessage(
                id=7,
                media=True,
                chat_id=123456,
                chat_title="123456",
                date=datetime.now(),
                video=MockVideo(
                    file_name="sample_video.mov",
                    mime_type="video/mov",
                ),
            )
        elif kwargs["message_ids"] == 8:
            return MockMessage(
                id=8,
                media=True,
                chat_id=234567,
                chat_title="234567",
                date=datetime.now(),
                video=MockVideo(
                    file_name="sample_video.mov",
                    mime_type="video/mov",
                ),
            )
        elif kwargs["message_ids"] == [1, 2]:
            return [
                MockMessage(
                    id=1,
                    media=True,
                    chat_id=234568,
                    chat_title="234568",
                    date=datetime.now(),
                    video=MockVideo(
                        file_name="sample_video.mov",
                        mime_type="video/mov",
                    ),
                ),
                MockMessage(
                    id=2,
                    media=True,
                    chat_id=234568,
                    chat_title="234568",
                    date=datetime.now(),
                    video=MockVideo(
                        file_name="sample_video2.mov",
                        mime_type="video/mov",
                    ),
                ),
            ]
        elif kwargs["message_ids"] == 313:
            return MockMessage(
                id=313,
                media=True,
                video=MockVideo(
                    file_name="sucess_exist_down.mp4",
                    mime_type="video/mp4",
                    file_size=1024,
                ),
            )
        elif kwargs["message_ids"] == 312:
            return MockMessage(
                id=312,
                media=True,
                video=MockVideo(
                    file_name="sucess_down.mp4",
                    mime_type="video/mp4",
                    file_size=1024,
                ),
            )
        elif kwargs["message_ids"] == 311:
            return MockMessage(
                id=311,
                media=True,
                video=MockVideo(
                    file_name="failed_down.mp4",
                    mime_type="video/mp4",
                    file_size=1024,
                ),
            )
        return []

    async def download_media(self, *args, **kwargs):
        mock_message = args[0]
        if mock_message.id in [7, 8]:
            raise pyrogram.errors.BadRequest
        elif mock_message.id == 9:
            raise pyrogram.errors.Unauthorized
        elif mock_message.id == 11:
            raise TypeError
        elif mock_message.id == 420:
            raise pyrogram.errors.FloodWait(value=420)
        elif mock_message.id == 421:
            raise Exception
        return kwargs["file_name"]

    async def edit_message_text(self, *args, **kwargs):
        return True


def check_for_updates(_: dict = None):
    pass


@mock.patch("media_downloader.get_extension", new=get_extension)
@mock.patch("module.pyrogram_extension.get_extension", new=get_extension)
@mock.patch("media_downloader.fetch_message", new=new_fetch_message)
@mock.patch("media_downloader.get_chat_history_v2", new=get_chat_history)
@mock.patch("media_downloader.RETRY_TIME_OUT", new=0)
@mock.patch("media_downloader.check_for_updates", new=check_for_updates)
@mock.patch("media_downloader._start_channel_library_service", new=lambda *_args: None)
@mock.patch("media_downloader._stop_channel_library_service", new=lambda *_args: None)
class MediaDownloaderTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.loop = asyncio.get_event_loop()
        except RuntimeError:
            cls.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(cls.loop)
        rest_app(MOCK_CONF)
        app.loop = cls.loop

    # @mock.patch("media_downloader.app.save_path", new=MOCK_DIR)
    def test_get_media_meta(self):
        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        # Test Voice notes
        message = MockMessage(
            id=1,
            media=True,
            chat_title="test1",
            date=datetime(2019, 7, 25, 14, 53, 50),
            voice=MockVoice(
                mime_type="audio/ogg",
                date=datetime(2019, 7, 25, 14, 53, 50),
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.voice, "voice")
        )

        self.assertEqual(
            (
                platform_generic_path(
                    "/root/project/test1/2019_07/1 - voice_2019-07-25T14_53_50.ogg"
                ),
                platform_generic_path(
                    os.path.join(
                        app.temp_save_path, "test1/1 - voice_2019-07-25T14_53_50.ogg"
                    )
                ),
                "ogg",
            ),
            result,
        )

        # Test photos
        message = MockMessage(
            id=2,
            media=True,
            date=datetime(2019, 8, 5, 14, 35, 12),
            chat_title="test2",
            photo=MockPhoto(
                date=datetime(2019, 8, 5, 14, 35, 12), file_unique_id="ADAVKJYIFV"
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.photo, "photo")
        )
        self.assertEqual(
            (
                platform_generic_path("/root/project/test2/2019_08/2 - ADAVKJYIFV.jpg"),
                platform_generic_path(
                    os.path.join(app.temp_save_path, "test2/2 - ADAVKJYIFV.jpg")
                ),
                None,
            ),
            result,
        )

        message = MockMessage(
            id=2,
            media=True,
            date=datetime(2019, 8, 5, 14, 35, 12),
            chat_title="test2",
            media_group_id="AAA213213",
            caption="#home #book",
            photo=MockPhoto(
                date=datetime(2019, 8, 5, 14, 35, 12), file_unique_id="ADAVKJYIFV"
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.photo, "photo")
        )
        self.assertEqual(
            (
                platform_generic_path(
                    "/root/project/test2/2019_08/2 - #home #book - ADAVKJYIFV.jpg"
                ),
                platform_generic_path(
                    os.path.join(
                        app.temp_save_path, "test2/2 - #home #book - ADAVKJYIFV.jpg"
                    )
                ),
                None,
            ),
            result,
        )

        # Test Documents
        message = MockMessage(
            id=3,
            media=True,
            chat_title="test2",
            document=MockDocument(
                file_name="sample_document.pdf",
                mime_type="application/pdf",
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.document, "document")
        )
        self.assertEqual(
            (
                platform_generic_path("/root/project/test2/0/3 - sample_document.pdf"),
                platform_generic_path(
                    os.path.join(app.temp_save_path, "test2/3 - sample_document.pdf")
                ),
                "pdf",
            ),
            result,
        )

        before_file_name_prefix_split = app.file_name_prefix_split
        app.file_name_prefix_split = "-"

        message = MockMessage(
            id=3,
            media=True,
            chat_title="test2",
            media_group_id="BBB213213",
            caption="#work",
            document=MockDocument(
                file_name="sample_document.pdf",
                mime_type="application/pdf",
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.document, "document")
        )
        self.assertEqual(
            (
                platform_generic_path(
                    "/root/project/test2/0/3-#work-sample_document.pdf"
                ),
                platform_generic_path(
                    os.path.join(
                        app.temp_save_path, "test2/3-#work-sample_document.pdf"
                    )
                ),
                "pdf",
            ),
            result,
        )

        app.file_name_prefix_split = before_file_name_prefix_split
        # Test audio
        message = MockMessage(
            id=4,
            media=True,
            date=datetime(2021, 8, 5, 14, 35, 12),
            chat_title="test2",
            audio=MockAudio(
                file_name="sample_audio.mp3",
                mime_type="audio/mp3",
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.audio, "audio")
        )
        self.assertEqual(
            (
                platform_generic_path(
                    "/root/project/test2/2021_08/4 - sample_audio.mp3"
                ),
                platform_generic_path(
                    os.path.join(app.temp_save_path, "test2/4 - sample_audio.mp3")
                ),
                "mp3",
            ),
            result,
        )

        # Test Video 1
        message = MockMessage(
            id=5,
            media=True,
            date=datetime(2022, 8, 5, 14, 35, 12),
            chat_title="test2",
            video=MockVideo(
                mime_type="video/mp4",
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.video, "video")
        )
        self.assertEqual(
            (
                platform_generic_path("/root/project/test2/2022_08/5.mp4"),
                platform_generic_path(os.path.join(app.temp_save_path, "test2/5.mp4")),
                "mp4",
            ),
            result,
        )

        # Test Video 2
        message = MockMessage(
            id=5,
            media=True,
            date=datetime(2022, 8, 5, 14, 35, 12),
            chat_title="test2",
            video=MockVideo(
                file_name="test.mp4",
                mime_type="video/mp4",
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.video, "video")
        )
        self.assertEqual(
            (
                platform_generic_path("/root/project/test2/2022_08/5 - test.mp4"),
                platform_generic_path(
                    os.path.join(app.temp_save_path, "test2/5 - test.mp4")
                ),
                "mp4",
            ),
            result,
        )

        # Test Video 3: not exist chat_title
        message = MockMessage(
            id=5,
            media=True,
            dis_chat=True,
            date=datetime(2022, 8, 5, 14, 35, 12),
            video=MockVideo(
                file_name="test.mp4",
                mime_type="video/mp4",
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.video, "video")
        )

        self.assertEqual(
            (
                platform_generic_path("/root/project/-123/2022_08/5 - test.mp4"),
                platform_generic_path(
                    os.path.join(app.temp_save_path, "-123/5 - test.mp4")
                ),
                "mp4",
            ),
            result,
        )

        # Test VideoNote
        message = MockMessage(
            id=6,
            media=True,
            date=datetime(2019, 7, 25, 14, 53, 50),
            chat_title="test2",
            video_note=MockVideoNote(
                mime_type="video/mp4",
                date=datetime(2019, 7, 25, 14, 53, 50),
            ),
        )
        result = self.loop.run_until_complete(
            async_get_media_meta(-123, message, message.video_note, "video_note")
        )
        self.assertEqual(
            (
                platform_generic_path(
                    "/root/project/test2/2019_07/6 - video_note_2019-07-25T14_53_50.mp4"
                ),
                platform_generic_path(
                    os.path.join(
                        app.temp_save_path,
                        "test2/6 - video_note_2019-07-25T14_53_50.mp4",
                    )
                ),
                "mp4",
            ),
            result,
        )

    def test_get_media_meta_uses_comment_naming_context_for_video(self):
        from module.comment_workflow import CommentNamingContext, NamingStrategy

        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        app.temp_save_path = os.path.join(MOCK_DIR, "temp")
        app.file_path_prefix = ["chat_title", "media_datetime"]
        app.file_name_prefix = ["message_id", "file_name"]
        app.file_name_prefix_split = " - "

        message = MockMessage(
            id=4978,
            chat_id=-1001,
            chat_title="Discussion",
            media="video",
            video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
            caption="caption text",
            from_user=MockUser(username="user123"),
            date=datetime(2026, 6, 7),
        )
        node = TaskNode(chat_id=-1001)
        node.comment_naming_context = CommentNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel="zhyseseb",
            post_id=422,
            post_title="夏日/合集 Vol.12",
        )

        file_name, temp_file_name, file_format = self.loop.run_until_complete(
            _get_media_meta(-1001, message, message.video, "video", node=node)
        )

        self.assertEqual(file_format, "mp4")
        self.assertEqual(
            file_name,
            platform_generic_path(
                f"{MOCK_DIR}/Discussion/2026_06/zhyseseb/422-夏日_合集 Vol.12/4978 - bad_name_.mp4"
            ),
        )
        self.assertEqual(
            temp_file_name,
            platform_generic_path(
                f"{MOCK_DIR}/temp/Discussion/zhyseseb/422-夏日_合集 Vol.12/4978 - bad_name_.mp4"
            ),
        )

    def test_get_media_meta_uses_package_naming_context_for_video(self):
        from module.comment_workflow import (
            NamingStrategy,
            PackageMediaItem,
            PackageNamingContext,
        )

        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        app.temp_save_path = os.path.join(MOCK_DIR, "temp")
        app.file_path_prefix = ["chat_title", "media_datetime"]
        app.file_name_prefix = ["message_id", "file_name"]
        app.file_name_prefix_split = " - "

        message = MockMessage(
            id=126711,
            chat_id=-1001,
            chat_title="Private",
            media="video",
            video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
            caption="课程/第01章",
            from_user=MockUser(username="user123"),
            date=datetime(2026, 6, 7),
        )
        node = TaskNode(chat_id=-1001)
        node.package_naming_context = PackageNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel="私密频道",
            start_message_id=126700,
            package_title="课程/第01章",
        )
        node.package_media_items = {
            126711: PackageMediaItem(
                message=message,
                media_type="video",
                caption_for_naming="课程/第01章",
                original_caption="课程/第01章",
            )
        }

        file_name, temp_file_name, file_format = self.loop.run_until_complete(
            _get_media_meta(-1001, message, message.video, "video", node=node)
        )

        self.assertEqual(file_format, "mp4")
        self.assertEqual(
            file_name,
            platform_generic_path(
                f"{MOCK_DIR}/Private/2026_06/126700-课程_第01章/126711 - bad_name_.mp4"
            ),
        )
        self.assertEqual(
            temp_file_name,
            platform_generic_path(
                f"{MOCK_DIR}/temp/Private/126700-课程_第01章/126711 - bad_name_.mp4"
            ),
        )

    def test_get_media_meta_naming_snapshot_overrides_node_package_context(self):
        from module.comment_workflow import (
            NamingStrategy,
            PackageMediaItem,
            PackageNamingContext,
        )

        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        app.temp_save_path = os.path.join(MOCK_DIR, "temp")
        app.file_path_prefix = ["chat_title", "media_datetime"]
        app.file_name_prefix = ["message_id", "file_name"]
        app.file_name_prefix_split = " - "

        message = MockMessage(
            id=126711,
            chat_id=-1001,
            chat_title="Private",
            media="video",
            video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
            caption="课程/第01章",
            from_user=MockUser(username="user123"),
            date=datetime(2026, 6, 7),
        )
        node = TaskNode(chat_id=-1001)
        node.package_naming_context = PackageNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel="私密频道",
            start_message_id=222,
            package_title="P2",
        )
        node.package_media_items = {}

        p1_context = PackageNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel="私密频道",
            start_message_id=111,
            package_title="P1",
        )
        p1_item = PackageMediaItem(
            message=message,
            media_type="video",
            caption_for_naming="P1",
            original_caption="课程/第01章",
        )
        naming_snapshot = {"context": p1_context, "item": p1_item}

        file_name, _temp_file_name, file_format = self.loop.run_until_complete(
            _get_media_meta(
                -1001,
                message,
                message.video,
                "video",
                node=node,
                naming_snapshot=naming_snapshot,
            )
        )

        self.assertEqual(file_format, "mp4")
        # 期望 gen_file_name 以 "111-" 开头（P1），即使 node.package_naming_context 是 P2
        self.assertIn("111-", file_name)
        self.assertNotIn("222-", file_name)

    def test_scan_comment_range_keeps_only_comments_from_discussion_root(self):
        from media_downloader import scan_comment_range
        from module.comment_workflow import filter_media_comments

        discussion_root_id = 6050
        other_discussion_root_id = 6110
        discussion_message = MockMessage(
            id=discussion_root_id,
            chat_id=-200,
            chat_title="Discussion",
        )
        comments = {
            6844: MockMessage(
                id=6844,
                media="photo",
                photo=MockPhoto(date=datetime(2026, 6, 8), file_unique_id="p6844"),
                reply_to_message_id=discussion_root_id,
            ),
            6845: MockMessage(
                id=6845,
                media="video",
                video=MockVideo(file_name="6845.mp4", mime_type="video/mp4"),
                reply_to_message_id=discussion_root_id,
            ),
            6846: MockMessage(
                id=6846,
                media="video",
                video=MockVideo(file_name="6846.mp4", mime_type="video/mp4"),
                reply_to_message_id=discussion_root_id,
            ),
            6847: MockMessage(
                id=6847,
                media="video",
                video=MockVideo(file_name="6847.mp4", mime_type="video/mp4"),
                reply_to_message_id=discussion_root_id,
            ),
            6848: MockMessage(
                id=6848,
                text="text-only comment",
                reply_to_message_id=discussion_root_id,
            ),
            6886: MockMessage(
                id=6886,
                media="video",
                video=MockVideo(file_name="6886.mp4", mime_type="video/mp4"),
                reply_to_message_id=other_discussion_root_id,
            ),
            6887: MockMessage(
                id=6887,
                media="video",
                video=MockVideo(file_name="6887.mp4", mime_type="video/mp4"),
                reply_to_message_id=other_discussion_root_id,
            ),
        }

        class FakeClient:
            async def get_discussion_message(self, chat_id, base_message_id):
                self.requested_discussion = (chat_id, base_message_id)
                return discussion_message

            async def get_messages(self, chat_id, message_ids):
                if isinstance(message_ids, list):
                    return [comments.get(message_id) for message_id in message_ids]
                return comments.get(message_ids)

        result = self.loop.run_until_complete(
            scan_comment_range(
                FakeClient(),
                -1001,
                605,
                6844,
                6887,
                expected_comment_count=5,
            )
        )

        self.assertEqual(
            [comment.id for comment in result.comments],
            [6844, 6845, 6846, 6847, 6848],
        )
        self.assertEqual(
            [comment.id for comment in filter_media_comments(result.comments)],
            [6844, 6845, 6846, 6847],
        )

    def test_scan_comment_range_uses_source_replies_before_discussion_group(self):
        from media_downloader import scan_comment_range
        from module.comment_workflow import filter_media_comments

        comments = [
            MockMessage(
                id=6844,
                media="photo",
                photo=MockPhoto(date=datetime(2026, 6, 8), file_unique_id="p6844"),
            ),
            MockMessage(
                id=6845,
                media="video",
                video=MockVideo(file_name="6845.mp4", mime_type="video/mp4"),
            ),
            MockMessage(
                id=6846,
                media="video",
                video=MockVideo(file_name="6846.mp4", mime_type="video/mp4"),
            ),
            MockMessage(
                id=6847,
                media="video",
                video=MockVideo(file_name="6847.mp4", mime_type="video/mp4"),
            ),
            MockMessage(id=6848, text="text-only comment"),
        ]

        class FakeClient:
            def __init__(self):
                self.invoked = []
                self.discussion_requested = False
                self.raw_result = object()

            async def resolve_peer(self, chat_id):
                self.resolved_chat_id = chat_id
                return "resolved-peer"

            async def invoke(self, rpc, sleep_threshold=-1):
                self.invoked.append((rpc, sleep_threshold))
                return self.raw_result

            async def get_discussion_message(self, chat_id, base_message_id):
                self.discussion_requested = True
                raise AssertionError("direct source replies should be tried first")

        async def fake_parse_messages(client, raw_messages, replies=0):
            self.assertIs(raw_messages, client.raw_result)
            self.assertEqual(replies, 0)
            return comments

        client = FakeClient()
        with mock.patch(
            "media_downloader.pyrogram_utils.parse_messages",
            new=fake_parse_messages,
        ):
            result = self.loop.run_until_complete(
                scan_comment_range(
                    client,
                    "zhyseseb",
                    605,
                    6844,
                    6887,
                    expected_comment_count=5,
                )
            )

        rpc, sleep_threshold = client.invoked[0]
        self.assertEqual(client.resolved_chat_id, "zhyseseb")
        self.assertEqual(rpc.msg_id, 605)
        self.assertEqual(rpc.min_id, 6843)
        self.assertEqual(rpc.max_id, 6888)
        self.assertEqual(rpc.limit, 5)
        self.assertEqual(sleep_threshold, -1)
        self.assertFalse(client.discussion_requested)
        self.assertEqual(
            [comment.id for comment in result.comments],
            [6844, 6845, 6846, 6847, 6848],
        )
        self.assertEqual(
            [comment.id for comment in filter_media_comments(result.comments)],
            [6844, 6845, 6846, 6847],
        )

    def test_download_prepared_messages_preserves_planned_later_caption_for_package_naming_context(
        self,
    ):
        from media_downloader import download_prepared_messages
        from module.comment_workflow import (
            NamingStrategy,
            PackageNamingContext,
            plan_message_package,
        )

        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        app.temp_save_path = os.path.join(MOCK_DIR, "temp")
        app.file_path_prefix = ["chat_title", "media_datetime"]
        app.file_name_prefix = ["message_id", "file_name"]
        app.file_name_prefix_split = " - "

        messages = [
            MockMessage(
                id=100,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="ep-01.mp4", mime_type="video/mp4"),
                caption="课程 第01章 01_40",
                date=datetime(2026, 6, 7),
            ),
            MockMessage(
                id=101,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="ep-02.mp4", mime_type="video/mp4"),
                caption="课程 第01章 02_40",
                date=datetime(2026, 6, 7),
            ),
            MockMessage(
                id=102,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="ep-03.mp4", mime_type="video/mp4"),
                date=datetime(2026, 6, 7),
            ),
        ]
        package_plan = plan_message_package(messages, start_message_id=100)

        for strategy, expected_suffix in (
            (
                NamingStrategy.CAPTION,
                "课程 第01章 01_40/102 - 课程 第01章 02_40 - ep-03.mp4",
            ),
            (
                NamingStrategy.MONTH_CAPTION,
                "私密频道/2026_06/课程 第01章 01_40/102 - 课程 第01章 02_40.mp4",
            ),
        ):
            with self.subTest(strategy=strategy):
                node = TaskNode(chat_id=-1001, bot=None, task_id=11)
                node.is_running = True
                node.package_naming_context = PackageNamingContext(
                    strategy=strategy,
                    channel="私密频道",
                    start_message_id=100,
                    package_title=package_plan.package_title,
                )
                node.package_media_items = {
                    item.message.id: item for item in package_plan.items
                }
                generated_names = []

                async def fake_add_download_task(message, task_node):
                    file_name, _temp_file_name, _file_format = await _get_media_meta(
                        -1001,
                        message,
                        message.video,
                        "video",
                        node=task_node,
                    )
                    generated_names.append(file_name)
                    task_node.total_task += 1
                    task_node.total_download_task += 1
                    task_node.success_download_task += 1
                    task_node.download_status[message.id] = DownloadStatus.SuccessDownload
                    return True

                async def fake_report_bot_status(bot, task_node):
                    return None

                async def fake_sleep(seconds):
                    raise AssertionError(
                        "download_prepared_messages should not wait after queued success"
                    )

                with mock.patch(
                    "media_downloader.add_download_task", new=fake_add_download_task
                ), mock.patch(
                    "module.pyrogram_extension.report_bot_status",
                    new=fake_report_bot_status,
                ), mock.patch(
                    "module.download_stat.remove_active_task_node"
                ), mock.patch(
                    "media_downloader.asyncio.sleep", new=fake_sleep
                ):
                    self.loop.run_until_complete(
                        download_prepared_messages(
                            messages,
                            download_filter="",
                            node=node,
                        )
                    )

                self.assertTrue(
                    generated_names[-1].endswith(platform_generic_path(expected_suffix))
                )
                self.assertEqual(
                    node.package_media_items[102].caption_for_naming,
                    "课程 第01章 02_40",
                )

    def test_download_prepared_messages_counts_scan_failures_in_progress_totals(self):
        from media_downloader import download_prepared_messages

        rest_app(MOCK_CONF)
        messages = [
            MockMessage(
                id=201,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="clip-a.mp4", mime_type="video/mp4"),
            ),
            MockMessage(
                id=202,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="clip-b.mp4", mime_type="video/mp4"),
            ),
        ]
        node = TaskNode(chat_id=-1001, bot=None, task_id=12)
        node.is_running = True
        report_calls = []

        async def fake_add_download_task(message, task_node):
            task_node.total_task += 1
            task_node.total_download_task += 1
            task_node.success_download_task += 1
            task_node.download_status[message.id] = DownloadStatus.SuccessDownload
            return True

        async def fake_report_bot_status(bot, task_node):
            report_calls.append(
                (
                    task_node.success_download_task,
                    task_node.failed_download_task,
                    task_node.total_download_task,
                    list(task_node.failed_tasks),
                )
            )

        async def fake_sleep(seconds):
            raise AssertionError(
                "download_prepared_messages should not sleep after all expected tasks finish"
            )

        with mock.patch(
            "media_downloader.add_download_task", new=fake_add_download_task
        ), mock.patch(
            "module.pyrogram_extension.report_bot_status", new=fake_report_bot_status
        ), mock.patch(
            "module.download_stat.remove_active_task_node"
        ), mock.patch(
            "media_downloader.asyncio.sleep", new=fake_sleep
        ):
            self.loop.run_until_complete(
                download_prepared_messages(
                    messages,
                    download_filter="",
                    node=node,
                    failed_message_ids=[203],
                )
            )

        self.assertEqual(node.failed_download_task, 1)
        self.assertEqual(node.success_download_task, 2)
        self.assertEqual(node.total_download_task, 3)
        self.assertEqual(node.total_task, 3)
        self.assertEqual(node.failed_tasks, [(-1001, 203, None)])
        self.assertTrue(report_calls)
        self.assertEqual(report_calls[-1][:3], (2, 1, 3))

    def test_download_prepared_messages_counts_false_enqueue_as_failed_task(self):
        from media_downloader import download_prepared_messages

        rest_app(MOCK_CONF)
        messages = [
            MockMessage(
                id=301,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="clip-a.mp4", mime_type="video/mp4"),
            )
        ]
        node = TaskNode(chat_id=-1001, bot=None, task_id=13)
        node.is_running = True
        report_calls = []

        async def fake_add_download_task(message, task_node):
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
            raise AssertionError(
                "download_prepared_messages should not sleep after enqueue failure"
            )

        with mock.patch(
            "media_downloader.add_download_task", new=fake_add_download_task
        ), mock.patch(
            "module.pyrogram_extension.report_bot_status", new=fake_report_bot_status
        ), mock.patch(
            "module.download_stat.remove_active_task_node"
        ), mock.patch(
            "media_downloader.asyncio.sleep", new=fake_sleep
        ):
            self.loop.run_until_complete(
                download_prepared_messages(
                    messages,
                    download_filter="",
                    node=node,
                )
            )

        self.assertEqual(node.failed_download_task, 1)
        self.assertEqual(node.success_download_task, 0)
        self.assertEqual(node.total_download_task, 1)
        self.assertEqual(node.total_task, 1)
        self.assertTrue(report_calls)
        self.assertEqual(report_calls[-1], (0, 1, 1))

    def test_download_prepared_messages_filter_queues_only_matching_media(self):
        import media_downloader
        from media_downloader import download_prepared_messages

        rest_app(MOCK_CONF)
        messages = [
            MockMessage(
                id=401,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="clip-a.mp4", mime_type="video/mp4"),
                caption="keep",
            ),
            MockMessage(
                id=402,
                chat_id=-1001,
                chat_title="Private",
                media="video",
                video=MockVideo(file_name="clip-b.mp4", mime_type="video/mp4"),
                caption="drop",
            ),
            MockMessage(id=403, chat_id=-1001, chat_title="Private", text="skip"),
        ]
        node = TaskNode(chat_id=-1001, bot=None, task_id=14)
        node.is_running = True
        queued_ids = []

        def fake_exec_filter(config, meta_data):
            return meta_data.caption == "keep"

        def fake_set_meta_data(meta_data, message, caption):
            meta_data.caption = caption

        async def fake_add_download_task(message, task_node):
            queued_ids.append(message.id)
            task_node.total_task += 1
            task_node.total_download_task += 1
            task_node.success_download_task += 1
            task_node.download_status[message.id] = DownloadStatus.SuccessDownload
            return True

        async def fake_report_bot_status(bot, task_node):
            return None

        async def fake_sleep(seconds):
            raise AssertionError(
                "download_prepared_messages should not wait after filtered success"
            )

        with mock.patch.object(
            media_downloader.app, "exec_filter", new=fake_exec_filter
        ), mock.patch(
            "media_downloader.add_download_task", new=fake_add_download_task
        ), mock.patch(
            "module.pyrogram_extension.set_meta_data", new=fake_set_meta_data
        ), mock.patch(
            "module.pyrogram_extension.report_bot_status", new=fake_report_bot_status
        ), mock.patch(
            "module.download_stat.remove_active_task_node"
        ), mock.patch(
            "media_downloader.asyncio.sleep", new=fake_sleep
        ):
            self.loop.run_until_complete(
                download_prepared_messages(
                    messages,
                    download_filter="caption == keep",
                    node=node,
                )
            )

        self.assertEqual(queued_ids, [401])
        self.assertEqual(node.success_download_task, 1)
        self.assertEqual(node.total_download_task, 1)

    @mock.patch("media_downloader.app.save_path", new=MOCK_DIR)
    @mock.patch("media_downloader.asyncio.sleep", return_value=None)
    @mock.patch("media_downloader.logger")
    @mock.patch("media_downloader._is_exist", new=is_exist)
    @mock.patch(
        "media_downloader._move_to_download_path", new=mock_move_to_download_path
    )
    @mock.patch(
        "media_downloader._check_download_finish", new=mock_check_download_finish
    )
    def test_download_media(self, mock_logger, patch_sleep):
        reset_download_cache()
        rest_app(MOCK_CONF)
        client = MockClient()
        app.hide_file_name = True
        message = MockMessage(
            id=5,
            media=True,
            video=MockVideo(
                file_name="sample_video.mp4",
                mime_type="video/mp4",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["mp4"]}, -123
            )
        )
        self.assertEqual(
            (
                DownloadStatus.SuccessDownload,
                platform_generic_path("/root/project/-123/0/5 - sample_video.mp4"),
            ),
            result,
        )

        message = MockMessage(
            id=6,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual(
            (
                DownloadStatus.SuccessDownload,
                platform_generic_path("/root/project/-123/0/6 - sample_video.mov"),
            ),
            result,
        )

        # Test re-fetch message success
        message = MockMessage(
            id=7,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)
        mock_logger.warning.assert_called_with(
            "Message[7]: file reference expired, refetching..."
        )

        # Test re-fetch message failure
        message = MockMessage(
            id=8,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)
        mock_logger.error.assert_called_with(
            "Message[8]: file reference expired for 3 retries, download skipped."
        )

        # Test other exception
        message = MockMessage(
            id=9,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)

        # Check no media
        message = MockMessage(
            id=10,
            media=None,
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.SkipDownload, None), result)

        # Test timeout
        message = MockMessage(
            id=11,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)
        mock_logger.error.assert_called_with(
            "Message[11]: Timing out after 3 reties, download skipped."
        )

        # Test file name with out suffix
        message = MockMessage(
            id=12,
            media=True,
            video=MockVideo(
                file_name="sample_video",
                mime_type="video/mp4",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual(
            (
                DownloadStatus.SuccessDownload,
                platform_generic_path("/root/project/-123/0/12 - sample_video.mp4"),
            ),
            result,
        )

        # Test FloodWait 420
        message = MockMessage(
            id=420,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)
        mock_logger.warning.assert_called_with("Message[{}]: FlowWait {}", 420, 420)

        # Test other Exception
        message = MockMessage(
            id=421,
            media=True,
            video=MockVideo(
                file_name="sample_video.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)

        # Test other Exception
        message = MockMessage(
            id=422,
            media=True,
            video=MockVideo(
                file_name="422 - exception.mov",
                mime_type="video/mov",
            ),
        )
        result = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["all"]}
            )
        )
        self.assertEqual((DownloadStatus.FailedDownload, None), result)

    @mock.patch("media_downloader.HookClient", new=MockClient)
    @mock.patch("media_downloader.asyncio.Queue.put")
    def test_download_task(self, moc_put):
        rest_app(MOCK_CONF)
        client = MockClient()
        app.chat_download_config[8654123].download_filter = "id != 1213"
        self.loop.run_until_complete(download_all_chat(client))
        moc_put.assert_called()

    def test_can_download(self):
        file_formats = {
            "audio": ["mp3"],
            "video": ["mp4"],
            "document": ["all"],
        }
        result = _can_download("audio", file_formats, "mp3")
        self.assertEqual(result, True)

        result1 = _can_download("audio", file_formats, "ogg")
        self.assertEqual(result1, False)

        result2 = _can_download("document", file_formats, "pdf")
        self.assertEqual(result2, True)

        result3 = _can_download("document", file_formats, "epub")
        self.assertEqual(result3, True)

    def test_is_exist(self):
        this_dir = os.path.dirname(os.path.abspath(__file__))
        result = _is_exist(os.path.join(this_dir, "__init__.py"))
        self.assertEqual(result, True)

        result1 = _is_exist(os.path.join(this_dir, "init.py"))
        self.assertEqual(result1, False)

        result2 = _is_exist(this_dir)
        self.assertEqual(result2, False)

    @mock.patch("media_downloader.os.makedirs")
    @mock.patch("builtins.open", new_callable=mock.mock_open)
    def test_save_msg_to_file(self, mock_open, mock_makedirs):
        rest_app(MOCK_CONF)
        app.enable_download_txt = True
        app.temp_save_path = "/tmp"
        app.date_format = "%Y_%m"

        message = MockMessage(
            id=123,
            dis_chat=True,
            chat=Chat(chat_id=456, chat_title="Test Chat"),
            date=datetime(2023, 5, 15, 10, 30, 0),
            text="This is a test message",
        )

        expected_file_path = platform_generic_path(
            "/root/project/Test Chat/2023_05/123.txt"
        )

        result = self.loop.run_until_complete(save_msg_to_file(app, 456, message))

        self.assertEqual(result, (DownloadStatus.SuccessDownload, expected_file_path))
        mock_makedirs.assert_called_once_with(
            os.path.dirname(expected_file_path), exist_ok=True
        )
        mock_open.assert_called_once_with(expected_file_path, "w", encoding="utf-8")
        mock_open().write.assert_called_once_with("This is a test message")

    @mock.patch("media_downloader.RETRY_TIME_OUT", new=0)
    @mock.patch("media_downloader.os.path.getsize", new=os_get_file_size)
    @mock.patch("media_downloader.os.remove", new=os_remove)
    @mock.patch("media_downloader._is_exist", new=is_exist)
    @mock.patch(
        "media_downloader._move_to_download_path", new=mock_move_to_download_path
    )
    def test_issues_311(self):
        # see https://github.com/Dineshkarthik/telegram_media_downloader/issues/311
        rest_app(MOCK_CONF)

        client = MockClient()
        # 1. test `TimeOutError`
        message = MockMessage(
            id=311,
            media=True,
            video=MockVideo(
                file_name="failed_down.mp4",
                mime_type="video/mp4",
                file_size=1024,
            ),
        )

        media_size = getattr(message.video, "file_size")
        self.assertEqual(media_size, 1024)

        res = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["mp4"]}
            )
        )
        self.assertEqual(res, (DownloadStatus.FailedDownload, None))

        # 2. test sucess download
        rest_app(MOCK_CONF)
        message = MockMessage(
            id=312,
            media=True,
            video=MockVideo(
                file_name="sucess_down.mp4",
                mime_type="video/mp4",
                file_size=1024,
            ),
        )

        res = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["mp4"]}
            )
        )

        self.assertEqual(
            res,
            (
                DownloadStatus.SuccessDownload,
                platform_generic_path("/root/project/-123/0/312 - sucess_down.mp4"),
            ),
        )

        rest_app(MOCK_CONF)
        # 3. test already download
        message = MockMessage(
            id=313,
            media=True,
            video=MockVideo(
                file_name="sucess_exist_down.mp4",
                mime_type="video/mp4",
                file_size=1024,
            ),
        )

        res = self.loop.run_until_complete(
            async_download_media(
                client, message, ["video", "photo"], {"video": ["mp4"]}
            )
        )

        self.assertEqual(res, (DownloadStatus.SkipDownload, None))

    @mock.patch("media_downloader.HookClient", new=MockClient)
    @mock.patch("media_downloader.RETRY_TIME_OUT", new=1)
    @mock.patch("media_downloader.logger")
    def test_main_with_bot(self, mock_logger):
        rest_app(MOCK_CONF)

        main()

        mock_logger.success.assert_called_with(
            "Updated last read message_id to config file,total download 0, total upload file 0"
        )

    @mock.patch("media_downloader.app.pre_run", new=raise_keyboard_interrupt)
    @mock.patch("media_downloader.HookClient", new=MockClient)
    @mock.patch("media_downloader.RETRY_TIME_OUT", new=1)
    @mock.patch("media_downloader.logger")
    def test_keyboard_interrupt(self, mock_logger):
        rest_app(MOCK_CONF)

        main()

        mock_logger.info.assert_any_call("KeyboardInterrupt")
        mock_logger.success.assert_called_with(
            "Updated last read message_id to config file,total download 0, total upload file 0"
        )

    @mock.patch("media_downloader.app.pre_run", new=raise_exception)
    @mock.patch("media_downloader.HookClient", new=MockClient)
    @mock.patch("media_downloader.RETRY_TIME_OUT", new=1)
    @mock.patch("media_downloader.logger")
    def test_other_exception(self, mock_logger):
        rest_app(MOCK_CONF)

        main()

        mock_logger.success.assert_called_with(
            "Updated last read message_id to config file,total download 0, total upload file 0"
        )

    @mock.patch("media_downloader._load_config", new=load_config)
    @mock.patch("media_downloader.logger")
    def test_check_config(self, mock_logger):
        _check_config()
        mock_logger.exception.assert_called_with("load config error: error load config")

    def test_check_config_suc(self):
        app.update_config()
        self.assertEqual(_check_config(), True)

    def test_sanitize_monitor_cfg_masks_webhook_url(self):
        cfg = {
            "enabled": True,
            "chats": [8654123],
            "webhook_url": "https://discord.com/api/webhooks/111222333/secret-token",
        }
        safe = _sanitize_monitor_cfg(cfg)
        self.assertEqual(safe["webhook_url"], "https://discord.com/***")
        self.assertNotIn("secret-token", str(safe))
        # 其他键保持原样，且不修改原配置
        self.assertEqual(safe["enabled"], True)
        self.assertEqual(safe["chats"], [8654123])
        self.assertEqual(
            cfg["webhook_url"],
            "https://discord.com/api/webhooks/111222333/secret-token",
        )
        # 解析不出 scheme+host 时整体脱敏，不回显原值
        self.assertEqual(
            _sanitize_monitor_cfg(
                {"webhook_url": "discord.com/api/webhooks/1/tok"}
            )["webhook_url"],
            "***",
        )

    def test_sanitize_monitor_cfg_without_webhook_url(self):
        self.assertEqual(
            _sanitize_monitor_cfg({"enabled": False}), {"enabled": False}
        )
        self.assertEqual(
            _sanitize_monitor_cfg({"enabled": True, "webhook_url": None}),
            {"enabled": True, "webhook_url": None},
        )

    def test_add_download_task_releases_intent_when_queue_put_fails(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        class FailingQueue:
            @staticmethod
            def qsize():
                return 0

            async def put(self, _item):
                raise RuntimeError("queue unavailable")

        async def scenario():
            gate = TelegramActivityGate()
            message = MockMessage(id=701, media=True)
            node = TaskNode(chat_id=-1001)
            with mock.patch.object(media_downloader, "queue", FailingQueue()), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ):
                result = await media_downloader.add_download_task(message, node)

            self.assertFalse(result)
            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_add_download_task_cancellation_releases_pending_intent(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        class BlockingQueue:
            def __init__(self):
                self.put_started = asyncio.Event()

            @staticmethod
            def qsize():
                return 0

            async def put(self, _item):
                self.put_started.set()
                await asyncio.Future()

        async def scenario():
            gate = TelegramActivityGate()
            blocking_queue = BlockingQueue()
            with mock.patch.object(
                media_downloader, "queue", blocking_queue
            ), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ):
                enqueue_task = asyncio.create_task(
                    media_downloader.add_download_task(
                        MockMessage(id=707, media=True), TaskNode(chat_id=-1001)
                    )
                )
                await blocking_queue.put_started.wait()
                enqueue_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await enqueue_task

            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_stopped_queue_item_cancels_registered_download_intent(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            gate = TelegramActivityGate()
            test_queue = asyncio.Queue()
            node = TaskNode(chat_id=-1001)
            node.stop_transmission()
            intent = await gate.register_download_intent()
            await test_queue.put((MockMessage(id=702, media=True), node, intent))

            with mock.patch.object(media_downloader, "queue", test_queue), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ):
                worker_task = asyncio.create_task(media_downloader.worker(MockClient()))
                await asyncio.wait_for(test_queue.join(), 1)
                await gate.wait_until_idle()
                worker_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker_task

            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_worker_cancellation_releases_active_download_intent(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            gate = TelegramActivityGate()
            test_queue = asyncio.Queue()
            entered_download = asyncio.Event()

            async def blocked_download_task(
                _client, _message, _node, telegram_permit=None
            ):
                self.assertIsNotNone(telegram_permit)
                entered_download.set()
                await asyncio.Future()

            with mock.patch.object(media_downloader, "queue", test_queue), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ), mock.patch.object(
                media_downloader, "download_task", new=blocked_download_task
            ):
                queued = await media_downloader.add_download_task(
                    MockMessage(id=703, media=True), TaskNode(chat_id=-1001)
                )
                self.assertTrue(queued)
                worker_task = asyncio.create_task(media_downloader.worker(MockClient()))
                await entered_download.wait()
                worker_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker_task

            await gate.wait_until_idle()
            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_worker_exception_releases_active_download_intent(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            gate = TelegramActivityGate()
            test_queue = asyncio.Queue()
            original_sleep = asyncio.sleep

            async def failed_download_task(
                _client, _message, _node, telegram_permit=None
            ):
                self.assertIsNotNone(telegram_permit)
                raise RuntimeError("download failed")

            async def yield_without_delay(_seconds):
                await original_sleep(0)

            with mock.patch.object(media_downloader, "queue", test_queue), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ), mock.patch.object(
                media_downloader, "download_task", new=failed_download_task
            ), mock.patch.object(
                media_downloader.asyncio, "sleep", new=yield_without_delay
            ):
                queued = await media_downloader.add_download_task(
                    MockMessage(id=704, media=True), TaskNode(chat_id=-1001)
                )
                self.assertTrue(queued)
                worker_task = asyncio.create_task(media_downloader.worker(MockClient()))
                await asyncio.wait_for(test_queue.join(), 1)
                await gate.wait_until_idle()
                worker_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker_task

            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_worker_accepts_legacy_queue_item_and_gates_telegram_work(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            gate = TelegramActivityGate()
            test_queue = asyncio.Queue()
            started = asyncio.Event()

            async def successful_download_task(
                _client, _message, _node, telegram_permit=None
            ):
                self.assertIsNotNone(telegram_permit)
                started.set()

            await test_queue.put(
                (MockMessage(id=705, media=True), TaskNode(chat_id=-1001))
            )
            scan = await gate.acquire_scan()
            with mock.patch.object(media_downloader, "queue", test_queue), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ), mock.patch.object(
                media_downloader, "download_task", new=successful_download_task
            ):
                worker_task = asyncio.create_task(media_downloader.worker(MockClient()))
                await asyncio.sleep(0)
                self.assertFalse(started.is_set())
                scan.release()
                await asyncio.wait_for(started.wait(), 1)
                await asyncio.wait_for(test_queue.join(), 1)
                await gate.wait_until_idle()
                worker_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker_task

        self.loop.run_until_complete(scenario())

    def test_worker_binds_naming_snapshot_through_download_media_to_media_meta(self):
        import media_downloader
        from module.comment_workflow import NamingStrategy, PackageNamingContext
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            rest_app(MOCK_CONF)
            app.save_path = MOCK_DIR

            gate = TelegramActivityGate()
            test_queue = asyncio.Queue()

            node = TaskNode(chat_id=-1001)
            node.package_naming_context = PackageNamingContext(
                strategy=NamingStrategy.RECOMMENDED,
                channel="ch",
                start_message_id=111,
                package_title="P1",
            )
            node.package_media_items = {}

            message = MockMessage(
                id=126711,
                chat_id=-1001,
                media="video",
                video=MockVideo(file_name="a.mp4", mime_type="video/mp4"),
                caption="c",
            )

            with mock.patch.object(
                media_downloader, "queue", test_queue
            ), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ):
                queued = await media_downloader.add_download_task(message, node)
            self.assertTrue(queued)

            # 模拟 stray/leftover 场景：条目入队后，node 被复用于下一个包（P2）。
            # 队列条目已经绑定了 P1 的命名快照，处理时不应受此影响。
            node.package_naming_context = PackageNamingContext(
                strategy=NamingStrategy.RECOMMENDED,
                channel="ch",
                start_message_id=222,
                package_title="P2",
            )

            captured = {}
            real_get_media_meta = media_downloader._get_media_meta

            async def spy_get_media_meta(*args, **kwargs):
                captured["naming_snapshot"] = kwargs.get("naming_snapshot")
                result = await real_get_media_meta(*args, **kwargs)
                captured["file_name"] = result[0]
                # 拿到需要的数据后中断，避免真的走到网络下载逻辑
                raise RuntimeError("stop-after-capture")

            with mock.patch.object(
                media_downloader, "queue", test_queue
            ), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ), mock.patch.object(
                media_downloader, "_get_media_meta", new=spy_get_media_meta
            ):
                worker_task = asyncio.create_task(media_downloader.worker(MockClient()))
                await asyncio.wait_for(test_queue.join(), 1)
                await gate.wait_until_idle()
                worker_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker_task

            self.assertIsNotNone(captured.get("naming_snapshot"))
            self.assertEqual(
                captured["naming_snapshot"]["context"].start_message_id, 111
            )
            self.assertIn("111-", captured["file_name"])
            self.assertNotIn("222-", captured["file_name"])

            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_worker_legacy_three_tuple_falls_back_to_node_package_naming_context(self):
        import media_downloader
        from module.comment_workflow import NamingStrategy, PackageNamingContext
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            rest_app(MOCK_CONF)
            app.save_path = MOCK_DIR

            gate = TelegramActivityGate()
            test_queue = asyncio.Queue()

            node = TaskNode(chat_id=-1001)
            node.package_naming_context = PackageNamingContext(
                strategy=NamingStrategy.RECOMMENDED,
                channel="ch",
                start_message_id=333,
                package_title="P3",
            )
            node.package_media_items = {}

            message = MockMessage(
                id=999,
                chat_id=-1001,
                media="video",
                video=MockVideo(file_name="a.mp4", mime_type="video/mp4"),
                caption="c",
            )

            # 手动构造遗留 3 元组（无命名快照），worker 必须继续兼容
            intent = await gate.register_download_intent()
            await test_queue.put((message, node, intent))

            captured = {}
            real_get_media_meta = media_downloader._get_media_meta

            async def spy_get_media_meta(*args, **kwargs):
                captured["naming_snapshot"] = kwargs.get("naming_snapshot")
                result = await real_get_media_meta(*args, **kwargs)
                captured["file_name"] = result[0]
                raise RuntimeError("stop-after-capture")

            with mock.patch.object(
                media_downloader, "queue", test_queue
            ), mock.patch.object(
                media_downloader, "get_telegram_activity_gate", return_value=gate
            ), mock.patch.object(
                media_downloader, "_get_media_meta", new=spy_get_media_meta
            ):
                worker_task = asyncio.create_task(media_downloader.worker(MockClient()))
                await asyncio.wait_for(test_queue.join(), 1)
                await gate.wait_until_idle()
                worker_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker_task

            # 无快照时，退回到 node.package_naming_context（P3）
            self.assertIsNone(captured.get("naming_snapshot"))
            self.assertIn("333-", captured["file_name"])

            scan = await asyncio.wait_for(gate.acquire_scan(), 1)
            scan.release()
            await gate.wait_until_idle()

        self.loop.run_until_complete(scenario())

    def test_cloud_upload_starts_after_telegram_permit_is_released(self):
        import media_downloader
        from module.telegram_activity import TelegramActivityGate

        async def scenario():
            rest_app(MOCK_CONF)
            app.cloud_drive_config.enable_upload_file = True
            gate = TelegramActivityGate()
            permit = await gate.acquire_download()
            scan_acquired = asyncio.Event()
            cloud_upload_called = False
            cloud_started_before_scan = False
            message = MockMessage(id=706, media=True)
            node = TaskNode(chat_id=-1001)

            async def acquire_waiting_scan():
                scan = await gate.acquire_scan()
                scan_acquired.set()
                scan.release()

            scan_task = asyncio.create_task(acquire_waiting_scan())
            await asyncio.sleep(0)

            async def fake_download_media(*_args, **_kwargs):
                return DownloadStatus.SuccessDownload, "/tmp/telegram-media.bin"

            async def fake_telegram_upload(*_args, **_kwargs):
                return None

            async def fake_cloud_upload(*_args, **_kwargs):
                nonlocal cloud_upload_called, cloud_started_before_scan
                cloud_started_before_scan = not scan_acquired.is_set()
                cloud_upload_called = True
                return True

            async def fake_report(*_args, **_kwargs):
                return None

            with mock.patch.object(
                media_downloader, "download_media", new=fake_download_media
            ), mock.patch.object(
                media_downloader, "upload_telegram_chat", new=fake_telegram_upload
            ), mock.patch.object(
                media_downloader, "report_bot_download_status", new=fake_report
            ), mock.patch.object(
                media_downloader.app, "upload_file", new=fake_cloud_upload
            ), mock.patch.object(
                media_downloader.app, "set_download_id"
            ), mock.patch.object(
                media_downloader.os.path, "exists", return_value=True
            ), mock.patch.object(
                media_downloader.os.path, "getsize", return_value=1
            ):
                await media_downloader.download_task(
                    MockClient(), message, node, telegram_permit=permit
                )

            await asyncio.wait_for(scan_task, 1)
            await gate.wait_until_idle()
            self.assertTrue(cloud_upload_called)
            self.assertFalse(cloud_started_before_scan)

        self.loop.run_until_complete(scenario())

    # @mock.patch(
    #     "media_downloader.queue",
    #     new=MyQueue(
    #         [
    #             (
    #                 MockMessage(
    #                     id=312,
    #                     media=True,
    #                     chat_id=8654123,
    #                     chat_title="8654123",
    #                     video=MockVideo(
    #                         file_name="sucess_down.mp4",
    #                         mime_type="video/mp4",
    #                         file_size=1024,
    #                     ),
    #                 ),
    #                 TaskNode(chat_id=8654123, upload_telegram_chat_id=123456),
    #             ),
    #             (
    #                 MockMessage(
    #                     id=333,
    #                     media=True,
    #                     chat_id=8654123,
    #                     chat_title="8654123",
    #                     text="123",
    #                 ),
    #                 TaskNode(chat_id=8654123, upload_telegram_chat_id=123456),
    #             ),
    #         ]
    #     ),
    # )
    # @mock.patch("media_downloader.app.set_download_id", new=new_set_download_id)
    # @mock.patch("media_downloader.upload_telegram_chat", new=new_upload_telegram_chat)
    # @mock.patch("media_downloader.os.remove")
    # @mock.patch(
    #     "media_downloader._move_to_download_path", new=mock_move_to_download_path
    # )
    # @mock.patch("media_downloader.os.path.getsize", new=os_get_file_size)
    # def test_upload_telegram_chat(self, mock_remove):
    #     rest_app(MOCK_CONF)
    #     client = MockClient()
    #     app.chat_download_config[8654123].last_read_message_id = 0
    #     self.loop.run_until_complete(worker(client))
    #     mock_remove.assert_called_with(
    #         platform_generic_path("/root/project/8654123/0/312 - sucess_down.mp4")
    #     )

    def test_download_prescan_packages_manages_parent_once_and_reports_package_results(self):
        import media_downloader
        import module.task_state as task_state_module

        from module.comment_workflow import plan_message_package
        from module.download_stat import (
            add_active_task_node,
            get_active_task_nodes,
            remove_active_task_node,
        )
        from module.prescan_workflow import PrescanPackage
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        messages = [
            MockMessage(
                id=message_id,
                media="video",
                caption=f"Lesson {index}",
                video=MockVideo(file_name=f"{index}.mp4", mime_type="video/mp4"),
            )
            for index, message_id in enumerate((101, 202), start=1)
        ]
        packages = []
        for package_id, message in zip((11, 22), messages):
            plan = plan_message_package([message], message.id)
            package = PrescanPackage(
                package_id,
                message.caption,
                message.id,
                message.id,
                plan.items,
                plan,
                [message],
            )
            package.attempt_id = f"attempt-{package_id}"
            packages.append(package)

        with tempfile.TemporaryDirectory() as tmp_dir:
            real_store = TaskStateStore(storage_path=Path(tmp_dir) / "tasks.sqlite3")
            node = TaskNode(chat_id=-1001, bot=None, task_id="channel-batch-fixed")
            node.client = object()
            callbacks = []
            lifecycle = []

            async def fake_add_download_task(message, package_node):
                package_node.total_task += 1
                package_node.total_download_task += 1
                package_node.download_status[message.id] = DownloadStatus.SuccessDownload
                package_node.stat(
                    DownloadStatus.SuccessDownload,
                    package_node.chat_id,
                    message.id,
                    f"/{message.id}.mp4",
                )
                real_store.upsert_file(
                    package_node.task_id,
                    message.id,
                    status=FileStatus.DOWNLOADED,
                    filename=f"/{message.id}.mp4",
                )
                return True

            async def fake_report(*_args, **_kwargs):
                return None

            async def on_package_started(attempt_id, package):
                callbacks.append(("started", attempt_id, package.package_id))

            async def on_package_finished(attempt_id, message_results):
                snapshot = real_store.get_task(node.task_id)
                callbacks.append(
                    (
                        "finished",
                        attempt_id,
                        tuple(message_results),
                        snapshot.status,
                    )
                )

            def tracked_add(active_node, *args, **kwargs):
                lifecycle.append("add")
                return add_active_task_node(active_node, *args, **kwargs)

            def tracked_remove(task_id):
                lifecycle.append("remove")
                return remove_active_task_node(task_id)

            old_store = task_state_module._TASK_STORE
            task_state_module._TASK_STORE = real_store
            try:
                with mock.patch.object(
                    media_downloader, "add_download_task", new=fake_add_download_task
                ), mock.patch(
                    "module.pyrogram_extension.report_bot_status", new=fake_report
                ), mock.patch(
                    "module.download_stat.add_active_task_node", new=tracked_add
                ), mock.patch(
                    "module.download_stat.remove_active_task_node", new=tracked_remove
                ):
                    results = self.loop.run_until_complete(
                        media_downloader.download_prescan_packages(
                            packages,
                            channel="Course",
                            parent_node=node,
                            selected_package_ids={11, 22},
                            on_package_started=on_package_started,
                            on_package_finished=on_package_finished,
                        )
                    )
            finally:
                task_state_module._TASK_STORE = old_store
                get_active_task_nodes().pop(node.task_id, None)

            self.assertEqual(lifecycle, ["add", "remove"])
            self.assertEqual(
                [result.status for result in results], ["completed", "completed"]
            )
            self.assertEqual(
                callbacks,
                [
                    ("started", "attempt-11", 11),
                    ("finished", "attempt-11", (101,), TaskStatus.DOWNLOADING),
                    ("started", "attempt-22", 22),
                    ("finished", "attempt-22", (202,), TaskStatus.DOWNLOADING),
                ],
            )
            self.assertEqual(
                real_store.get_task(node.task_id).status, TaskStatus.COMPLETED
            )

    def test_download_prescan_packages_materializes_each_package_lazily_with_prepare_hook(self):
        import media_downloader
        import module.task_state as task_state_module

        from types import SimpleNamespace

        from module.comment_workflow import plan_message_package
        from module.download_stat import get_active_task_nodes
        from module.prescan_workflow import PrescanPackage
        from module.task_state import FileStatus, TaskStateStore

        # Descriptors carry only routing metadata; no messages/items are held.
        descriptors = [
            SimpleNamespace(
                package_id=11,
                start_message_id=101,
                title="Lesson 1",
                attempt_id="attempt-11",
            ),
            SimpleNamespace(
                package_id=22,
                start_message_id=202,
                title="Lesson 2",
                attempt_id="attempt-22",
            ),
        ]
        events = []
        live = {"count": 0, "max": 0}

        with tempfile.TemporaryDirectory() as tmp_dir:
            real_store = TaskStateStore(storage_path=Path(tmp_dir) / "tasks.sqlite3")
            node = TaskNode(chat_id=-1001, bot=None, task_id="channel-batch-stream")
            node.client = object()

            async def prepare_package(descriptor):
                live["count"] += 1
                live["max"] = max(live["max"], live["count"])
                events.append(("prepare", descriptor.package_id))
                message = MockMessage(
                    id=descriptor.start_message_id,
                    media="video",
                    caption=descriptor.title,
                    video=MockVideo(
                        file_name=f"{descriptor.start_message_id}.mp4",
                        mime_type="video/mp4",
                    ),
                )
                plan = plan_message_package([message], message.id)
                package = PrescanPackage(
                    descriptor.package_id,
                    descriptor.title,
                    descriptor.start_message_id,
                    descriptor.start_message_id,
                    plan.items,
                    plan,
                    [message],
                )
                package.attempt_id = descriptor.attempt_id
                return package

            async def fake_add_download_task(message, package_node):
                events.append(("download", message.id))
                package_node.total_task += 1
                package_node.total_download_task += 1
                package_node.download_status[message.id] = DownloadStatus.SuccessDownload
                package_node.stat(
                    DownloadStatus.SuccessDownload,
                    package_node.chat_id,
                    message.id,
                    f"/{message.id}.mp4",
                )
                real_store.upsert_file(
                    package_node.task_id,
                    message.id,
                    status=FileStatus.DOWNLOADED,
                    filename=f"/{message.id}.mp4",
                )
                live["count"] -= 1
                return True

            async def fake_report(*_args, **_kwargs):
                return None

            old_store = task_state_module._TASK_STORE
            task_state_module._TASK_STORE = real_store
            try:
                with mock.patch.object(
                    media_downloader, "add_download_task", new=fake_add_download_task
                ), mock.patch(
                    "module.pyrogram_extension.report_bot_status", new=fake_report
                ):
                    results = self.loop.run_until_complete(
                        media_downloader.download_prescan_packages(
                            descriptors,
                            channel="Course",
                            parent_node=node,
                            selected_package_ids={11, 22},
                            prepare_package=prepare_package,
                        )
                    )
            finally:
                task_state_module._TASK_STORE = old_store
                get_active_task_nodes().pop(node.task_id, None)

            # Each package is built immediately before its own download, so only
            # one package is ever materialized at a time.
            self.assertEqual(live["max"], 1)
            self.assertEqual(
                events,
                [
                    ("prepare", 11),
                    ("download", 101),
                    ("prepare", 22),
                    ("download", 202),
                ],
            )
            self.assertEqual(
                [result.status for result in results], ["completed", "completed"]
            )

    def test_download_prescan_packages_preserves_snapshot_result_order_with_missing_middle(self):
        import media_downloader
        import module.task_state as task_state_module

        from module.comment_workflow import plan_message_package
        from module.download_stat import get_active_task_nodes
        from module.prescan_workflow import PrescanPackage
        from module.task_state import FileStatus, TaskStateStore

        messages = [
            MockMessage(
                id=message_id,
                media="video",
                caption=f"Lesson {message_id}",
                video=MockVideo(file_name=f"{message_id}.mp4", mime_type="video/mp4"),
            )
            for message_id in (1, 3)
        ]
        plan = plan_message_package(messages, 1)
        package = PrescanPackage(
            10,
            "Ordered",
            1,
            3,
            plan.items,
            plan,
            messages,
            failed_message_ids=[2],
            expected_message_ids=[1, 2, 3],
        )
        package.not_found_message_ids = {2}
        callbacks = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            real_store = TaskStateStore(storage_path=Path(tmp_dir) / "tasks.sqlite3")
            node = TaskNode(chat_id=-1001, bot=None, task_id="ordered-snapshot")

            async def fake_download(messages_to_download, _filter, package_node, **_kwargs):
                for message in messages_to_download:
                    real_store.upsert_file(
                        package_node.task_id,
                        message.id,
                        status=FileStatus.DOWNLOADED,
                    )

            async def fake_report(*_args, **_kwargs):
                return None

            async def on_finished(_attempt_id, message_results):
                callbacks.append(tuple(message_results))

            old_store = task_state_module._TASK_STORE
            task_state_module._TASK_STORE = real_store
            try:
                with mock.patch.object(
                    media_downloader,
                    "download_prepared_messages",
                    new=fake_download,
                ), mock.patch(
                    "module.pyrogram_extension.report_bot_status", new=fake_report
                ):
                    results = self.loop.run_until_complete(
                        media_downloader.download_prescan_packages(
                            [package],
                            channel="Course",
                            parent_node=node,
                            selected_package_ids={10},
                            on_package_finished=on_finished,
                        )
                    )
            finally:
                task_state_module._TASK_STORE = old_store
                get_active_task_nodes().pop(node.task_id, None)

        self.assertEqual(results[0].expected_message_ids, (1, 2, 3))
        self.assertEqual(tuple(results[0].message_results), (1, 2, 3))
        self.assertEqual(callbacks, [(1, 2, 3)])

    def test_download_prescan_packages_classifies_package_scoped_outcomes(self):
        import media_downloader
        import module.task_state as task_state_module

        from module.comment_workflow import plan_message_package
        from module.download_stat import get_active_task_nodes
        from module.prescan_workflow import PrescanPackage
        from module.task_state import FileStatus, TaskStateStore

        outcome_by_message = {
            1: FileStatus.DOWNLOADED,
            2: FileStatus.UPLOAD_FAILED,
            3: FileStatus.FAILED,
            4: FileStatus.SKIPPED,
            5: FileStatus.SKIPPED,
        }
        packages = []
        for message_id in range(1, 7):
            message = MockMessage(
                id=message_id,
                media="video",
                caption=f"Lesson {message_id}",
                video=MockVideo(file_name=f"{message_id}.mp4", mime_type="video/mp4"),
            )
            plan = plan_message_package([message], message_id)
            packages.append(
                PrescanPackage(
                    message_id,
                    message.caption,
                    message_id,
                    message_id,
                    plan.items,
                    plan,
                    [message],
                )
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            real_store = TaskStateStore(storage_path=Path(tmp_dir) / "tasks.sqlite3")
            node = TaskNode(chat_id=-1001, bot=None, task_id="channel-batch-results")

            async def fake_download_one(
                messages,
                _download_filter,
                package_node,
                failed_message_ids=None,
                manage_parent_lifecycle=True,
            ):
                message_id = messages[0].id
                if message_id == 6:
                    package_node.stop_transmission()
                    return
                real_store.upsert_file(
                    package_node.task_id,
                    message_id,
                    status=outcome_by_message[message_id],
                )
                if message_id == 4:
                    package_node.skip_not_found_message_ids.add(message_id)
                if message_id == 5:
                    package_node.completed_file_skip_message_ids.add(message_id)

            async def fake_report(*_args, **_kwargs):
                return None

            old_store = task_state_module._TASK_STORE
            task_state_module._TASK_STORE = real_store
            try:
                with mock.patch.object(
                    media_downloader,
                    "download_prepared_messages",
                    new=fake_download_one,
                ), mock.patch(
                    "module.pyrogram_extension.report_bot_status", new=fake_report
                ):
                    results = self.loop.run_until_complete(
                        media_downloader.download_prescan_packages(
                            packages,
                            channel="Course",
                            parent_node=node,
                            selected_package_ids=set(range(1, 7)),
                        )
                    )
            finally:
                task_state_module._TASK_STORE = old_store
                get_active_task_nodes().pop(node.task_id, None)

            self.assertEqual(
                [result.status for result in results],
                [
                    "completed",
                    "upload_failed",
                    "failed",
                    "not_found",
                    "completed",
                    "cancelled",
                ],
            )
            self.assertEqual(
                results[4].message_results[5].status, "completed_file_skip"
            )
            self.assertEqual(results[5].message_results[6].status, "cancelled")

    def test_package_download_complete_waits_for_exact_message_ids(self):
        import media_downloader
        from module.app import DownloadStatus

        class N:
            pass
        node = N()
        node.download_status = {
            101: DownloadStatus.Downloading,
            102: DownloadStatus.SuccessDownload,
        }
        ids = {101, 102}
        # 101 仍在下载中 -> 未完成
        self.assertFalse(media_downloader._package_download_complete(node, ids))
        # 全部终态（含 Failed/Skip）-> 完成
        node.download_status[101] = DownloadStatus.FailedDownload
        self.assertTrue(media_downloader._package_download_complete(node, ids))
        # 缺失的 id 视为未完成
        self.assertFalse(media_downloader._package_download_complete(node, {101, 102, 103}))

    @classmethod
    def tearDownClass(cls):
        cls.loop.close()
