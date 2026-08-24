"""API key loading and comparison for the MCP control interface."""

from module.mcp_auth import load_mcp_api_key, mcp_api_key_path, verify_mcp_api_key


def test_environment_variable_wins_over_key_file(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.yaml")
    mcp_api_key_path(config_file).write_text("file-key\n", encoding="utf-8")
    monkeypatch.setenv("TMD_MCP_API_KEY", "env-key")

    assert load_mcp_api_key(config_file) == "env-key"


def test_key_file_is_used_when_environment_is_absent(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.yaml")
    key_path = mcp_api_key_path(config_file)
    key_path.write_text("  file-key  \n", encoding="utf-8")
    monkeypatch.delenv("TMD_MCP_API_KEY", raising=False)

    assert load_mcp_api_key(config_file) == "file-key"
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_missing_key_returns_empty_string(tmp_path, monkeypatch):
    monkeypatch.delenv("TMD_MCP_API_KEY", raising=False)

    assert load_mcp_api_key(str(tmp_path / "config.yaml")) == ""


def test_verification_rejects_empty_expected_key():
    assert verify_mcp_api_key("", "") is False
    assert verify_mcp_api_key("secret", "secret") is True
    assert verify_mcp_api_key("secret", "other") is False
