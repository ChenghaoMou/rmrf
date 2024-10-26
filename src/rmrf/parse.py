from tempfile import NamedTemporaryFile

import fitz
from loguru import logger
from rich.console import Console
from rich.logging import RichHandler
from rmc.exporters.svg import blocks_to_svg
from rmc.exporters.writing_tools import remarkable_palette
from rmscene import (
    SceneGlyphItemBlock,
    SceneLineItemBlock,
    UnreadableBlock,
    read_blocks,
)

from .fs import Node

console = Console()
logger.add(RichHandler(console=console), level="INFO")
logger.add(RichHandler(console=console), level="ERROR")


# def draw_handwriting_with_png(
#     doc: fitz.Document | None,
#     page_index: int,
#     hand_writing_points: list[Point],
#     page_width: float,
#     page_height: float,
#     cache_dir: str,
# ):
#     if doc:
#         page = doc[page_index]
#         page_image = page.get_pixmap(dpi=300)
#         uuid = uuid4()
#         page_image.save(f"{cache_dir}/{uuid}-{page_index}.png")
#         image = Image.open(f"{cache_dir}/{uuid}-{page_index}.png")
#         image = image.convert("RGBA")
#     else:
#         image = Image.new("RGBA", (page_width, page_height), (255, 255, 255, 255))

#     for group, segments in groupby(
#         [x for x in hand_writing_points if x.page_index == page_index],
#         key=lambda x: (
#             x.page_index,
#             x.block_index,
#             x.tool,
#             x.color,
#             x.thickness_scale,
#         ),
#     ):
#         color = group[3]
#         prev_x, prev_y = None, None
#         overlay = Image.new("RGBA", (page_width, page_height), (255, 255, 255, 0))
#         draw = ImageDraw.Draw(overlay)
#         for segment in segments:
#             x, y, speed, direction, width, pressure, thickness_scale = (
#                 segment.x,
#                 segment.y,
#                 segment.speed,
#                 segment.direction,
#                 segment.width,
#                 segment.pressure,
#                 segment.thickness_scale,
#             )
#             if prev_x and prev_y:
#                 draw.line(
#                     [(prev_x, prev_y), (x, y)],
#                     fill=color.as_tuple(),
#                     width=math.ceil(thickness_scale),
#                 )

#             prev_x, prev_y = x, y

#         image.alpha_composite(overlay)

#     with NamedTemporaryFile(suffix=".png", delete=False, dir=cache_dir) as f:
#         image.save(f.name)
#         return f.name


# def draw_handwriting_with_svg(
#     doc: fitz.Document | None,
#     page_index: int,
#     hand_writing_points: list[Point],
#     page_width: float,
#     page_height: float,
#     cache_dir: str,
# ):
#     svg_content = f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_width}" height="{page_height}">\n'

#     if doc:
#         # If we have a PDF document, add it as a background image
#         page = doc[page_index]
#         pix = page.get_pixmap()
#         img_data = pix.tobytes("png")
#         img_b64 = base64.b64encode(img_data).decode()
#         svg_content += (
#             f'  <image x="0" y="0" width="{page_width}" height="{page_height}" '
#         )
#         svg_content += f'xlink:href="data:image/png;base64,{img_b64}" />\n'

#     for group, segments in groupby(
#         hand_writing_points,
#         key=lambda x: (x.page_index, x.block_index, x.tool, x.color, x.thickness_scale),
#     ):
#         color = group[3]
#         thickness_scale = group[4]
#         points = list(segments)

#         if not points:
#             continue

#         path_data = "M "

#         for i, point in enumerate(points):
#             x, y = int(point.x), int(point.y)

#             if i == 0:
#                 path_data += f"{x:.2f},{y:.2f} "
#             else:
#                 path_data += f"L {x:.2f},{y:.2f} "

#         svg_content += f'  <path d="{path_data}" fill="none" '
#         svg_content += f'stroke="{color}" '
#         svg_content += f'stroke-width="{max(thickness_scale * color.size / 10, 1)}" '
#         svg_content += 'stroke-linecap="round" stroke-linejoin="round" />\n'

#     svg_content += "</svg>"

#     with NamedTemporaryFile(suffix=".svg", delete=False, dir=cache_dir) as f:
#         f.write(svg_content.encode("utf-8"))
#         return f.name


def get_color(
    block: SceneLineItemBlock | SceneGlyphItemBlock,
) -> tuple[int, int, int, int]:
    if block.extra_data and len(block.extra_data) >= 5:
        *_, b, g, r, a = block.extra_data
        return (r, g, b, a)

    r, g, b = remarkable_palette[block.item.value.color]
    return (r, g, b, 255)


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
        if node.file_type == "notebook":
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
                if not isinstance(block, (SceneLineItemBlock, SceneGlyphItemBlock)):
                    if isinstance(block, UnreadableBlock):
                        logger.error(f"[red]{block}[/red]")
                    continue

                if block.item.deleted_length > 0:
                    continue

                # If this is a highlight block, we don't need to draw it
                if node.is_highlight_block(block):
                    color = get_color(block)
                    highlights.append(
                        (
                            page_index or -1,
                            block.item.value.text,
                            color,
                        )
                    )

                    continue

                # If this is not a handwriting block, we don't need to draw it
                if not node.is_handwriting_block(block):
                    # console.print(f"[yellow]{block}[/yellow]")
                    continue

                color = get_color(block)
                # overwrite the color to match the original color
                block.value.color.value = color

                points = [p for p in block.item.value.points]

                x_min = node.absolute_x(min(p.x for p in points)) / node.width
                y_min = node.absolute_y(min(p.y for p in points)) / node.height
                x_max = node.absolute_x(max(p.x for p in points)) / node.width
                y_max = node.absolute_y(max(p.y for p in points)) / node.height

                if doc is None or page_index is None:
                    svg_blocks.append(block)
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
                # text cut-out
                if words := page.get_text("words", clip=rect):
                    # crop with 10 pixels margin
                    margin = 3
                    x_min = max(min(words, key=lambda x: x[0])[0] - margin, 0)
                    y_min = max(min(words, key=lambda x: x[1])[1] - margin, 0)
                    x_max = min(
                        max(words, key=lambda x: x[2])[2] + margin,
                        page_width,
                    )
                    y_max = min(
                        max(words, key=lambda x: x[3])[3] + margin,
                        page_height,
                    )
                    rect = fitz.Rect(x_min, y_min, x_max, y_max)

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
                                f.name,
                                None,
                            )
                        )

                    continue

                svg_blocks.append(block)

        if svg_blocks:
            with NamedTemporaryFile(
                suffix=".svg", delete=False, dir=node.cache_dir
            ) as f:
                blocks_to_svg(svg_blocks, f.name, xpos_shift=node.width / 2)
                highlights.append((page_index, f.name, None))

    return sorted(highlights, key=lambda x: x[0])
