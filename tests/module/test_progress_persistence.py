import asyncio
import threading


class _Store:
    def __init__(self):
        self.calls = []

    def transition_file(
        self,
        task_id,
        message_id,
        *,
        task_updates=None,
        file_updates=None,
    ):
        self.calls.append(
            {
                "thread_id": threading.get_ident(),
                "task_id": str(task_id),
                "message_id": str(message_id),
                "task_updates": dict(task_updates or {}),
                "file_updates": dict(file_updates or {}),
            }
        )
        return None


def test_progress_samples_are_bounded_and_persisted_off_loop():
    from module.progress_persistence import ProgressPersistence

    now = [100.0]
    store = _Store()
    persistence = ProgressPersistence(
        min_interval_seconds=10,
        min_byte_delta=100,
        clock=lambda: now[0],
    )
    event_loop_thread = threading.get_ident()

    async def scenario():
        first = await persistence.persist_download(
            store,
            "task-1",
            101,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=1,
            download_speed=1,
        )
        suppressed = await persistence.persist_download(
            store,
            "task-1",
            101,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=50,
            download_speed=2,
        )
        byte_delta = await persistence.persist_download(
            store,
            "task-1",
            101,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=150,
            download_speed=3,
        )
        forced = await persistence.persist_download(
            store,
            "task-1",
            101,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=151,
            download_speed=0,
            force=True,
        )
        return first, suppressed, byte_delta, forced

    assert asyncio.run(scenario()) == (True, False, True, True)
    assert [call["file_updates"]["downloaded_size"] for call in store.calls] == [
        1,
        150,
        151,
    ]
    assert all(call["thread_id"] != event_loop_thread for call in store.calls)


def test_progress_time_threshold_and_clear_reset_sampling():
    from module.progress_persistence import ProgressPersistence

    now = [100.0]
    store = _Store()
    persistence = ProgressPersistence(
        min_interval_seconds=5,
        min_byte_delta=1000,
        clock=lambda: now[0],
    )

    async def scenario():
        await persistence.persist_download(
            store,
            "task-2",
            202,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=10,
            download_speed=1,
        )
        now[0] += 5
        elapsed = await persistence.persist_download(
            store,
            "task-2",
            202,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=11,
            download_speed=1,
        )
        persistence.clear("task-2", 202)
        reset = await persistence.persist_download(
            store,
            "task-2",
            202,
            total_count=1,
            filename="sample.bin",
            total_size=1000,
            downloaded_size=12,
            download_speed=1,
        )
        return elapsed, reset

    assert asyncio.run(scenario()) == (True, True)
    assert len(store.calls) == 3


def test_forced_progress_waits_for_existing_file_write():
    from module.progress_persistence import ProgressPersistence

    class _BlockingStore(_Store):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.release = threading.Event()
            self.active_writes = 0
            self.max_active_writes = 0
            self._write_lock = threading.Lock()

        def transition_file(self, *args, **kwargs):
            with self._write_lock:
                self.active_writes += 1
                self.max_active_writes = max(self.max_active_writes, self.active_writes)
            try:
                self.entered.set()
                self.release.wait(timeout=2)
                return super().transition_file(*args, **kwargs)
            finally:
                with self._write_lock:
                    self.active_writes -= 1

    store = _BlockingStore()
    persistence = ProgressPersistence(min_interval_seconds=0, min_byte_delta=0)

    async def scenario():
        first = asyncio.create_task(
            persistence.persist_download(
                store,
                "task-inflight",
                303,
                total_count=1,
                filename="sample.bin",
                total_size=100,
                downloaded_size=10,
                download_speed=1,
            )
        )
        assert await asyncio.to_thread(store.entered.wait, 1)
        forced = asyncio.create_task(
            persistence.persist_download(
                store,
                "task-inflight",
                303,
                total_count=1,
                filename="sample.bin",
                total_size=100,
                downloaded_size=100,
                download_speed=0,
                force=True,
            )
        )
        await asyncio.sleep(0.05)
        observed_max = store.max_active_writes
        forced_finished_early = forced.done()
        store.release.set()
        results = await asyncio.gather(first, forced)
        return observed_max, forced_finished_early, results

    observed_max, forced_finished_early, results = asyncio.run(scenario())

    assert observed_max == 1
    assert forced_finished_early is False
    assert results == [True, True]
    assert store.max_active_writes == 1
    assert [call["file_updates"]["downloaded_size"] for call in store.calls] == [
        10,
        100,
    ]
