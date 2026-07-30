from module.transfer_progress import TransferProgressTracker


def test_runtime_and_progress_callback_share_one_tracker():
    from module import download_entry, download_stat

    runtime = download_entry._build_transfer_runtime()

    assert runtime.progress_tracker is download_stat.download_progress_tracker


def test_same_message_id_in_two_chats_has_independent_progress():
    tracker = TransferProgressTracker(clock=lambda: 10.0)
    first = ("task-1", "-1001", "42")
    second = ("task-2", "-1002", "42")

    tracker.start(first)
    tracker.start(second)
    tracker.observe(first, 10)

    assert tracker.downloaded_size(first) == 10
    assert tracker.downloaded_size(second) == 0


def test_observe_refreshes_heartbeat_only_when_bytes_increase():
    timestamps = iter((10.0, 11.0, 12.0, 13.0))
    tracker = TransferProgressTracker(clock=lambda: next(timestamps))
    key = ("task-1", "-1001", "42")

    tracker.start(key)
    tracker.observe(key, 10)
    progressed_at = tracker.last_progress_at(key)
    tracker.observe(key, 10)

    assert tracker.last_progress_at(key) == progressed_at
