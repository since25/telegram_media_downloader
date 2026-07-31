PYTHON ?= python3.11
TEST_ARTIFACTS ?= /tmp/coverage
TYPE_CHECK_PATHS := module/cloud_drive.py module/config_persistence.py \
	module/download_admission.py module/download_lifecycle.py \
	module/download_queue.py module/download_runtime.py module/download_stat.py \
	module/download_transfer.py module/progress_persistence.py module/task_state.py \
	module/runtime_health.py module/telegram_activity.py module/transfer_progress.py \
	module/web_auth.py module/web_commands.py module/web_server.py

.PHONY: install dev_install static_type_check pylint style_check test

install:
	$(PYTHON) -m pip install --upgrade pip setuptools
	$(PYTHON) -m pip install -r requirements.txt

dev_install: install
	$(PYTHON) -m pip install -r dev-requirements.txt

static_type_check:
	$(PYTHON) -m mypy $(TYPE_CHECK_PATHS) --ignore-missing-imports --follow-imports=silent

pylint:
	$(PYTHON) -m pylint $(TYPE_CHECK_PATHS) -rn -sn --errors-only --rcfile=pylintrc

style_check: static_type_check pylint

test:
	$(PYTHON) -m pytest --cov media_downloader --doctest-modules \
		--cov utils \
		--cov-report term-missing \
		--cov-report html:${TEST_ARTIFACTS} \
		--junit-xml=${TEST_ARTIFACTS}/media-downloader.xml \
		tests/
