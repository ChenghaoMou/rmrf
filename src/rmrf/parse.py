import math
from tempfile import NamedTemporaryFile

import fitz
from loguru import logger
from rich.console import Console
from rmscene import (
    RootTextBlock,
    SceneGlyphItemBlock,
    SceneLineItemBlock,
    UnreadableBlock,
    read_blocks,
)

from .fs import Node
from .svg import blocks_to_svg
from .writing_tools import remarkable_palette

console = Console()


def get_color(
    block: SceneLineItemBlock | SceneGlyphItemBlock,
) -> tuple[int, int, int, int]:
    if block.extra_data and len(block.extra_data) >= 5:
        *_, b, g, r, a = block.extra_data
        return (r, g, b, a)

    r, g, b = remarkable_palette[block.item.value.color]
    return (r, g, b, 255)


def get_limits(
    blocks: list[SceneLineItemBlock | SceneGlyphItemBlock | RootTextBlock],
) -> tuple[int, int, int, int]:
    x_values = []
    y_values = []
    for block in blocks:
        if isinstance(block, SceneLineItemBlock):
            x_values.extend(p.x for p in block.item.value.points)
            y_values.extend(p.y for p in block.item.value.points)
        elif isinstance(block, RootTextBlock):
            console.print(block)
            x_values.append(block.value.pos_x)
            y_values.append(block.value.pos_y)

    return (min(x_values), min(y_values), max(x_values), max(y_values))


def extract_highlights(node: Node) -> list:
    highlights = []
    highlight_dir = node.source_dir / node.id
    if not highlight_dir.exists():
        return highlights

    page_width = None
    page_height = None

    if node.file_type == "pdf" or node.file_type == "epub":
        if (pdf_file := node.source_dir / f"{node.id}.pdf").exists():
            doc = fitz.open(pdf_file)
        else:
            doc = None
    else:
        doc = None
        if node.file_type in {"notebook", "DocumentType"}:
            page_width = node.width
            page_height = node.height

    for rm_file in highlight_dir.glob("*.rm"):
        basename = rm_file.name
        page_id = basename.split(".")[0]
        page_index = node.id2page.get(page_id, None)
        svg_blocks = []

        with open(rm_file, "rb") as f:
            blocks = read_blocks(f)
            for block_idx, block in enumerate(blocks):
                if not isinstance(
                    block, (SceneLineItemBlock, SceneGlyphItemBlock, RootTextBlock)
                ):
                    if isinstance(block, UnreadableBlock):
                        logger.error(f"[red]{block}[/red]")
                    continue

                if isinstance(block, RootTextBlock):
                    svg_blocks.append((block, (0, 0, 0, 255)))
                    continue

                if isinstance(block, SceneLineItemBlock) and block.item.value is None:
                    continue

                if block.item.deleted_length > 0:
                    continue

                # If this is a highlight block, we don't need to draw it
                if node.is_highlight_block(block):
                    color = get_color(block)
                    highlights.append(
                        (
                            page_index or -1,
                            node.page_tags.get(page_index, set()),
                            block.item.value.text,
                            color,
                        )
                    )

                    continue

                # If this is not a handwriting block, we don't need to draw it
                if not node.is_handwriting_block(block):
                    continue

                color = get_color(block)
                points = [p for p in block.item.value.points]

                x_min = node.x_percent(min(p.x for p in points))
                y_min = node.y_percent(min(p.y for p in points))
                x_max = node.x_percent(max(p.x for p in points))
                y_max = node.y_percent(max(p.y for p in points))

                if doc is None or page_index is None:
                    svg_blocks.append((block, color))
                    continue

                page = doc[page_index]
                page_width = int(page.rect.width)
                page_height = int(page.rect.height)
                rect = fitz.Rect(
                    x_min * page_width,
                    y_min * page_height,
                    x_max * page_width,
                    y_max * page_height,
                )
                # cut-out
                if words := page.get_text("words", clip=rect):
                    # snaps to words crop with 10 pixels margin
                    # margin = 3
                    # x_min = max(min(words, key=lambda x: x[0])[0] - margin, 0)
                    # y_min = max(min(words, key=lambda x: x[1])[1] - margin, 0)
                    # x_max = min(
                    #     max(words, key=lambda x: x[2])[2] + margin,
                    #     page_width,
                    # )
                    # y_max = min(
                    #     max(words, key=lambda x: x[3])[3] + margin,
                    #     page_height,
                    # )
                    # rect = fitz.Rect(x_min, y_min, x_max, y_max)

                    image = page.get_pixmap(
                        dpi=300,
                        clip=rect,
                    )
                    with NamedTemporaryFile(
                        suffix=".png", delete=False, dir=node.cache_dir
                    ) as f:
                        image.save(f.name)
                        highlights.append(
                            (
                                page_index,
                                node.page_tags.get(page_index, set()),
                                f.name,
                                None,
                            )
                        )

                    continue

                svg_blocks.append((block, color))

        if svg_blocks:
            with NamedTemporaryFile(
                mode="w", suffix=".svg", delete=False, dir=node.cache_dir
            ) as f:
                x_min, y_min, x_max, y_max = get_limits([b for b, _ in svg_blocks])

                screen_width = node.width
                screen_height = node.height

                x_delta = node.width / 2
                y_delta = abs(y_min) if y_min < 0 else 0

                if (
                    x_max - x_min > screen_width
                    or x_max + x_delta > screen_width
                    or x_max > screen_width
                ):
                    x_delta = abs(x_min) if x_min < 0 else 0
                    screen_width = max(
                        math.ceil(x_max - x_min), screen_width, x_max + x_delta
                    )

                if (
                    y_max - y_min > screen_height
                    or y_max + y_delta > screen_height
                    or y_max > screen_height
                ):
                    y_delta = abs(y_min) if y_min < 0 else 0
                    screen_height = max(
                        math.ceil(y_max - y_min), screen_height, y_max + y_delta
                    )

                x_delta = math.ceil(x_delta)
                y_delta = math.ceil(y_delta)

                logger.debug(
                    f"screen_width: {screen_width}, screen_height: {screen_height}"
                )
                logger.debug(f"x_delta: {x_delta}, y_delta: {y_delta}")
                logger.debug(
                    f"x_min: {x_min:.2f} -> {x_min + x_delta:.2f}, y_min: {y_min:.2f} -> {y_min + y_delta:.2f}"
                )
                logger.debug(
                    f"x_max: {x_max:.2f} -> {x_max + x_delta:.2f}, y_max: {y_max:.2f} -> {y_max + y_delta:.2f}"
                )

                margin = 100

                blocks_to_svg(
                    svg_blocks,
                    f,
                    xpos_shift=math.ceil(x_delta) + margin,
                    ypos_shift=math.ceil(y_delta) + margin,
                    screen_width=screen_width + margin * 2,
                    screen_height=screen_height + margin * 2,
                )

                highlights.append(
                    (
                        page_index,
                        node.page_tags.get(page_index, set()),
                        f.name,
                        None,
                    )
                )

    return sorted(highlights, key=lambda x: x[0])
