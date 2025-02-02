import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import fitz
from rmscene import RootTextBlock, SceneGlyphItemBlock, SceneLineItemBlock, read_blocks
from rmscene.scene_stream import Block

logger = logging.getLogger("rmrf")


@dataclass
class File:
    id: str
    metadata: dict
    source_dir: Path | str
    cache_dir: Path | str
    date_format: str = "%Y-%m-%d %H:%M:%S:%f"
    id2page: dict[str, int] = field(default_factory=dict)
    page_tags: dict[int, set[str]] = field(default_factory=dict)
    page_scroll: dict[int, int] = field(default_factory=dict)
    children: list["File"] = field(default_factory=list)

    def __post_init__(self):
        self.source_dir = Path(self.source_dir)
        self.cache_dir = Path(self.cache_dir)
        self.read_page_map()
        self.zid = hashlib.shake_256(self.name.encode()).hexdigest(6)

    def read_page_map(self):
        self.page_scroll = defaultdict(int)
        if "cPages" in self.metadata and "pages" in self.metadata["cPages"]:
            for i, page in enumerate(self.metadata["cPages"]["pages"]):
                self.id2page[page["id"]] = i
                if "verticalScroll" in page:
                    self.page_scroll[i] = page["verticalScroll"]["value"]

        if "pages" in self.metadata:
            for page, i in zip(
                self.metadata["pages"], self.metadata["redirectionPageMap"]
            ):
                self.id2page[page] = i

        self.page_tags = defaultdict(set)
        if "pageTags" in self.metadata:
            for item in self.metadata["pageTags"]:
                page_idx = self.id2page[item["pageId"]]
                self.page_tags[page_idx].add(item["name"])

        self.rm_blocks = {}
        highlight_dir = self.source_dir / self.id
        if not highlight_dir.exists():
            return

        for rm_file in highlight_dir.glob("*.rm"):
            basename = rm_file.name
            page_id = basename.split(".")[0]
            page_index = self.id2page.get(page_id, None)
            with open(rm_file, "rb") as f:
                self.rm_blocks[page_index] = list(read_blocks(f))

    @property
    def orientation(self):
        return self.metadata["orientation"]

    @property
    def is_portrait(self):
        return self.orientation == "portrait"

    @property
    def is_landscape(self):
        return self.orientation == "landscape"

    @property
    def zoom_mode(self):
        return self.metadata["zoomMode"]

    @property
    def zoom_scale(self):
        return self.metadata["customZoomScale"]

    @property
    def margin(self):
        return self.metadata["margins"]

    @property
    def center_x(self):
        return self.metadata["customZoomCenterX"]

    @property
    def center_y(self):
        return self.metadata["customZoomCenterY"]

    @property
    def screen_height(self):
        return 2160

    @property
    def screen_width(self):
        return 1620

    @property
    def zoom_height(self):
        return self.metadata["customZoomPageHeight"]

    @property
    def zoom_width(self):
        return self.metadata["customZoomPageWidth"]

    @property
    def created_time(self):
        result = datetime.fromtimestamp(
            int(self.metadata["createdTime"]) / 1000
        ).strftime(self.date_format)
        # Hopefully I will live long enough to update this code :)
        if not result.startswith("20"):
            result = datetime.now().strftime(self.date_format)
        return result

    @property
    def last_modified_time(self):
        return datetime.fromtimestamp(
            int(self.metadata["lastModified"]) / 1000
        ).strftime(self.date_format)

    @property
    def last_opened_time(self):
        return datetime.fromtimestamp(int(self.metadata["lastOpened"]) / 1000).strftime(
            self.date_format
        )

    @property
    def is_collection(self):
        return self.metadata["type"] == "CollectionType"

    @property
    def is_document(self):
        return self.metadata["type"] == "DocumentType"

    @property
    def file_type(self):
        return self.metadata["fileType"]

    @property
    def is_trash(self):
        return self.file_type == "trash"

    @property
    def parent(self):
        return self.metadata["parent"]

    @property
    def name(self):
        return self.metadata["visibleName"]

    @property
    def deleted(self):
        return self.metadata.get("deleted", False) or self.parent == "trash"

    @staticmethod
    def is_highlight_block(block: SceneLineItemBlock | SceneGlyphItemBlock):
        # It must have at least 5 bytes to contain a color (a, r, g, b, ?)
        # print(block.extra_data)
        return (
            # block.extra_data.startswith(b"\xa4\x01")
            # and len(block.extra_data) >= 5
            block.item and block.item.value and getattr(block.item.value, "text", None)
        )

    @staticmethod
    def is_handwriting_block(block: SceneLineItemBlock | SceneGlyphItemBlock):
        return (
            block.item
            and block.item.value
            and getattr(block.item.value, "points", None)
        )

    @property
    def doc(self) -> fitz.Document | None:
        if self.file_type == "pdf" or self.file_type == "epub":
            if (pdf_file := self.source_dir / f"{self.id}.pdf").exists():
                doc = fitz.open(pdf_file)
            else:
                doc = None
        else:
            doc = None
        return doc

    def get_page_blocks(self, page_idx: int) -> list[Block]:
        return self.rm_blocks.get(page_idx, [])

    def __len__(self):
        return len(self.id2page)

    @property
    def valid_elements(self):
        return (SceneLineItemBlock, SceneGlyphItemBlock, RootTextBlock)


@dataclass
class FileSystem:
    source_dir: str | Path
    cache_dir: str | Path

    def __post_init__(self):
        self.source_dir = Path(self.source_dir)
        self.cache_dir = Path(self.cache_dir)
        user_home = Path.home()
        logger.info(
            f"Initializing with ~/{str(self.source_dir.relative_to(user_home))} and ~/{str(self.cache_dir.relative_to(user_home))}"
        )
        self.root = File(
            "root",
            {"visibleName": "Root", "type": "CollectionType"},
            self.source_dir,
            self.cache_dir,
        )
        self.nodes = {}
        file_ids = self.read_file_ids()
        self.parse_hierarchy(file_ids)

    def add_node(self, node_id, metadata):
        node = File(node_id, metadata, self.source_dir, self.cache_dir)
        if node.deleted:
            return
        self.nodes[node_id] = node
        return node

    def build_hierarchy(self):
        for node in self.nodes.values():
            parent_id = node.parent
            if parent_id in self.nodes:
                self.nodes[parent_id].children.append(node)
            else:
                self.root.children.append(node)

    def get_metadata(self, file_id: str) -> dict:
        path = self.source_dir / f"{file_id}.metadata"
        if not path.exists():
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def get_content(self, file_id: str) -> dict:
        path = self.source_dir / f"{file_id}.content"
        if not path.exists():
            return {}
        with open(path, "r") as f:
            return json.load(f)

    def parse_hierarchy(self, file_ids):
        for file_id in file_ids:
            metadata = self.get_metadata(file_id)
            if not metadata:
                logger.warning(f"Metadata for {file_id} not found")

            content = self.get_content(file_id)
            metadata |= content
            self.add_node(file_id, metadata)

        self.build_hierarchy()
        return self

    def read_file_ids(self):
        file_ids = set()
        for file in self.source_dir.glob("*"):
            file_id = file.name.split(".")[0]
            if not file_id or file_id.startswith("."):
                continue
            file_ids.add(file_id)
        return file_ids


@dataclass
class Highlight:
    page_index: int
    block_index: int | float
    tags: set[str]


@dataclass
class TextHighlight(Highlight):
    text: str
    color: tuple[int, int, int, int]


@dataclass
class ImageHighlight(Highlight):
    image_path: str


DrawingHighlight = ImageHighlight
