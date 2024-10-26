import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger
from rmscene import SceneGlyphItemBlock, SceneLineItemBlock


@dataclass
class Node:
    id: str
    metadata: dict
    source_dir: Path | str
    cache_dir: Path | str
    date_format: str = "%Y-%m-%d %H:%M:%S:%f"
    id2page: dict[str, int] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)

    def __post_init__(self):
        self.read_page_map()
        self.source_dir = Path(self.source_dir)
        self.cache_dir = Path(self.cache_dir)

    def read_page_map(self):
        if "cPages" in self.metadata and "pages" in self.metadata["cPages"]:
            for i, page in enumerate(self.metadata["cPages"]["pages"]):
                self.id2page[page["id"]] = i

        if "pages" in self.metadata:
            for page, i in zip(
                self.metadata["pages"], self.metadata["redirectionPageMap"]
            ):
                self.id2page[page] = i

    # "customZoomCenterX": 1.1180836815342663,
    # "customZoomCenterY": 1454.6268696760806,
    # "customZoomOrientation": "portrait",
    # "customZoomPageHeight": 2654,
    # "customZoomPageWidth": 1877,
    # "customZoomScale": 1.062249010581842,

    @property
    def height(self):
        if self.file_type == "notebook":
            # logger.debug(f"Using default screen height for notebook {self.id}")
            return 2160
        return self.metadata["customZoomPageHeight"] # customZoomPageHeight with default zoom scale

    @property
    def width(self):
        if self.file_type == "notebook":
            # logger.debug(f"Using default screen width for notebook {self.id}")
            return 1620
        return self.metadata["customZoomPageWidth"] # customZoomPageWidth with default zoom scale
    

    @property
    def zoom_scale(self):
        return self.metadata["customZoomScale"] # customZoomScale default

    @property
    def margin(self):
        return self.metadata["margins"]

    @property
    def center_x(self):
        return self.metadata["customZoomCenterX"] # customZoomCenterX default

    @property
    def center_y(self):
        return self.metadata["customZoomCenterY"] # customZoomCenterY default

    def absolute_x(self, relative_x: int):
        return relative_x + self.width / 2

    def absolute_y(self, relative_y: int):
        return relative_y
    
    def x_percent(self, relative_x: int):
        return self.absolute_x(relative_x) / self.width

    def y_percent(self, relative_y: int):
        return self.absolute_y(relative_y) / self.height

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
        return datetime.fromtimestamp(
            int(self.metadata["lastOpened"]) / 1000
        ).strftime(self.date_format)

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
        return block.extra_data.startswith(b"\xa4\x01") and len(block.extra_data) >= 5

    @staticmethod
    def is_handwriting_block(block: SceneLineItemBlock | SceneGlyphItemBlock):
        return block.item and block.item.value and block.item.value.points


class FileSystem:
    def __init__(self, source_dir: str, cache_dir: str):
        logger.info(
            f"Initializing FileSystem with source_dir: {source_dir} and cache_dir: {cache_dir}"
        )
        self.source_dir = Path(source_dir)
        self.cache_dir = Path(cache_dir)
        self.root = Node(
            "root",
            {"visibleName": "Root", "type": "CollectionType"},
            source_dir,
            cache_dir,
        )
        self.nodes = {}

    def add_node(self, node_id, metadata):
        node = Node(node_id, metadata, self.source_dir, self.cache_dir)
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
