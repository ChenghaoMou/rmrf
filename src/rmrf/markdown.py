import glob
import hashlib
import os
import re
import shutil
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Callable

from loguru import logger
from rich.console import Console
from rich.tree import Tree

from .fs import FileSystem, Node
from .parse import (
    Highlight,
    ImageHighlight,
    TextHighlight,
    extract_highlights,
)

console = Console()

Template = """---
title: "{title}"
alias:
  - "{alias}"
created: {created}
updated: {updated}
modified: {modified}
tags:
  - reMarkable
---

# {original_title}

{highlights}
"""

Highlight_Template = """
<mark style="background-color: #{r:02x}{g:02x}{b:02x};">{text}</mark>
"""

Page_Template = """
## Page {page_index}

{tags}

{highlights}
"""


class MarkdownWriter:
    def __init__(
        self,
        target_dir: str,
        static_dir: str,
        cache_dir: str,
        title_getter: Callable[[str], str],
        file_template: str = Template,
        highlight_template: str = Highlight_Template,
        page_template: str = Page_Template,
    ):
        self.target_dir = Path(target_dir)
        self.static_dir = Path(static_dir)
        self.cache_dir = Path(cache_dir)
        self.title_getter = title_getter
        self.file_template = file_template
        self.highlight_template = highlight_template
        self.page_template = page_template

    def update(self, node: Node, force=False):
        name = hashlib.shake_256(node.name.encode()).hexdigest(6)
        old_content = ""
        last_modified: str | None = None

        # * Read the old content if the file exists and check the dates
        if os.path.exists(f"{self.target_dir}/{name}.md"):
            with open(f"{self.target_dir}/{name}.md", "r") as f:
                old_content = f.read()
                last_modified = re.search(
                    r"updated: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{6})", old_content
                )
                if last_modified:
                    last_modified = last_modified.group(1)
                    last_modified_dt = datetime.strptime(
                        last_modified, "%Y-%m-%d %H:%M:%S:%f"
                    )
                    if (
                        last_modified_dt
                        >= datetime.strptime(
                            node.last_modified_time, "%Y-%m-%d %H:%M:%S:%f"
                        )
                        and not force
                    ):
                        return False, last_modified, None

        highlights: list[Highlight] = extract_highlights(node)
        highlight_text = []
        static_dir = self.static_dir / name

        if static_dir.exists():
            # remove all files in the static dir
            for f in glob.glob(f"{static_dir}/*"):
                os.remove(f)

        if os.path.exists(f"{self.target_dir}/{name}.md"):
            os.remove(f"{self.target_dir}/{name}.md")

        for page_index, group in groupby(
            sorted(highlights, key=lambda x: x.page_index),
            key=lambda x: x.page_index,
        ):
            page_highlights = []

            for highlight in group:
                if isinstance(highlight, ImageHighlight):
                    base_name = os.path.basename(highlight.image_path)
                    os.makedirs(static_dir, exist_ok=True)
                    shutil.copy(
                        highlight.image_path,
                        static_dir / base_name,
                    )
                    assert os.path.exists(
                        static_dir / base_name
                    ), f"static file {static_dir / base_name} does not exist"
                    page_highlights.append(
                        f"![Image (page {page_index})](statics/{os.path.join(name, base_name)})"
                    )
                    # remove the image file
                    os.remove(highlight.image_path)
                elif isinstance(highlight, TextHighlight):
                    page_highlights.append(
                        self.highlight_template.format(
                            text=highlight.text,
                            r=highlight.color[0],
                            g=highlight.color[1],
                            b=highlight.color[2],
                            page_index=page_index,
                        )
                    )

            if highlight.tags:
                tag_content = "tags: " + ", ".join(
                    f"#{tag.replace(' ', '_')}" for tag in highlight.tags
                )
            else:
                tag_content = ""

            highlight_text.append(
                self.page_template.format(
                    page_index=page_index,
                    tags=tag_content,
                    highlights="\n".join(page_highlights),
                )
            )

        try:
            original_title = self.title_getter(node.name)
            title = original_title.replace('"', " ").replace("'", " ")
            note = self.file_template.format(
                original_title=original_title,
                title=title,
                alias=title,
                created=node.created_time,
                updated=node.last_modified_time,
                modified=datetime.now().strftime("%Y-%m-%d %H:%M:%S:%f"),
                highlights="\n\n".join(highlight_text),
            )
            if highlight_text:
                with open(f"{self.target_dir}/{name}.md", "w") as f:
                    f.write(note)
                return True, last_modified, node.last_modified_time

        except Exception as e:
            logger.error(f"[red]{e}[/red]")
            raise e
        finally:
            for f in self.cache_dir.glob("*.png"):
                try:
                    os.remove(f)
                except Exception as e:
                    logger.error(f"[red]{e}[/red]")

        return False, last_modified, node.last_modified_time


def paper_title_getter(x: str) -> str:
    """Get the title of a paper from the file name, assuming default Zotero format"""
    *_, original_title = (
        x.replace(".pdf", "").replace(".rm", "").replace(".epub", "").split(" - ")
    )
    return original_title


def book_title_getter(x: str) -> str:
    """Get the title of a book from the file name, assuming default Calibre format"""
    return x.replace(".pdf", "").replace(".rm", "").replace(".epub", "").split(" - ")[0]


def update(fs: FileSystem, *, prefix, writer: MarkdownWriter, force=False):
    tree_node = Tree("/")
    update_notes(
        fs=fs,
        prefix=prefix,
        writer=writer,
        force=force,
        node=fs.root,
        tree_node=tree_node,
        path="/Root",
    )

    console.print(tree_node)


def update_notes(
    fs: FileSystem,
    *,
    prefix,
    writer: MarkdownWriter,
    node,
    tree_node,
    path="",
    force=False,
):
    if path.startswith(prefix):
        updated, prev_last_modified, new_last_modified = writer.update(
            node, force=force
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
        )
