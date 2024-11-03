import math
from dataclasses import dataclass
from tempfile import NamedTemporaryFile

import fitz
from loguru import logger
from PIL import Image
from rich.console import Console
from rmscene import (
    RootTextBlock,
    SceneGlyphItemBlock,
    SceneLineItemBlock,
    UnreadableBlock,
    read_blocks,
)
from shapely.geometry import Polygon

from .fs import Node
from .svg import blocks_to_svg
from .writing_tools import remarkable_palette

console = Console()


@dataclass
class Highlight:
    page_index: int
    tags: set[str]


@dataclass
class TextHighlight(Highlight):
    text: str
    color: tuple[int, int, int, int]


@dataclass
class ImageHighlight(Highlight):
    image_path: str


DrawingHighlight = ImageHighlight


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
        if (
            isinstance(block, SceneLineItemBlock)
            and block.item
            and block.item.value
            and block.item.value.points
        ):
            x_values.extend(p.x for p in block.item.value.points)
            y_values.extend(p.y for p in block.item.value.points)
        elif isinstance(block, RootTextBlock) and block.value:
            x_values.append(block.value.pos_x)
            y_values.append(block.value.pos_y)

    if not x_values or not y_values:
        return (0, 0, 0, 0)

    return (min(x_values), min(y_values), max(x_values), max(y_values))


def is_rectangular(
    block: SceneLineItemBlock | SceneGlyphItemBlock, threshold: float = 0.8
) -> bool:
    """
    Test if the block is close to a rectangle.

    Parameters
    ----------
    block: SceneLineItemBlock | SceneGlyphItemBlock
        The block to test.
    threshold: float
        The threshold for the ratio of the area of the polygon to the area of the rectangle. Defaults to 0.8.

    Returns
    -------
    bool
        True if the block is close to a rectangle, False otherwise.
    """
    polygon = Polygon([(p.x, p.y) for p in block.item.value.points])
    x_min, y_min, x_max, y_max = get_limits([block])
    rectangle = (x_max - x_min) * (y_max - y_min)
    if rectangle <= 0:
        return False
    return polygon.area / rectangle >= threshold


def get_transformation(
    node: Node,
    blocks: list[SceneLineItemBlock | SceneGlyphItemBlock | RootTextBlock],
    doc: fitz.Document | None = None,
    page_index: int | None = None,
    dpi: int = 300,
) -> tuple[int, int, int, int, float, float, Image.Image | None]:
    """
    Get the transformation matrix for the blocks.

    Parameters
    ----------
    node: Node
        The node to get the transformation for.
    blocks: list[SceneLineItemBlock | SceneGlyphItemBlock | RootTextBlock]
        The blocks to get the transformation for.
    doc: fitz.Document | None
        The document to get the transformation for. Defaults to None.
    page_index: int | None
        The page index to get the transformation for. Defaults to None.
    dpi: int
        The DPI to use for the transformation. Defaults to 300.

    Returns
    -------
    tuple[int, int, int, int, float, float, Image.Image | None]
        The transformation matrix for the blocks, which is a tuple of the form (x_delta, y_delta, screen_width, screen_height, x_scale, y_scale, base_image).
    """
    logger.warning("Transformation is highly experimental")

    x_min, y_min, x_max, y_max = get_limits(blocks)
    logger.debug(f"{x_min=:.2f}, {y_min=:.2f}, {x_max=:.2f}, {y_max=:.2f}")

    if doc is not None and page_index is not None:
        page = doc[page_index]
        image = page.get_pixmap(
            dpi=dpi,
        )
        base_image = Image.frombytes("RGB", (image.width, image.height), image.samples)
        image_width = image.width
        image_height = image.height
    else:
        base_image = None
        image_width = None
        image_height = None

    screen_width = node.zoom_width
    screen_height = node.zoom_height

    logger.debug(f"{screen_width=:.2f}, {screen_height=:.2f}")

    x_delta = screen_width / 2 + node.center_x
    y_delta = abs(y_min) if y_min < 0 else 0

    while (
        x_max - x_min > screen_width
        or x_min + x_delta < 0
        or x_max + x_delta > screen_width
        or x_max > screen_width
        or (x_delta - node.center_x) * 2 > screen_width
    ):
        c1, r1 = abs(x_min) if x_min < 0 else 0, "Offsetting negative x"
        c2, r2 = x_delta, "x_delta"
        c3, r3 = screen_width / 2 + node.center_x, "Screen width / 2 + center_x"

        x_delta_ = max(c1, c2, c3)

        if x_delta_ != x_delta:
            reason = [r1, r2, r3][[c1, c2, c3].index(x_delta_)]
            logger.warning(f"{x_delta=:.2f} -> {x_delta_=:.2f} ({reason})")
        x_delta = x_delta_

        c1, r1 = math.ceil(x_max - x_min), "x_max - x_min"
        c2, r2 = screen_width, "screen_width"
        c3, r3 = math.ceil((x_delta - node.center_x) * 2), "2 * (x_delta - center_x)"
        c4, r4 = math.ceil(x_max + x_delta), "x_max + x_delta"

        screen_width_ = max(c1, c2, c3, c4)

        if screen_width_ != screen_width:
            reason = [r1, r2, r3, r4][[c1, c2, c3, c4].index(screen_width_)]
            logger.warning(f"{screen_width=:.2f} -> {screen_width_=:.2f} ({reason})")
            screen_height = screen_height * screen_width_ / screen_width

        screen_width = screen_width_

    while (
        y_max - y_min > screen_height
        or y_min + y_delta < 0
        or y_max + y_delta > screen_height
        or y_max > screen_height
    ):
        c1, r1 = abs(y_min) if y_min < 0 else 0, "Offsetting negative y"
        c2, r2 = node.center_y - screen_height / 2, "center_y - screen_height / 2"
        c3, r3 = y_delta, "y_delta"

        y_delta_ = max(c1, c2, c3)

        if y_delta_ != y_delta:
            reason = [r1, r2, r3][[c1, c2, c3].index(y_delta_)]
            logger.warning(f"{y_delta=:.2f} -> {y_delta_=:.2f} ({reason})")
        y_delta = y_delta_

        c1, r1 = math.ceil(y_max - y_min), "y_max - y_min"
        c2, r2 = screen_height, "screen_height"
        c3, r3 = math.ceil(y_max + y_delta), "y_max + y_delta"
        c4, r4 = math.ceil(y_max), "y_max"

        screen_height_ = max(c1, c2, c3, c4)

        if screen_height_ != screen_height:
            reason = [r1, r2, r3, r4][[c1, c2, c3, c4].index(screen_height_)]
            logger.warning(f"{screen_height=:.2f} -> {screen_height_=:.2f} ({reason})")
            screen_width = screen_width * screen_height_ / screen_height

        screen_height = screen_height_

    screen_width = math.ceil(screen_width)
    screen_height = math.ceil(screen_height)
    x_delta = math.ceil(x_delta)
    y_delta = math.ceil(y_delta)

    assert x_max + x_delta <= screen_width
    assert x_min + x_delta >= 0
    assert x_max - x_min <= screen_width
    assert y_max + y_delta <= screen_height
    assert y_min + y_delta >= 0
    assert y_max - y_min <= screen_height

    if base_image is not None:
        x_scale = image_width / screen_width
        y_scale = image_height / screen_height
        x_scale = y_scale = round(min(x_scale, y_scale), 2)
        screen_width = math.ceil(max(screen_width * x_scale, image_width))
        screen_height = math.ceil(max(screen_height * y_scale, image_height))

        # logger.warning(f"final: {x_scale=:.2f}, {y_scale=:.2f}, {screen_width=:.2f}, {screen_height=:.2f}, ratio: {screen_width / screen_height:.2f}")
    else:
        x_scale = y_scale = 1.0

    return x_delta, y_delta, screen_width, screen_height, x_scale, y_scale, base_image


def extract_highlights(node: Node) -> list[Highlight]:
    highlights: list[Highlight] = []
    highlight_dir = node.source_dir / node.id
    if not highlight_dir.exists():
        return highlights

    doc = node.doc

    for rm_file in highlight_dir.glob("*.rm"):
        basename = rm_file.name
        page_id = basename.split(".")[0]
        page_index = node.id2page.get(page_id, None)

        svg_blocks = []

        with open(rm_file, "rb") as f:
            blocks = list(read_blocks(f))

            (
                x_delta,
                y_delta,
                screen_width,
                screen_height,
                x_scale,
                y_scale,
                base_image,
            ) = get_transformation(node, blocks, doc, page_index)

            for block in blocks:
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

                # * If this is a highlight block, we don't need to draw it
                if node.is_highlight_block(block):
                    highlights.append(
                        TextHighlight(
                            page_index=page_index or -1,
                            tags=node.page_tags.get(page_index, set()),
                            text=block.item.value.text,
                            color=get_color(block),
                        )
                    )

                    continue

                # * If this is not a handwriting block, we don't need to draw it
                if not node.is_handwriting_block(block):
                    continue

                color = get_color(block)
                # * test if the block is close to a rectangle
                if is_rectangular(block):
                    x_min, y_min, x_max, y_max = get_limits([block])
                    cropped = base_image.crop(
                        (
                            (x_min + x_delta) * x_scale,
                            (y_min + y_delta) * y_scale,
                            (x_max + x_delta) * x_scale,
                            (y_max + y_delta) * y_scale,
                        )
                    )
                    with NamedTemporaryFile(
                        mode="wb", suffix=".png", delete=False, dir=node.cache_dir
                    ) as f:
                        cropped.save(f)
                        highlights.append(
                            ImageHighlight(
                                page_index=page_index,
                                tags=node.page_tags.get(page_index, set()),
                                image_path=f.name,
                            )
                        )
                        continue

                svg_blocks.append((block, color))

        if svg_blocks:
            with NamedTemporaryFile(
                mode="w", suffix=".svg", delete=False, dir=node.cache_dir
            ) as f:
                margin = 0

                blocks_to_svg(
                    svg_blocks,
                    f,
                    xpos_shift=math.ceil(x_delta) + margin,
                    ypos_shift=math.ceil(y_delta) + margin,
                    screen_width=screen_width + margin * 2,
                    screen_height=screen_height + margin * 2,
                    base_image=base_image,
                    margin=margin,
                    x_scale=x_scale,
                    y_scale=y_scale,
                )

                highlights.append(
                    DrawingHighlight(
                        page_index=page_index,
                        tags=node.page_tags.get(page_index, set()),
                        image_path=f.name,
                    )
                )

    return sorted(highlights, key=lambda x: x.page_index)
