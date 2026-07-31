"""Stable CLI and import facade for the refactored downloader modules."""

import importlib
from types import ModuleType

from module import download_entry as _implementation

__all__ = [name for name in dir(_implementation) if not name.startswith("_")]
_delegated_originals: dict[str, list[object]] = {}


class _FacadeModule(ModuleType):
    """Delegate public access while retaining a distinct compatibility module."""

    def __getattr__(self, name: str):
        return getattr(_implementation, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("__") or name in {
            "_implementation",
            "_delegated_originals",
        }:
            ModuleType.__setattr__(self, name, value)
            return
        if hasattr(_implementation, name):
            _delegated_originals.setdefault(name, []).append(
                getattr(_implementation, name)
            )
            setattr(_implementation, name, value)
            return
        ModuleType.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        originals = _delegated_originals.get(name)
        if originals:
            setattr(_implementation, name, originals.pop())
            if not originals:
                _delegated_originals.pop(name, None)
            return
        ModuleType.__delattr__(self, name)

    def __dir__(self):
        return sorted(set(ModuleType.__dir__(self)) | set(dir(_implementation)))


if __name__ == "__main__":
    raise SystemExit(_implementation.run_cli())

_facade = importlib.import_module(__name__)
ModuleType.__setattr__(_facade, "__class__", _FacadeModule)
