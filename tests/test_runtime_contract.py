import os
import re
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str):
    return YAML(typ="safe").load((ROOT / path).read_text(encoding="utf-8"))


def test_package_metadata_supports_only_python_311():
    setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
    minor_classifiers = set(
        re.findall(r'"Programming Language :: Python :: (3\.\d+)"', setup_text)
    )

    assert 'python_requires="~=3.11.0"' in setup_text
    assert minor_classifiers == {"3.11"}


def test_cli_configuration_failure_exits_nonzero(tmp_path):
    environment = os.environ.copy()
    environment["TMD_CONFIG_PATH"] = str(tmp_path / "missing-config.yaml")
    environment["TMD_DATA_PATH"] = str(tmp_path / "missing-data.yaml")
    result = subprocess.run(
        [sys.executable, str(ROOT / "media_downloader.py")],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0


def test_ci_uses_the_python_311_production_contract():
    unittest_workflow = _load_yaml(".github/workflows/unittest.yml")
    code_checks_workflow = _load_yaml(".github/workflows/code-checks.yml")

    unittest_job = unittest_workflow["jobs"]["build"]
    versions = unittest_job["strategy"]["matrix"]["python-version"]
    assert [str(version) for version in versions] == ["3.11"]

    unittest_uses = {
        step["uses"]
        for step in unittest_job["steps"]
        if isinstance(step, dict) and "uses" in step
    }
    code_check_steps = code_checks_workflow["jobs"]["pre-commit"]["steps"]
    code_check_uses = {
        step["uses"]
        for step in code_check_steps
        if isinstance(step, dict) and "uses" in step
    }
    code_check_python = next(
        step["with"]["python-version"]
        for step in code_check_steps
        if step.get("uses") == "actions/setup-python@v7.0.0"
    )

    assert "actions/checkout@v7.0.1" in unittest_uses
    assert "actions/setup-python@v7.0.0" in unittest_uses
    assert "actions/checkout@v7.0.1" in code_check_uses
    assert "actions/setup-python@v7.0.0" in code_check_uses
    assert "pre-commit/action@v3.0.1" in code_check_uses
    assert str(code_check_python) == "3.11"


def test_local_commands_and_documentation_require_python_311():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    pylintrc = (ROOT / "pylintrc").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_cn = (ROOT / "README_CN.md").read_text(encoding="utf-8")
    operations_doc = (ROOT / "docs/web-control-console.md").read_text(encoding="utf-8")

    assert "PYTHON ?= python3.11" in makefile
    for module in ("pip", "mypy", "pylint", "pytest"):
        assert f"$(PYTHON) -m {module}" in makefile

    assert "`Python 3.11`" in readme
    assert "`Python 3.7`" not in readme
    assert "`Python 3.11`" in readme_cn
    assert "`Python 3.7`" not in readme_cn
    assert (
        "supported production and development interpreter is Python 3.11"
        in operations_doc
    )
    assert "Callers receive\na shallow dictionary snapshot" in operations_doc
    assert "overgeneral-exceptions=builtins.Exception" in pylintrc
    assert "redefined-variable-type" not in pylintrc
    assert "bad-continuation" not in pylintrc


def test_development_and_pre_commit_tools_are_aligned():
    requirement_lines = {
        line.strip()
        for line in (ROOT / "dev-requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.startswith("#")
    }
    expected_requirements = {
        "black==25.12.0",
        "isort==6.1.0",
        "mock==5.2.0",
        "mypy==1.20.2",
        "pre-commit==4.6.1",
        "pylint==3.3.9",
        "pytest==8.4.2",
        "pytest-cov==6.3.0",
        "types-PyYAML==6.0.12.20260724",
        "types-pytz==2026.3.1.20260727",
        "types-croniter==2.0.0.20240423",
        "wheel==0.47.0",
    }
    assert requirement_lines == expected_requirements

    config = _load_yaml(".pre-commit-config.yaml")
    assert config["default_language_version"]["python"] == "python3.11"
    revisions = {entry["repo"]: entry["rev"] for entry in config["repos"]}
    assert revisions == {
        "https://github.com/pre-commit/pre-commit-hooks": "v6.0.0",
        "https://github.com/psf/black": "25.12.0",
        "https://github.com/pycqa/isort": "6.1.0",
        "https://github.com/pre-commit/mirrors-mypy": "v1.20.2",
        "https://github.com/pycqa/pylint": "v3.3.9",
    }

    mypy_hook = next(
        hook
        for entry in config["repos"]
        if entry["repo"] == "https://github.com/pre-commit/mirrors-mypy"
        for hook in entry["hooks"]
        if hook["id"] == "mypy"
    )
    assert set(mypy_hook["additional_dependencies"]) == {
        "types-PyYAML==6.0.12.20260724",
        "types-pytz==2026.3.1.20260727",
        "types-croniter==2.0.0.20240423",
    }

    pylint_hook = next(
        hook
        for entry in config["repos"]
        if entry["repo"] == "https://github.com/pycqa/pylint"
        for hook in entry["hooks"]
        if hook["id"] == "pylint"
    )
    assert pylint_hook.get("language") != "system"


def test_architecture_hardening_modules_are_in_blocking_static_boundary():
    expected_paths = {
        "module/config_persistence.py",
        "module/download_runtime.py",
        "module/download_transfer.py",
        "module/runtime_health.py",
        "module/transfer_progress.py",
        "module/web_auth.py",
        "module/web_server.py",
    }
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    config = _load_yaml(".pre-commit-config.yaml")

    for path in expected_paths:
        assert path in makefile

    expected_stems = {Path(path).stem for path in expected_paths}
    for hook_id in ("mypy", "pylint"):
        hook = next(
            hook
            for entry in config["repos"]
            for hook in entry["hooks"]
            if hook["id"] == hook_id
        )
        file_pattern = hook["files"]
        for stem in expected_stems:
            assert stem in file_pattern


def test_runtime_config_paths_support_directory_mounts(tmp_path):
    config_path = tmp_path / "state" / "config.yaml"
    data_path = tmp_path / "state" / "data.yaml"
    environment = os.environ.copy()
    environment["TMD_CONFIG_PATH"] = str(config_path)
    environment["TMD_DATA_PATH"] = str(data_path)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from module.download_entry import app;"
                "print(app.config_file);"
                "print(app.app_data_file)"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.splitlines()[-2:] == [str(config_path), str(data_path)]
