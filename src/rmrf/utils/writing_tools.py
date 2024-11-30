#
# created     : Sun Oct 27 2024
# author      : Chenghao Mou <mouchenghao at gmail dot com>
# license     : MIT
# description : based on https://github.com/lschwetlick/maxio,
#              https://github.com/chemag/maxio and
#              https://github.com/ricklupton/rmc
#

import math
from dataclasses import dataclass

from rmscene.scene_items import Pen as PenType
from rmscene.scene_items import PenColor

# color codes are read on exported documents manually
remarkable_palette = {
    PenColor.BLACK: (0, 0, 0),
    PenColor.GRAY: (144, 144, 144),
    PenColor.WHITE: (255, 255, 255),
    PenColor.YELLOW: (251, 247, 25),
    PenColor.GREEN: (0, 255, 0),
    PenColor.PINK: (255, 192, 203),
    PenColor.BLUE: (78, 105, 201),
    PenColor.RED: (179, 62, 57),
    PenColor.GRAY_OVERLAP: (125, 125, 125),
    #! Skipped as different colors are used for highlights
    #! PenColor.HIGHLIGHT = ...
    PenColor.GREEN_2: (161, 216, 125),
    PenColor.CYAN: (139, 208, 229),
    PenColor.MAGENTA: (183, 130, 205),
    PenColor.YELLOW_2: (247, 232, 81),
}


@dataclass
class Pen:
    base_width: float
    base_color_id: int | tuple[int, int, int, int]

    def __post_init__(self):
        if isinstance(self.base_color_id, tuple):
            self.base_color = self.base_color_id[:3]
            self.stroke_opacity = self.base_color_id[3] / 255
        else:
            assert (
                self.base_color_id in remarkable_palette
            ), f"Unknown base_color_id: {self.base_color_id}"
            self.base_color = remarkable_palette[self.base_color_id]
            self.stroke_opacity = 1

        assert (
            len(self.base_color) == 3
        ), f"base_color must be a tuple of 3 integers: {self.base_color}"

        self.segment_length = 1000
        self.base_opacity = 1
        self.name = "Basic Pen"
        self.stroke_linecap = "round"
        self.stroke_width = self.base_width
        self.stroke_color = self.base_color

    # note that the units of the points have had their units converted
    # in scene_stream.py
    # speed = d.read_float32() * 4
    # ---> replace speed with speed / 4 [input]
    # direction = 255 * d.read_float32() / (math.pi * 2)
    # ---> replace tilt with direction_to_tilt() [input]
    @classmethod
    def direction_to_tilt(cls, direction):
        return direction * (math.pi * 2) / 255

    # width = int(round(d.read_float32() * 4))
    # ---> replace width with width / 4 [input]
    # ---> replace width with 4 * width [output]
    # pressure = d.read_float32() * 255
    # ---> replace pressure with pressure / 255 [input]

    def get_segment_width(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        return self.base_width

    def get_segment_color(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> str:
        return f"rgb{tuple(self.base_color)}"

    def get_segment_opacity(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        return self.base_opacity

    def cutoff(self, value: float) -> float:
        """must be between 1 and 0"""
        return max(0, min(1, value))

    @classmethod
    def create(cls, pen_nr: PenType, color_id: PenColor, width: float) -> "Pen":
        match pen_nr:
            case PenType.PAINTBRUSH_1 | PenType.PAINTBRUSH_2:
                return Brush(width, color_id)
            case PenType.CALIGRAPHY:
                return Caligraphy(width, color_id)
            case PenType.MARKER_1 | PenType.MARKER_2:
                return Marker(width, color_id)
            case PenType.BALLPOINT_1 | PenType.BALLPOINT_2:
                return Ballpoint(width, color_id)
            case PenType.FINELINER_1 | PenType.FINELINER_2:
                return Fineliner(width, color_id)
            case PenType.PENCIL_1 | PenType.PENCIL_2:
                return Pencil(width, color_id)
            case PenType.MECHANICAL_PENCIL_1 | PenType.MECHANICAL_PENCIL_2:
                return Mechanical_Pencil(width, color_id)
            case PenType.HIGHLIGHTER_1 | PenType.HIGHLIGHTER_2:
                #! TODO: check if this is correct
                width = 25
                return Highlighter(width, color_id)
            case PenType.SHADER:
                #! TODO: check if this is correct
                width = 12
                return Shader(width, color_id)
            case PenType.ERASER_AREA:
                return Erase_Area(width, color_id)
            case PenType.ERASER:
                color_id = PenColor.WHITE
                return Eraser(width, color_id)
            case _:
                raise Exception(f"Unknown pen_nr: {pen_nr}")


@dataclass
class Fineliner(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.base_width = (self.base_width**2.1) * 1.3
        self.name = "Fineliner"


@dataclass
class Ballpoint(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.segment_length = 5
        self.name = "Ballpoint"

    def get_segment_width(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        segment_width = (
            (0.5 + pressure / 255) + (1 * width / 4) - 0.5 * ((speed / 4) / 50)
        )
        return segment_width

    def get_segment_color(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> str:
        intensity = (0.1 * -((speed / 4) / 35)) + (1.2 * pressure / 255) + 0.5
        intensity = self.cutoff(intensity)
        # using segment color not opacity because the dots interfere with each other.
        # Color must be 255 rgb
        segment_color = [int(abs(intensity - 1) * 255)] * 3
        return "rgb" + str(tuple(segment_color))


@dataclass
class Marker(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.segment_length = 3
        self.name = "Marker"

    def get_segment_width(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        segment_width = 0.9 * (
            (width / 4) - 0.4 * self.direction_to_tilt(direction)
        ) + (0.1 * last_width)
        return segment_width


@dataclass
class Pencil(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.segment_length = 2
        self.name = "Pencil"

    def get_segment_width(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        segment_width = 0.7 * (
            (((0.8 * self.base_width) + (0.5 * pressure / 255)) * (width / 4))
            - (0.25 * self.direction_to_tilt(direction) ** 1.8)
            - (0.6 * (speed / 4) / 50)
        )
        # segment_width = 1.3*(((self.base_width * 0.4) * pressure) - 0.5 * ((self.direction_to_tilt(direction) ** 0.5)) + (0.5 * last_width))
        max_width = self.base_width * 10
        segment_width = segment_width if segment_width < max_width else max_width
        return segment_width

    def get_segment_opacity(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        segment_opacity = (0.1 * -((speed / 4) / 35)) + (1 * pressure / 255)
        segment_opacity = self.cutoff(segment_opacity) - 0.1
        return segment_opacity


@dataclass
class Mechanical_Pencil(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.base_width = self.base_width**2
        self.base_opacity = 0.7
        self.name = "Mechanical Pencil"


@dataclass
class Brush(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.segment_length = 2
        self.stroke_linecap = "round"
        self.opacity = 1
        self.name = "Brush"

    def get_segment_width(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        segment_width = 0.7 * (
            ((1 + (1.4 * pressure / 255)) * (width / 4))
            - (0.5 * self.direction_to_tilt(direction))
            - ((speed / 4) / 50)
        )  # + (0.2 * last_width)
        return segment_width

    def get_segment_color(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> str:
        intensity = ((pressure / 255) ** 1.5 - 0.2 * ((speed / 4) / 50)) * 1.5
        intensity = self.cutoff(intensity)
        # using segment color not opacity because the dots interfere with each other.
        # Color must be 255 rgb
        rev_intensity = abs(intensity - 1)
        segment_color = [
            int(rev_intensity * (255 - self.base_color[0])),
            int(rev_intensity * (255 - self.base_color[1])),
            int(rev_intensity * (255 - self.base_color[2])),
        ]

        return "rgb" + str(tuple(segment_color))


@dataclass
class Highlighter(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.stroke_linecap = "square"
        self.base_opacity = 0.3
        # self.stroke_opacity = 0.2
        self.name = "Highlighter"


@dataclass
class Shader(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.stroke_linecap = "round"
        self.base_opacity = 0.1
        # self.stroke_opacity = 0.2
        self.name = "Shader"


@dataclass
class Eraser(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.stroke_linecap = "square"
        self.base_width = self.base_width * 2
        self.name = "Eraser"


@dataclass
class Erase_Area(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.stroke_linecap = "square"
        self.base_opacity = 0
        self.name = "Erase Area"


@dataclass
class Caligraphy(Pen):
    def __post_init__(self):
        super().__post_init__()
        self.segment_length = 2
        self.name = "Calligraphy"

    def get_segment_width(
        self, speed: int, direction: int, width: int, pressure: int, last_width: int
    ) -> float:
        segment_width = 0.9 * (
            ((1 + pressure / 255) * (width / 4))
            - 0.3 * self.direction_to_tilt(direction)
        ) + (0.1 * last_width)
        return segment_width
