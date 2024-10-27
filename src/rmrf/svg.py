#
# created     : Sun Oct 27 2024
# author      : Chenghao Mou <mouchenghao at gmail dot com>
# license     : MIT
# description : based on https://github.com/ricklupton/rmc
#

import math
import string
import xml.dom.minidom
from dataclasses import dataclass
from io import StringIO
from typing import Iterable

from loguru import logger
from rmscene import (
    Block,
    RootTextBlock,
    SceneLineItemBlock,
)
from rmscene.scene_items import ParagraphStyle

from .writing_tools import (
    Pen,
)

SCREEN_WIDTH = 1404
SCREEN_HEIGHT = 1872
XPOS_SHIFT = SCREEN_WIDTH / 2

SVG_HEADER = string.Template("""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" height="$height" width="$width">
    <script type="application/ecmascript"> 
        <![CDATA[
            var visiblePage = 'p1';
            function goToPage(page) {
                document.getElementById(visiblePage).setAttribute('style', 'display: none');
                document.getElementById(page).setAttribute('style', 'display: inline');
                visiblePage = page;
            }
        ]]>
    </script>
""")


@dataclass
class SvgDocInfo:
    height: int
    width: int
    xpos_delta: float
    ypos_delta: float

def blocks_to_svg(
    blocks: Iterable[tuple[Block, tuple[int, int, int, int]]],
    output: StringIO,
    xpos_shift: float = XPOS_SHIFT,
    ypos_shift: float = 0,
    screen_width: int = SCREEN_WIDTH,
    screen_height: int = SCREEN_HEIGHT,
):
    blocks = list(blocks)
    output_text = ""

    svg_doc_info = get_dimensions(
        [block for block, _ in blocks],
        xpos_shift=xpos_shift,
        ypos_shift=ypos_shift,
        screen_width=screen_width,
        screen_height=screen_height,
    )

    output_text += SVG_HEADER.substitute(
        height=svg_doc_info.height, width=svg_doc_info.width
    )

    output_text += '<g id="p1" style="display:inline">'
    output_text += '<filter id="blurMe"><feGaussianBlur in="SourceGraphic" stdDeviation="10" /></filter>'

    for block, color in blocks:
        if isinstance(block, SceneLineItemBlock):
            output_text += draw_stroke(block, svg_doc_info, color)
        elif isinstance(block, RootTextBlock):
            output_text += draw_text(block, svg_doc_info)
        else:
            logger.warning(f"not converting block: {block.__class__}")

    output_text += "<!-- clickable rect to flip pages -->"
    output_text += f'<rect x="0" y="0" width="{svg_doc_info.width}" height="{svg_doc_info.height}" fill-opacity="0"/>'
    output_text += "</g> </svg>"
    output.write(xml.dom.minidom.parseString(output_text).toprettyxml(indent="  "))


def draw_stroke(
    block: SceneLineItemBlock,
    svg_doc_info: SvgDocInfo,
    color: tuple[int, int, int, int],
) -> str:
    output_text = ""
    logger.debug("----SceneLineItemBlock")
    output_text += f"<!-- SceneLineItemBlock item_id: {block.item.item_id} -->"

    if block.item.value is None:
        logger.debug("empty stroke")
        return

    pen = Pen.create(
        pen_nr=block.item.value.tool.value,
        color_id=color,
        width=block.item.value.thickness_scale,
    )

    output_text += f"<!-- Stroke tool: {block.item.value.tool.name} color: {block.item.value.color.name} thickness_scale: {block.item.value.thickness_scale} -->"
    output_text += "<polyline "
    output_text += f'style="fill:none;stroke:rgb({pen.stroke_color[0]}, {pen.stroke_color[1]}, {pen.stroke_color[2]});stroke-width:{pen.stroke_width};opacity:{pen.stroke_opacity}" '
    output_text += f'stroke-linecap="{pen.stroke_linecap}" '
    output_text += 'points="'

    last_xpos = -1.0
    last_ypos = -1.0
    last_segment_width = 0
    
    for point_id, point in enumerate(block.item.value.points):
        xpos = point.x + svg_doc_info.xpos_delta
        ypos = point.y + svg_doc_info.ypos_delta
        assert (
            0 <= xpos <= svg_doc_info.width
        ), f"xpos: {xpos} width: {svg_doc_info.width}"
        assert (
            0 <= ypos <= svg_doc_info.height
        ), f"ypos: {ypos} height: {svg_doc_info.height}"

        if point_id % pen.segment_length == 0:
            segment_width = pen.get_segment_width(
                point.speed,
                point.direction,
                point.width,
                point.pressure,
                last_segment_width,
            )
            segment_opacity = pen.get_segment_opacity(
                point.speed,
                point.direction,
                point.width,
                point.pressure,
                last_segment_width,
            )
            output_text += '"/>'
            output_text += "<polyline "
            output_text += f'style="fill:none; stroke:rgb({pen.stroke_color[0]}, {pen.stroke_color[1]}, {pen.stroke_color[2]});stroke-width:{segment_width:.3f};opacity:{segment_opacity}" '
            output_text += f'stroke-linecap="{pen.stroke_linecap}" '
            output_text += 'points="'
            if last_xpos != -1.0:
                output_text += f"{last_xpos:.3f},{last_ypos:.3f} "
        
        last_xpos = xpos
        last_ypos = ypos
        last_segment_width = segment_width

        output_text += f"{xpos:.3f},{ypos:.3f} "
    output_text += '"/>'
    return output_text


def draw_text(block: RootTextBlock, svg_doc_info: SvgDocInfo) -> str:
    output_text = ""
    logger.debug("----RootTextBlock")
    output_text += f"<!-- RootTextBlock item_id: {block.block_id} -->"
    output_text += """
<style> 
.basic, .plain {
    font-family: sans-serif; 
    font-size: 40px
}
.heading {
    font-family: serif; 
    font-size: 50px
}
.bold {
    font-family: sans-serif; 
    font-size: 50px
    font-weight: bold
}
.bullet, .bullet2 {
    font-family: sans-serif; 
    font-size: 40px
}
.checkbox, .checkbox-checked {
    font-family: sans-serif; 
    font-size: 40px
}
</style>"""

    style_class = "plain"
    if block.value.styles:
        value = list(block.value.styles.values())[0].value
        style_class = ParagraphStyle(value).name

    content = ""
    xpos = block.value.pos_x + svg_doc_info.xpos_delta
    ypos = block.value.pos_y + svg_doc_info.ypos_delta

    for text_item in block.value.items.sequence_items():
        content += text_item.value

    offset = 0.5 * content.count("\n")
    content = content.replace("\n", "")
    content = f"<tspan x='{xpos}' dy='{offset}em'>{content}</tspan>"
    output_text += f"<!-- RootTextBlock item_id: {block.block_id} -->"
    if content:
        output_text += (
            f"""<text x="{xpos}" y="{ypos}" class="{style_class.lower()}">{content}</text>"""
        )

    return output_text


def get_limits(blocks: Iterable[Block]) -> tuple[float, float, float, float]:
    xmin = ymin = float("inf")
    xmax = ymax = float("-inf")

    for block in blocks:
        #! text blocks use a different xpos/ypos coordinate system
        if not isinstance(block, SceneLineItemBlock):
            continue

        if block.item.value is None:
            continue
        
        for point in block.item.value.points:
            xpos = point.x
            ypos = point.y
            xmin = min(xmin, xpos)
            xmax = max(xmax, xpos)
            ymin = min(ymin, ypos)
            ymax = max(ymax, ypos)
    
    return xmin, xmax, ymin, ymax


# def get_limits_text(block):
#     xmin = block.pos_x
#     xmax = block.pos_x + block.width
#     ymin = block.pos_y
#     ymax = block.pos_y
#     return xmin, xmax, ymin, ymax


def get_dimensions(
    blocks: Iterable[Block],
    xpos_shift: float = XPOS_SHIFT,
    ypos_shift: float = 0,
    screen_width: int = SCREEN_WIDTH,
    screen_height: int = SCREEN_HEIGHT,
):
    xmin, xmax, ymin, ymax = get_limits(blocks)
    logger.debug(f"xmin: {xmin} xmax: {xmax} ymin: {ymin} ymax: {ymax}")

    #* {xpos,ypos} coordinates are based on the top-center point
    #* of the doc **iff there are no text boxes**. When you add
    #* text boxes, the xpos/ypos values change.
    xpos_delta = xpos_shift
    ypos_delta = ypos_shift
    # adjust dimensions if needed
    width = int(
        math.ceil(
            max(
                screen_width,
                xmax - xmin if xmin is not None and xmax is not None else 0,
            )
        )
    )
    height = int(
        math.ceil(
            max(
                screen_height,
                ymax - ymin if ymin is not None and ymax is not None else 0,
            )
        )
    )
    logger.debug(
        f"height: {height} width: {width} xpos_delta: {xpos_delta} ypos_delta: {ypos_delta}"
    )
    
    return SvgDocInfo(
        height=height, width=width, xpos_delta=xpos_delta, ypos_delta=ypos_delta
    )
