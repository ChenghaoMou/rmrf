import glob
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Callable

from jinja2 import Template
from rich.console import Console
from rich.tree import Tree

from rmrf.base import (
    File,
    FileSystem,
    Highlight,
    ImageHighlight,
    TextHighlight,
)
from rmrf.export.base import Writer
from rmrf.utils import find_zotero_item

console = Console()
logger = logging.getLogger("rmrf")


@dataclass
class MarkdownWriter(Writer):
    """
    A writer that exports highlights to Markdown files.

    Parameters
    ----------
    template: str | Path
        The path to the Jinja2 template file.
    enable_zotero: bool
        Whether to enable Zotero lookup. Defaults to False.
    enable_cropping: bool
        Whether to enable cropping. Defaults to True.
    """

    template: str | Path
    enable_zotero: bool = False
    enable_cropping: bool = True

    def __post_init__(self):
        super().__post_init__()
        self.template = Template(Path(self.template).read_text())
        self.enable_zotero = self.enable_zotero
        self.enable_cropping = self.enable_cropping

    def should_update(self, node: File, force: bool = False) -> bool:
        if force:
            return True

        if not os.path.exists(f"{self.target_dir}/{node.zid}.md"):
            return True

        with open(f"{self.target_dir}/{node.zid}.md", "r") as f:
            old_content = f.read()
            last_modified = re.search(
                r"updated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{6})", old_content
            )
            if not last_modified:
                return True
            last_modified_dt = datetime.strptime(
                last_modified.group(1), "%Y-%m-%d %H:%M:%S:%f"
            )
            if last_modified_dt >= datetime.strptime(
                node.last_modified_time, "%Y-%m-%d %H:%M:%S:%f"
            ):
                return False

        return True

    def update(
        self,
        node: File,
        force=False,
        highlights: list[Highlight] | None = None,
    ):
        # * Read the old content if the file exists and check the dates
        if not self.should_update(node, force):
            return False, None, None

        pages = []
        static_dir = self.static_dir / node.zid

        if static_dir.exists():
            # remove all files in the static dir
            for f in glob.glob(f"{static_dir}/*"):
                os.remove(f)

        if os.path.exists(f"{self.target_dir}/{node.zid}.md"):
            os.remove(f"{self.target_dir}/{node.zid}.md")

        for page_index, group in groupby(
            sorted(
                highlights,
                key=lambda x: x.page_index if x.page_index is not None else -1,
            ),
            key=lambda x: x.page_index,
        ):
            highlights = []

            for highlight in group:
                if isinstance(highlight, ImageHighlight):
                    base_name = os.path.basename(highlight.image_path)
                    os.makedirs(static_dir, exist_ok=True)
                    shutil.copy(
                        highlight.image_path,
                        static_dir / base_name,
                    )
                    assert os.path.exists(static_dir / base_name), (
                        f"static file {static_dir / base_name} does not exist"
                    )
                    highlights.append(
                        f"![Image (page {page_index})](statics/{os.path.join(node.zid, base_name)})"
                    )
                    # remove the image file
                    os.remove(highlight.image_path)
                elif isinstance(highlight, TextHighlight):
                    highlights.append(
                        # self.highlight_template.format(
                        #     text=highlight.text,
                        #     r=highlight.color[0],
                        #     g=highlight.color[1],
                        #     b=highlight.color[2],
                        #     page_index=page_index,
                        # )
                        (*highlight.color, highlight.text)
                    )

            if highlight.tags:
                tags = highlight.tags
            else:
                tags = []

            pages.append((page_index, tags, highlights))

        try:
            original_title = self.title_getter(node)
            title = original_title.replace('"', " ").replace("'", " ")

            if self.enable_zotero:
                logger.info(
                    f"Looking up Zotero item for [yellow]{original_title}[/yellow]",
                    extra={"markup": True},
                )
                zotero_item = find_zotero_item(original_title)
                if zotero_item:
                    logger.info(
                        f"Found Zotero item for [yellow]{original_title}[/yellow]",
                        extra={"markup": True},
                    )
                    note = self.template.render(
                        original_title=original_title,
                        title=title,
                        alias=title,
                        created=node.created_time,
                        updated=node.last_modified_time,
                        modified=datetime.now().strftime("%Y-%m-%d %H:%M:%S:%f"),
                        pages=pages,
                        authors=zotero_item.authors,
                        url=zotero_item.url,
                        zotero_url=zotero_item.zotero_url,
                        abstract=zotero_item.abstract,
                    )
                    if pages:
                        with open(f"{self.target_dir}/{node.zid}.md", "w") as f:
                            f.write(note)
                        return True, None, node.last_modified_time

            note = self.template.render(
                original_title=original_title,
                title=title,
                alias=title,
                created=node.created_time,
                updated=node.last_modified_time,
                modified=datetime.now().strftime("%Y-%m-%d %H:%M:%S:%f"),
                pages=pages,
            )
            if pages:
                with open(f"{self.target_dir}/{node.zid}.md", "w") as f:
                    f.write(note)
                return True, None, node.last_modified_time

        except Exception as e:
            logger.error(f"[red]{e}[/red]", extra={"markup": True})
            raise e
        finally:
            for f in self.cache_dir.glob("*.png"):
                try:
                    os.remove(f)
                except Exception as e:
                    logger.error(f"[red]{e}[/red]", extra={"markup": True})

        return False, None, node.last_modified_time


def paper_title_getter(x: File) -> str:
    """Get the title of a paper from the file name, assuming default Zotero format"""
    filename = os.path.basename(x.name)
    *_, original_title = (
        filename.replace(".pdf", "")
        .replace(".rm", "")
        .replace(".epub", "")
        .split(" - ")
    )
    return original_title


def book_title_getter(x: File) -> str:
    """Get the title of a book from the file name, assuming default Calibre format"""
    filename = os.path.basename(x.name)
    return (
        filename.replace(".pdf", "")
        .replace(".rm", "")
        .replace(".epub", "")
        .split(" - ", 1)[0]
    )


def update(
    fs: FileSystem,
    *,
    prefix,
    writer: MarkdownWriter,
    force=False,
    highlight_extractor: Callable[[File], list[Highlight]] | None = None,
):
    tree_node = Tree("/")
    update_notes(
        fs=fs,
        prefix=prefix,
        writer=writer,
        force=force,
        node=fs.root,
        tree_node=tree_node,
        path="/Root",
        highlight_extractor=highlight_extractor,
    )

    console.print(list(tree_node.children)[0])


def update_notes(
    fs: FileSystem,
    *,
    prefix,
    writer: MarkdownWriter,
    node,
    tree_node,
    path="",
    highlight_extractor: Callable[[File], list[Highlight]] | None = None,
    force=False,
):
    if path.startswith(prefix):
        updated, prev_last_modified, new_last_modified = writer.update(
            node, force=force, highlights=highlight_extractor(node)
        )
        if updated and prev_last_modified != new_last_modified:
            branch = tree_node.add(f"{node.name} [green]✓[/green]")
        else:
            branch = tree_node.add(f"{node.name} [yellow]〰[/yellow]")
    else:
        branch = tree_node.add(f"{node.name} [red]✗[/red]")

    if not path.startswith(prefix) and not prefix.startswith(path):
        return

    for child in node.children:
        update_notes(
            fs=fs,
            prefix=prefix,
            writer=writer,
            node=child,
            tree_node=branch,
            path=path + "/" + child.name,
            force=force,
            highlight_extractor=highlight_extractor,
        )
