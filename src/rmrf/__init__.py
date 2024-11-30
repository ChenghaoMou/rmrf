import logging

from rich.logging import RichHandler

from rmrf.export.markdown import (
    MarkdownWriter,
    book_title_getter,
    paper_title_getter,
    update,
)
from rmrf.fs import FileSystem

FORMAT = "%(message)s"
logging.basicConfig(
    level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)


__all__ = [
    "FileSystem",
    "MarkdownWriter",
    "book_title_getter",
    "paper_title_getter",
    "update",
]
