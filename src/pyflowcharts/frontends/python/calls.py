"""Find the calls in Python code and the charts they may reach (static, best-effort)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ModuleInfo:
    """A file's dotted module name (``""`` when it has none) and the package that relative
    imports start from."""

    name: str
    package: tuple[str, ...]


def module_info(key: PurePosixPath) -> ModuleInfo:
    """``pkg/io/load`` → ``pkg.io.load`` in package ``pkg.io``; ``pkg/__init__`` → ``pkg``
    in package ``pkg``; a bare ``__init__`` has no module name."""
    package = key.parts[:-1]
    if key.name == "__init__":
        return ModuleInfo(".".join(package), package)
    return ModuleInfo(".".join(key.parts), package)
