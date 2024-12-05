import shutil
from datetime import datetime
from pathlib import Path

import typer
from rmscene import read_blocks

from rmrf.base.fs import DrawingHighlight
from rmrf.export.markdown import MarkdownWriter
from rmrf.parse import extract_highlights_from_blocks

app = typer.Typer()


@app.command()
def convert_file(
    source_file: Path = typer.Option(..., help="Source rm file"),
    template: Path | None = typer.Option(None, help="Template file, required for md"),
    output_file: Path = typer.Option(..., help="Output file"),
    output_static_folder: Path | None = typer.Option(
        None, help="Output static folder, default is output file parent directory"
    ),
    output_format: str | None = typer.Option(
        ..., help="Output format, md or svg, default is output file suffix"
    ),
    enable_cropping: bool = typer.Option(default=True, help="Enable cropping"),
):
    with open(source_file, "rb") as f:
        blocks = list(read_blocks(f))

    if output_format is None:
        output_format = source_file.suffix.removeprefix(".").lower()
    else:
        suffix = output_file.suffix.removeprefix(".").lower()
        assert (
            suffix == output_format
        ), f"output format {output_format} does not match source file suffix {suffix}"

    assert output_format in (
        "md",
        "svg",
    ), f"output format {output_format} is not supported"

    highlights = extract_highlights_from_blocks(blocks, enable_cropping=enable_cropping)
    if output_format == "md":
        if output_static_folder is None:
            output_static_folder = output_file.parent

        writer = MarkdownWriter(
            target_dir=output_file.parent,
            static_dir=output_static_folder,
            cache_dir="/tmp",
            title_getter=lambda _: source_file.stem,
            template=template,
            enable_cropping=enable_cropping,
        )

        class MockNode:
            def __init__(self):
                self.created_time = datetime.now()
                self.last_modified_time = datetime.now()
                self.zid = output_file.stem

        mock_node = MockNode()
        writer.update(node=mock_node, force=True, highlights=highlights)
    elif output_format == "svg":
        for highlight in highlights:
            if isinstance(highlight, DrawingHighlight):
                shutil.copy(
                    highlight.image_path,
                    output_file,
                )
                break


if __name__ == "__main__":
    app()
