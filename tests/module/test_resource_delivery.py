"""Tests for main-account download and resource-Bot upload delivery."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyrogram import enums

from module.resource_bot_store import ResourceBotStore
from module.resource_delivery import (
    PreparedDeliveryItem,
    ResourceDeliveryService,
    TransferSpeedTracker,
    build_delivery_groups,
    safe_delivery_filename,
)


class NoopActivityGate:
    @asynccontextmanager
    async def download_permit(self):
        yield None


class FakeChannelStore:
    def __init__(self, package=None, items=None):
        self.package = package or {
            "id": 12,
            "index_revision": 3,
            "boundary_status": "stable",
            "title": "Course",
        }
        self.items = list(items or [])

    def get_package(self, package_id):
        if self.package is None or int(package_id) != int(self.package["id"]):
            return None
        return dict(self.package)

    def list_package_items_aggregate(self, package_id, cursor=None, limit=200):
        assert int(package_id) == int(self.package["id"])
        assert limit == 200
        if cursor is not None:
            return SimpleNamespace(items=[], next_cursor=None)
        return SimpleNamespace(items=list(self.items), next_cursor=None)


class FakeMainClient:
    def __init__(self, messages, fail_download_message_id=None):
        self.messages = dict(messages)
        self.fail_download_message_id = fail_download_message_id
        self.get_calls = []
        self.download_calls = []

    async def get_messages(self, chat_id, message_id):
        self.get_calls.append((chat_id, message_id))
        return self.messages.get((chat_id, message_id))

    async def download_media(
        self, message, file_name, progress=None, progress_args=()
    ):
        self.download_calls.append(message.id)
        if message.id == self.fail_download_message_id:
            raise RuntimeError("download failed")
        path = Path(file_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"media-{message.id}".encode("utf-8")
        path.write_bytes(payload)
        if progress is not None:
            await progress(len(payload), len(payload), *progress_args)
        return str(path)


class FakeResourceClient:
    def __init__(self, *, can_post=True, fail_upload_call=None):
        self.me = SimpleNamespace(id=999)
        self.can_post = can_post
        self.fail_upload_call = fail_upload_call
        self.upload_calls = []
        self.notifications = []

    async def get_chat_member(self, chat_id, user_id):
        assert user_id == self.me.id
        return SimpleNamespace(
            status=enums.ChatMemberStatus.ADMINISTRATOR,
            privileges=SimpleNamespace(can_post_messages=self.can_post),
        )

    async def send_media_group(self, chat_id, media):
        await self._record("media_group", chat_id, media)

    async def send_photo(
        self, chat_id, file_name, caption=None, progress=None, progress_args=()
    ):
        if progress is not None:
            await progress(10, 10, *progress_args)
        await self._record("photo", chat_id, file_name, caption)

    async def send_video(
        self, chat_id, file_name, caption=None, progress=None, progress_args=()
    ):
        if progress is not None:
            await progress(10, 10, *progress_args)
        await self._record("video", chat_id, file_name, caption)

    async def send_audio(
        self, chat_id, file_name, caption=None, progress=None, progress_args=()
    ):
        if progress is not None:
            await progress(10, 10, *progress_args)
        await self._record("audio", chat_id, file_name, caption)

    async def send_document(
        self, chat_id, file_name, caption=None, progress=None, progress_args=()
    ):
        if progress is not None:
            await progress(10, 10, *progress_args)
        await self._record("document", chat_id, file_name, caption)

    async def send_voice(
        self, chat_id, file_name, caption=None, progress=None, progress_args=()
    ):
        if progress is not None:
            await progress(10, 10, *progress_args)
        await self._record("voice", chat_id, file_name, caption)

    async def send_video_note(
        self, chat_id, file_name, progress=None, progress_args=()
    ):
        if progress is not None:
            await progress(10, 10, *progress_args)
        await self._record("video_note", chat_id, file_name)

    async def send_message(self, chat_id, text):
        self.notifications.append((chat_id, text))

    async def _record(self, kind, *args):
        call_number = len(self.upload_calls) + 1
        if self.fail_upload_call == call_number:
            raise RuntimeError("upload failed")
        self.upload_calls.append((kind, *args))


def package_item(
    ordinal,
    message_id,
    media_type,
    *,
    media_group_id=None,
    file_name=None,
    caption=None,
):
    return {
        "ordinal": ordinal,
        "message_id": message_id,
        "source_chat_id": -2001,
        "source_message_id": message_id,
        "media_type": media_type,
        "media_group_id": media_group_id,
        "file_name": file_name,
        "mime_type": None,
        "original_caption": caption,
        "caption": caption,
    }


def message(message_id):
    return SimpleNamespace(id=message_id, empty=False)


@pytest.fixture
def resource_store(tmp_path):
    store = ResourceBotStore(tmp_path / "resource_bot.sqlite3")
    store.initialize()
    key = store.create_activation_key(1)
    assert store.redeem_activation_key(key, 200)
    store.bind_channel(200, -1001, "Target", "target")
    return store


def create_job(store, *, package_revision=3, total_items=1, key="action"):
    job, _ = store.create_delivery_job(
        idempotency_key=key,
        user_id=200,
        package_id=12,
        package_revision=package_revision,
        target_chat_id=-1001,
        total_items=total_items,
    )
    return store.claim_next_delivery_job() or job


def make_service(
    tmp_path,
    resource_store,
    channel_store,
    main_client,
    resource_client,
):
    return ResourceDeliveryService(
        SimpleNamespace(),
        main_client,
        resource_client,
        resource_store,
        channel_store,
        temp_root=tmp_path / "deliveries",
        activity_gate=NoopActivityGate(),
        sleep=lambda _seconds: asyncio.sleep(0),
    )


def test_safe_filename_strips_paths_and_prefixes_ordinal():
    item = {
        "ordinal": 2,
        "source_message_id": 30,
        "file_name": "../../secret.mp4",
        "media_type": "video",
        "mime_type": "video/mp4",
    }

    assert safe_delivery_filename(item) == "0002-30-secret.mp4"


def test_safe_filename_uses_media_extension_when_name_is_missing():
    item = {
        "ordinal": 0,
        "source_message_id": 30,
        "file_name": None,
        "media_type": "photo",
        "mime_type": None,
    }

    assert safe_delivery_filename(item) == "0000-30-photo.jpg"


def prepared(ordinal, group_id, media_type):
    return PreparedDeliveryItem(
        ordinal=ordinal,
        source_chat_id=-2001,
        source_message_id=ordinal,
        media_type=media_type,
        media_group_id=group_id,
        caption=None,
        file_name=f"{ordinal}.bin",
    )


def test_delivery_groups_keep_contiguous_album_order():
    items = [
        prepared(1, "album-a", "photo"),
        prepared(2, "album-a", "video"),
        prepared(3, None, "document"),
    ]

    groups = build_delivery_groups(items)

    assert [[item.ordinal for item in group] for group in groups] == [[1, 2], [3]]


def test_incompatible_media_group_falls_back_to_single_items():
    items = [
        prepared(1, "album-a", "voice"),
        prepared(2, "album-a", "video_note"),
    ]

    groups = build_delivery_groups(items)

    assert [[item.ordinal for item in group] for group in groups] == [[1], [2]]


def test_transfer_speed_tracker_throttles_and_reports_terminal_sample():
    samples = []
    ticks = iter([0.0, 0.4, 1.2, 1.5])
    tracker = TransferSpeedTracker(
        samples.append, clock=lambda: next(ticks), interval=1.0
    )

    tracker.observe(100, 1000)
    tracker.observe(400, 1000)
    tracker.observe(800, 1000)
    tracker.observe(1000, 1000)

    assert samples == [666, 666]


def run(coroutine):
    return asyncio.run(coroutine)


def test_delivery_downloads_all_items_then_uploads_with_resource_bot(
    tmp_path, resource_store
):
    async def scenario():
        items = [
            package_item(0, 10, "photo", media_group_id="a", caption="Album"),
            package_item(1, 11, "video", media_group_id="a"),
            package_item(2, 12, "document", file_name="notes.pdf"),
        ]
        channel_store = FakeChannelStore(items=items)
        main_client = FakeMainClient(
            {
                (-2001, item["source_message_id"]): message(
                    item["source_message_id"]
                )
                for item in items
            }
        )
        resource_client = FakeResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store, total_items=3)

        result = await service.process_job(job)

        assert main_client.download_calls == [10, 11, 12]
        assert [call[0] for call in resource_client.upload_calls] == [
            "media_group",
            "document",
        ]
        assert result["status"] == "completed"
        assert result["downloaded_items"] == 3
        assert result["uploaded_items"] == 3
        assert resource_client.notifications[-1][0] == 200
        assert not (tmp_path / "deliveries" / job["public_id"]).exists()

    run(scenario())


def test_download_failure_starts_no_upload_and_cleans_temp(
    tmp_path, resource_store
):
    async def scenario():
        items = [
            package_item(0, 10, "document", file_name="one.bin"),
            package_item(1, 11, "document", file_name="two.bin"),
        ]
        channel_store = FakeChannelStore(items=items)
        main_client = FakeMainClient(
            {(-2001, 10): message(10), (-2001, 11): message(11)},
            fail_download_message_id=11,
        )
        resource_client = FakeResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store, total_items=2)

        result = await service.process_job(job)

        assert resource_client.upload_calls == []
        assert result["status"] == "failed"
        assert result["error_code"] == "download_failed"
        assert not (tmp_path / "deliveries" / job["public_id"]).exists()

    run(scenario())


def test_missing_source_message_fails_before_upload(tmp_path, resource_store):
    async def scenario():
        items = [package_item(0, 10, "photo")]
        channel_store = FakeChannelStore(items=items)
        main_client = FakeMainClient({})
        resource_client = FakeResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store)

        result = await service.process_job(job)

        assert result["error_code"] == "source_message_missing"
        assert main_client.download_calls == []
        assert resource_client.upload_calls == []

    run(scenario())


def test_package_revision_change_prevents_download(tmp_path, resource_store):
    async def scenario():
        channel_store = FakeChannelStore(
            package={
                "id": 12,
                "index_revision": 4,
                "boundary_status": "stable",
                "title": "Changed",
            },
            items=[package_item(0, 10, "photo")],
        )
        main_client = FakeMainClient({(-2001, 10): message(10)})
        resource_client = FakeResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store, package_revision=3)

        result = await service.process_job(job)

        assert result["error_code"] == "package_changed"
        assert main_client.get_calls == []

    run(scenario())


def test_partial_upload_is_reported_without_retry(tmp_path, resource_store):
    async def scenario():
        items = [
            package_item(0, 10, "document", file_name="one.bin"),
            package_item(1, 11, "voice", file_name="two.ogg"),
        ]
        channel_store = FakeChannelStore(items=items)
        main_client = FakeMainClient(
            {(-2001, 10): message(10), (-2001, 11): message(11)}
        )
        resource_client = FakeResourceClient(fail_upload_call=2)
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store, total_items=2)

        result = await service.process_job(job)

        assert len(resource_client.upload_calls) == 1
        assert result["status"] == "failed"
        assert result["error_code"] == "partial_upload"
        assert result["uploaded_items"] == 1

    run(scenario())


def test_target_permission_loss_prevents_download(tmp_path, resource_store):
    async def scenario():
        items = [package_item(0, 10, "photo")]
        channel_store = FakeChannelStore(items=items)
        main_client = FakeMainClient({(-2001, 10): message(10)})
        resource_client = FakeResourceClient(can_post=False)
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store)

        result = await service.process_job(job)

        assert result["error_code"] == "target_permission_lost"
        assert resource_store.get_binding(200)["status"] == "permission_lost"
        assert main_client.get_calls == []

    run(scenario())


def test_revocation_during_download_stops_at_next_item(
    tmp_path, resource_store
):
    class RevokingMainClient(FakeMainClient):
        async def download_media(
            self, message, file_name, progress=None, progress_args=()
        ):
            result = await super().download_media(
                message,
                file_name,
                progress=progress,
                progress_args=progress_args,
            )
            if message.id == 10:
                resource_store.revoke_user(200)
            return result

    async def scenario():
        items = [
            package_item(0, 10, "document", file_name="one.bin"),
            package_item(1, 11, "document", file_name="two.bin"),
        ]
        channel_store = FakeChannelStore(items=items)
        main_client = RevokingMainClient(
            {(-2001, 10): message(10), (-2001, 11): message(11)}
        )
        resource_client = FakeResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job = create_job(resource_store, total_items=2)

        result = await service.process_job(job)

        assert main_client.download_calls == [10]
        assert resource_client.upload_calls == []
        assert result["status"] == "failed"
        assert result["error_code"] == "activation_revoked"

    run(scenario())


def test_worker_processes_queued_jobs_serially(tmp_path, resource_store):
    class SerialResourceClient(FakeResourceClient):
        def __init__(self):
            super().__init__()
            self.active_uploads = 0
            self.max_active_uploads = 0

        async def send_document(
            self,
            chat_id,
            file_name,
            caption=None,
            progress=None,
            progress_args=(),
        ):
            self.active_uploads += 1
            self.max_active_uploads = max(
                self.max_active_uploads, self.active_uploads
            )
            await asyncio.sleep(0)
            await super().send_document(
                chat_id,
                file_name,
                caption,
                progress=progress,
                progress_args=progress_args,
            )
            self.active_uploads -= 1

    async def scenario():
        items = [package_item(0, 10, "document", file_name="one.bin")]
        channel_store = FakeChannelStore(items=items)
        main_client = FakeMainClient({(-2001, 10): message(10)})
        resource_client = SerialResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        first, _ = resource_store.create_delivery_job(
            idempotency_key="first",
            user_id=200,
            package_id=12,
            package_revision=3,
            target_chat_id=-1001,
            total_items=1,
            now=1,
        )
        second, _ = resource_store.create_delivery_job(
            idempotency_key="second",
            user_id=200,
            package_id=12,
            package_revision=3,
            target_chat_id=-1001,
            total_items=1,
            now=2,
        )

        await service.start()
        for _ in range(100):
            if (
                resource_store.get_delivery_job(first["id"])["status"]
                == "completed"
                and resource_store.get_delivery_job(second["id"])["status"]
                == "completed"
            ):
                break
            await asyncio.sleep(0)
        await service.stop()

        assert resource_client.max_active_uploads == 1
        assert [call[0] for call in resource_client.upload_calls] == [
            "document",
            "document",
        ]
        assert resource_store.get_delivery_job(first["id"])["finished_at"] <= (
            resource_store.get_delivery_job(second["id"])["started_at"]
        )

    run(scenario())


def test_stop_marks_active_job_interrupted_and_cleans_temp(
    tmp_path, resource_store
):
    class BlockingMainClient(FakeMainClient):
        def __init__(self, messages):
            super().__init__(messages)
            self.download_started = asyncio.Event()
            self.release_download = asyncio.Event()

        async def download_media(
            self, message, file_name, progress=None, progress_args=()
        ):
            self.download_started.set()
            await self.release_download.wait()
            return await super().download_media(
                message,
                file_name,
                progress=progress,
                progress_args=progress_args,
            )

    async def scenario():
        items = [package_item(0, 10, "document", file_name="one.bin")]
        channel_store = FakeChannelStore(items=items)
        main_client = BlockingMainClient({(-2001, 10): message(10)})
        resource_client = FakeResourceClient()
        service = make_service(
            tmp_path, resource_store, channel_store, main_client, resource_client
        )
        job, _ = resource_store.create_delivery_job(
            idempotency_key="interrupt",
            user_id=200,
            package_id=12,
            package_revision=3,
            target_chat_id=-1001,
            total_items=1,
        )

        await service.start()
        await asyncio.wait_for(main_client.download_started.wait(), timeout=1)
        active = resource_store.get_delivery_job(job["id"])
        assert active["status"] == "downloading"

        await service.stop()

        interrupted = resource_store.get_delivery_job(job["id"])
        assert interrupted["status"] == "failed"
        assert interrupted["error_code"] == "restart_interrupted"
        assert not (tmp_path / "deliveries" / job["public_id"]).exists()

    run(scenario())
