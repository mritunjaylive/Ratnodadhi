"""
models.py – Reader dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Reader:
    key: str              # 'system' | 'detected:<exe>' | 'custom:<id>'
    name: str
    exe: str
    formats: frozenset[str] = field(default_factory=frozenset)  # {'pdf','epub'} or {'*'}
    args_template: str = "{file}"

    def handles(self, fmt: str) -> bool:
        clean = fmt.lower().lstrip(".")
        return "*" in self.formats or clean in self.formats
