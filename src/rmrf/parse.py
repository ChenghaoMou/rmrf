import logging
import math
from tempfile import NamedTemporaryFile

import fitz
from PIL import Image
from rich.console import Console
from rmscene import (
    RootTextBlock,
    SceneGlyphItemBlock,
    SceneLineItemBlock,
    UnreadableBlock,
)
from shapely.geometry import Polygon

from rmrf.base import DrawingHighlight, File, Highlight, ImageHighlight, TextHighlight
from rmrf.export import blocks_to_svg
from rmrf.utils import remarkable_palette

console = Console()
warned_about_transformation = False
logger = logging.getLogger("rmrf")


class TransformationError(Exception):
    pass


def get_color(
    block: SceneLineItemBlock | SceneGlyphItemBlock,
) -> tuple[int, int, int, int]:
    if block.extra_data and len(block.extra_data) >= 5:
        *_, b, g, r, a = block.extra_data
        return (r, g, b, a)

    r, g, b, *a = remarkable_palette[block.item.value.color]
    if a:
        a = a[0]
    else:
        a = 255
    return (r, g, b, a)


def get_limits(
    blocks: list[SceneLineItemBlock | SceneGlyphItemBlock | RootTextBlock],
) -> tuple[int | None, int | None, int | None, int | None]:
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
        return (None, None, None, None)

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
    if len(block.item.value.points) < 4:
        return False
    polygon = Polygon([(p.x, p.y) for p in block.item.value.points])
    x_min, y_min, x_max, y_max = get_limits([block])
    rectangle = (x_max - x_min) * (y_max - y_min)
    if rectangle <= 0:
        return False
    return polygon.area / rectangle >= threshold


def get_transformation(
    node: File,
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
    global warned_about_transformation
    if not warned_about_transformation:
        logger.warning("Transformation is highly experimental")
        warned_about_transformation = True

    x_min, y_min, x_max, y_max = get_limits(blocks)
    if x_min is None or y_min is None or x_max is None or y_max is None:
        raise TransformationError("No points found in the blocks")

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

    # screen_width = node.screen_width
    screen_width = node.zoom_width
    # screen_height = node.screen_height
    screen_height = node.zoom_height

    logger.debug(f"{screen_width=:.2f}, {screen_height=:.2f}")

    x_delta = screen_width / 2
    y_delta = abs(y_min) if y_min < 0 else 0

    while (
        x_max - x_min > screen_width
        or x_min + x_delta < 0
        or x_max + x_delta > screen_width
        or x_max > screen_width
        or x_delta * 2 > screen_width
    ):
        c1, r1 = abs(x_min) if x_min < 0 else 0, "Offsetting negative x"
        c2, r2 = x_delta, "x_delta"
        c3, r3 = screen_width / 2, "Screen width / 2"

        x_delta_ = max(c1, c2, c3)

        if x_delta_ != x_delta:
            reason = [r1, r2, r3][[c1, c2, c3].index(x_delta_)]
            logger.warning(f"{x_delta=:.2f} -> {x_delta_=:.2f} ({reason})")
        x_delta = x_delta_

        c1, r1 = math.ceil(x_max - x_min), "x_max - x_min"
        c2, r2 = screen_width, "screen_width"
        c3, r3 = math.ceil(x_delta * 2), "2 * x_delta"
        c4, r4 = math.ceil(x_max + x_delta), "x_max + x_delta"

        screen_width_ = max(c1, c2, c3, c4)

        if screen_width_ != screen_width:
            reason = [r1, r2, r3, r4][[c1, c2, c3, c4].index(screen_width_)]
            logger.warning(f"{screen_width=:.2f} -> {screen_width_=:.2f} ({reason})")
            screen_height = screen_height * screen_width_ / screen_width

        screen_width = screen_width_

    assert (
        x_max + x_delta <= screen_width
    ), f"{x_max=:.2f}, {x_delta=:.2f}, {screen_width=:.2f}"
    assert x_min + x_delta >= 0, f"{x_min=:.2f}, {x_delta=:.2f}"
    assert (
        x_max - x_min <= screen_width
    ), f"{x_max=:.2f}, {x_min=:.2f}, {screen_width=:.2f}"

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
            screen_width = max(
                screen_width * screen_height_ / screen_height,
                screen_width,
            )

        screen_height = screen_height_

    screen_width = math.ceil(screen_width)
    screen_height = math.ceil(screen_height)
    # x_delta = math.ceil(x_delta)
    # y_delta = math.ceil(y_delta)

    assert (
        y_max + y_delta <= screen_height
    ), f"{y_max=:.2f}, {y_delta=:.2f}, {screen_height=:.2f}"
    assert y_min + y_delta >= 0, f"{y_min=:.2f}, {y_delta=:.2f}"
    assert (
        y_max - y_min <= screen_height
    ), f"{y_max=:.2f}, {y_min=:.2f}, {screen_height=:.2f}"

    if base_image is not None:
        x_scale = image_width / screen_width
        y_scale = image_height / screen_height
        x_scale = y_scale = round(min(x_scale, y_scale), 2)
        screen_width = math.ceil(max(screen_width * x_scale, image_width))
        screen_height = math.ceil(max(screen_height * y_scale, image_height))

    else:
        x_scale = y_scale = 1.0

    return x_delta, y_delta, screen_width, screen_height, x_scale, y_scale, base_image


def extract_highlights(
    node: File,
    enable_cropping: bool = True,
) -> list[Highlight]:
    """
    Extract highlights from the node.

    Parameters
    ----------
    node: Node
        The node to extract highlights from.
    enable_cropping: bool
        Whether to enable cropping. Defaults to True.

    Returns
    -------
    list[Highlight]
        The highlights extracted from the node.
    """
    highlights: list[Highlight] = []
    if not node.rm_blocks:
        return highlights

    doc = node.doc

    for page_index, blocks in sorted(node.rm_blocks.items(), key=lambda x: x[0]):
        highlights.extend(
            extract_highlights_from_blocks(
                blocks,
                enable_cropping,
                node=node,
                doc=doc,
                page_index=page_index,
                page_tags=node.page_tags.get(page_index, set()),
            )
        )
        # svg_blocks = []
        # cropping_blocks = []

        # for block_idx, block in enumerate(blocks):
        #     if not isinstance(block, node.valid_elements):
        #         if isinstance(block, UnreadableBlock):
        #             logger.error(f"{block}")
        #         continue

        #     if isinstance(block, RootTextBlock):
        #         svg_blocks.append((block_idx, block, (0, 0, 0, 255)))
        #         continue

        #     if isinstance(block, SceneLineItemBlock) and block.item.value is None:
        #         continue

        #     if block.item.deleted_length > 0:
        #         continue

        #     # * If this is a highlight block, we don't need to draw it
        #     if node.is_highlight_block(block):
        #         highlights.append(
        #             TextHighlight(
        #                 page_index=page_index or -1,
        #                 block_index=block_idx,
        #                 tags=node.page_tags.get(page_index, set()),
        #                 text=block.item.value.text,
        #                 color=get_color(block),
        #             )
        #         )
        #         continue

        #     # * If this is not a handwriting block, we don't need to draw it
        #     if not node.is_handwriting_block(block):
        #         continue

        #     # * test if the block is close to a rectangle
        #     if is_rectangular(block) and enable_cropping:
        #         cropping_blocks.append((block_idx, block))
        #     else:
        #         svg_blocks.append((block_idx, block, get_color(block)))

        # try:
        #     (
        #         x_delta,
        #         y_delta,
        #         screen_width,
        #         screen_height,
        #         x_scale,
        #         y_scale,
        #         base_image,
        #     ) = get_transformation(node, blocks, doc, page_index)
        # except TransformationError as e:
        #     logger.debug(f"Skipping page {page_index}: {e}")

        # if cropping_blocks and base_image:
        #     for block_idx, block in cropping_blocks:
        #         x_min, y_min, x_max, y_max = get_limits([block])
        #         cropped = base_image.crop(
        #             (
        #                 (x_min + x_delta) * x_scale,
        #                 (y_min + y_delta) * y_scale,
        #                 (x_max + x_delta) * x_scale,
        #                 (y_max + y_delta) * y_scale,
        #             )
        #         )
        #         with NamedTemporaryFile(
        #             mode="wb", suffix=".png", delete=False, dir=node.cache_dir
        #         ) as f:
        #             cropped.save(f)
        #             highlights.append(
        #                 ImageHighlight(
        #                     page_index=page_index,
        #                     block_index=block_idx,
        #                     tags=node.page_tags.get(page_index, set()),
        #                     image_path=f.name,
        #                 )
        #             )

        # elif cropping_blocks and not base_image:
        #     svg_blocks.extend(
        #         [
        #             (block_idx, block, get_color(block))
        #             for block_idx, block in cropping_blocks
        #         ]
        #     )

        # if svg_blocks:
        #     with NamedTemporaryFile(
        #         mode="w", suffix=".svg", delete=False, dir=node.cache_dir
        #     ) as f:
        #         margin = 0

        #         blocks_to_svg(
        #             [(block, color) for _, block, color in svg_blocks],
        #             f,
        #             xpos_shift=x_delta + margin,
        #             ypos_shift=y_delta + margin,
        #             screen_width=screen_width + margin * 2,
        #             screen_height=screen_height + margin * 2,
        #             base_image=base_image,
        #             margin=margin,
        #             x_scale=x_scale,
        #             y_scale=y_scale,
        #         )

        #         highlights.append(
        #             DrawingHighlight(
        #                 page_index=page_index,
        #                 block_index=float("inf"),
        #                 tags=node.page_tags.get(page_index, set()),
        #                 image_path=f.name,
        #             )
        #         )

    return highlights

def extract_highlights_from_blocks(
    blocks: list[SceneLineItemBlock | SceneGlyphItemBlock | RootTextBlock],
    enable_cropping: bool = True,
    allowed_elements: set| None = None,
    page_index: int | None = None,
    page_tags: set | None = None,
    node: File | None = None,
    doc: fitz.Document | None = None,
) -> list[Highlight]:
    if allowed_elements is None:
        allowed_elements = (SceneLineItemBlock, SceneGlyphItemBlock, RootTextBlock)

    if node is None:
        class MockNode:
            def __init__(self):
                self.zoom_width = 1620
                self.zoom_height = 2160
                self.center_y = 1080
                self.cache_dir = "/tmp"

        node = MockNode()

    highlights: list[Highlight] = []
    svg_blocks = []
    cropping_blocks = []

    for block_idx, block in enumerate(blocks):
        if not isinstance(block, allowed_elements):
            if isinstance(block, UnreadableBlock):
                logger.error(f"{block}")
            continue

        if isinstance(block, RootTextBlock):
            svg_blocks.append((block_idx, block, (0, 0, 0, 255)))
            continue

        if isinstance(block, SceneLineItemBlock) and block.item.value is None:
            continue

        if block.item.deleted_length > 0:
            continue

        # * If this is a highlight block, we don't need to draw it
        if File.is_highlight_block(block):
            highlights.append(
                TextHighlight(
                    page_index=page_index or -1,
                    block_index=block_idx,
                    tags=page_tags or set(),
                    text=block.item.value.text,
                    color=get_color(block),
                )
            )
            continue

        # * If this is not a handwriting block, we don't need to draw it
        if not File.is_handwriting_block(block):
            continue

        # * test if the block is close to a rectangle
        if is_rectangular(block) and enable_cropping:
            cropping_blocks.append((block_idx, block))
        else:
            svg_blocks.append((block_idx, block, get_color(block)))

    try:

        (
            x_delta,
            y_delta,
            screen_width,
            screen_height,
            x_scale,
            y_scale,
            base_image,
        ) = get_transformation(node, blocks, doc, page_index)
    except TransformationError as e:
        logger.debug(f"Skipping page {page_index}: {e}")

    if cropping_blocks and base_image:
        for block_idx, block in cropping_blocks:
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
                        block_index=block_idx,
                        tags=page_tags or set(),
                        image_path=f.name,
                    )
                )

    elif cropping_blocks and not base_image:
        svg_blocks.extend(
            [
                (block_idx, block, get_color(block))
                for block_idx, block in cropping_blocks
            ]
        )

    if svg_blocks:
        with NamedTemporaryFile(
            mode="w", suffix=".svg", delete=False, dir=node.cache_dir
        ) as f:
            margin = 0

            blocks_to_svg(
                [(block, color) for _, block, color in svg_blocks],
                f,
                xpos_shift=x_delta + margin,
                ypos_shift=y_delta + margin,
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
                    block_index=float("inf"),
                    tags=page_tags or set(),
                    image_path=f.name,
                )
            )

    return highlights

