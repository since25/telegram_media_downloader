"""Stable CLI and import facade for the refactored downloader modules."""

import sys

from module import download_entry as _implementation


if __name__ == "__main__":
    sys.modules["media_downloader"] = _implementation
    if _implementation._check_config():
        _implementation.main()
else:
    sys.modules[__name__] = _implementation
