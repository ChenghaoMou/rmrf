import hashlib
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Callable

from jinja2 import Template
from rich.console import Console
from rich.tree import Tree

from rmrf.base import File
from rmrf.base import FileSystem
from rmrf.base import Highlight
from rmrf.base import ImageHighlight
from rmrf.base import TextHighlight
from rmrf.export.base import Writer
from rmrf.export.note import merge_note
from rmrf.export.note import recorded_last_modified
from rmrf.utils import ZoteroItem
from rmrf.utils import find_zotero_item

console = Console()
logger = logging.getLogger("rmrf")


@dataclass
class MarkdownWriter(Writer):
    """
    A writer that exports highlights to Markdown files.

    Re-syncing a note only replaces the frontmatter keys the template renders and the
    body between the managed-region markers, so anything added by hand survives.

    Parameters
    ----------
    template: str | Path
        The path to the Jinja2 template file.
    enable_zotero: bool
        Whether to enable Zotero lookup. Defaults to False.
    enable_cropping: bool
        Whether to enable cropping. Defaults to True.
    zotero_lookup: Callable[[File], ZoteroItem | None] | None
        How to find a document's Zotero item, e.g. ``LocalZotero().find_document``
        wrapped to take a File. Defaults to the Zotero Web API by title.
    """

    template: str | Path
    enable_zotero: bool = False
    enable_cropping: bool = True
    zotero_lookup: Callable[[File], ZoteroItem | None] | None = None

    def __post_init__(self):
        super().__post_init__()
        self.template = Template(Path(self.template).read_text())
        if self.zotero_lookup is None:
            self.zotero_lookup = lambda node: find_zotero_item(self.title_getter(node))

    def note_path(self, node: File) -> Path:
        return self.target_dir / f"{node.zid}.md"

    def should_update(self, node: File, force: bool = False) -> bool:
        """Whether the tablet has changed the document since its note was written."""
        if force:
            return True
        path = self.note_path(node)
        if not path.exists():
            return True
        recorded = recorded_last_modified(path.read_text())
        return recorded is None or node.last_modified_ms is None or node.last_modified_ms > recorded

    def _copy_images(self, node: File, highlights: list[Highlight]) -> dict[str, str]:
        """Copy image highlights into the static folder under content-hash names.

        Returns the new relative link for each image path. Names only change when the
        image does, and images that are no longer used are removed.
        """
        static_dir = self.static_dir / node.zid
        links: dict[str, str] = {}
        for highlight in highlights:
            if not isinstance(highlight, ImageHighlight):
                continue
            source = Path(highlight.image_path)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
            name = f"{digest}{source.suffix}"
            static_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, static_dir / name)
            links[highlight.image_path] = f"statics/{node.zid}/{name}"
        if static_dir.exists():
            keep = {Path(link).name for link in links.values()}
            for stale in static_dir.iterdir():
                if stale.is_file() and stale.name not in keep:
                    stale.unlink()
        return links

    def update(
        self,
        node: File,
        force=False,
        highlights: list[Highlight] | None = None,
    ):
        if not self.should_update(node, force):
            return False, None, None

        highlights = highlights or []
        try:
            links = self._copy_images(node, highlights)
            pages = []
            for page_index, group in groupby(
                sorted(highlights, key=lambda x: x.page_index if x.page_index is not None else -1),
                key=lambda x: x.page_index,
            ):
                group = list(group)
                rendered = []
                for highlight in group:
                    if isinstance(highlight, ImageHighlight):
                        rendered.append(f"![Image (page {page_index})]({links[highlight.image_path]})")
                    elif isinstance(highlight, TextHighlight):
                        rendered.append((*highlight.color, highlight.text))
                tags = sorted(group[-1].tags) if group[-1].tags else []
                pages.append((page_index, tags, rendered))

            if not pages:
                return False, None, node.last_modified_time

            original_title = self.title_getter(node)
            title = original_title.replace('"', " ").replace("'", " ")
            context = dict(
                original_title=original_title,
                title=title,
                alias=title,
                created=node.created_time,
                updated=node.last_modified_time,
                modified=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                pages=pages,
            )

            if self.enable_zotero:
                zotero_item = self.zotero_lookup(node)
                if zotero_item:
                    logger.info(
                        f"Found Zotero item for [yellow]{original_title}[/yellow]",
                        extra={"markup": True},
                    )
                    context.update(
                        authors=zotero_item.authors,
                        url=zotero_item.url,
                        zotero_url=zotero_item.zotero_url,
                        abstract=zotero_item.abstract,
                    )
                else:
                    logger.warning(
                        f"No Zotero item for [yellow]{original_title}[/yellow]",
                        extra={"markup": True},
                    )

            path = self.note_path(node)
            existing = path.read_text() if path.exists() else None
            note = merge_note(existing, self.template.render(**context), node.last_modified_ms)
            if note != existing:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(note)
            return True, None, node.last_modified_time

        except Exception as e:
            logger.error(f"[red]{e}[/red]", extra={"markup": True})
            raise e
        finally:
            for highlight in highlights:
                if isinstance(highlight, ImageHighlight):
                    Path(highlight.image_path).unlink(missing_ok=True)


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
    if path.startswith(prefix) and node.is_document and writer.should_update(node, force):
        updated, _, _ = writer.update(node, force=True, highlights=highlight_extractor(node))
        mark = "[green]✓[/green]" if updated else "[yellow]〰[/yellow]"
        branch = tree_node.add(f"{node.name} {mark}")
    elif path.startswith(prefix):
        branch = tree_node.add(f"{node.name} [dim]=[/dim]")
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
