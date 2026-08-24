"""API key material for the MCP control interface."""

import hmac
import os
from pathlib import Path


KEY_ENVIRONMENT_VARIABLE = "TMD_MCP_API_KEY"


def mcp_api_key_path(config_file: str) -> Path:
    """Return the owner-only key file that sits beside the YAML config."""

    return Path(config_file).resolve().parent / "mcp_api_key"


def load_mcp_api_key(config_file: str) -> str:
    """Read the key from the environment first, then the owner-only file."""

    environment_key = str(os.environ.get(KEY_ENVIRONMENT_VARIABLE, "")).strip()
    if environment_key:
        return environment_key
    key_path = mcp_api_key_path(config_file)
    if not key_path.exists():
        return ""
    if os.name == "posix":
        os.chmod(key_path, 0o600)
    return key_path.read_text(encoding="utf-8").strip()


def verify_mcp_api_key(expected: str, supplied: str) -> bool:
    """Compare in constant time and never accept an unconfigured key."""

    if not expected:
        return False
    return hmac.compare_digest(str(expected), str(supplied or ""))
