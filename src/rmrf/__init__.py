import logging

from rich.logging import RichHandler

from .fs import FileSystem
from .markdown import MarkdownWriter, book_title_getter, paper_title_getter, update

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
