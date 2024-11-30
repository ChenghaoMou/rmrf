from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rmrf.base import File


@dataclass
class Writer:
    target_dir: str | Path
    static_dir: str | Path
    cache_dir: str | Path
    title_getter: Callable[[File], str]

    def __post_init__(self):
        self.target_dir = Path(self.target_dir)
        self.static_dir = Path(self.static_dir)
        self.cache_dir = Path(self.cache_dir)
