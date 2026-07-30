import pytest

from module.task_state import TaskStateStore, reset_task_store_for_tests


@pytest.fixture(autouse=True)
def isolated_process_task_store():
    """Give every test an explicit in-memory process task store."""

    previous_store = reset_task_store_for_tests(TaskStateStore())
    try:
        yield
    finally:
        reset_task_store_for_tests(previous_store)
