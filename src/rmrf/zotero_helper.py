import logging
import os
from dataclasses import dataclass
from pathlib import Path

import diskcache
from dotenv import load_dotenv
from pyzotero import zotero

load_dotenv()
logger = logging.getLogger("rmrf")
logging.getLogger("urllib3").setLevel(logging.WARNING)
cache = diskcache.Cache(directory=Path.home() / ".cache" / "rmrf")


@dataclass
class ZoteroItem:
    key: str
    title: str
    pdf_path: Path | None
    authors: list[str]
    abstract: str
    url: str
    zotero_url: str


class ZoteroLibrary:
    def __init__(self):
        zotero_user_id = os.getenv("ZOTERO_USER_ID")
        zotero_lib_key = os.getenv("ZOTERO_LIB_KEY")
        storage_folder = os.getenv("STORAGE_FOLDER")
        self.zot = zotero.Zotero(zotero_user_id, "user", zotero_lib_key)
        self.storage_folder = Path(storage_folder)

    def lookup_item_and_pdf(self, item_name: str) -> ZoteroItem | None:
        items = self.zot.items(q=item_name)
        if not items:
            logger.warning(f"No items found with the name: [red]{item_name}[/red]")
            return None

        item = items[0]
        attachments = self.zot.children(item["key"])
        pdf_attachment = next(
            (
                att
                for att in attachments
                if att["data"].get("contentType") == "application/pdf"
            ),
            None,
        )

        if pdf_attachment:
            pdf_key = pdf_attachment["key"]
            pdf_filename = pdf_attachment["data"].get("filename", "Unknown.pdf")
            pdf_path = self.storage_folder / pdf_key / pdf_filename
            return ZoteroItem(
                key=item["key"],
                title=item["data"]["title"],
                pdf_path=pdf_path if pdf_path.exists() else None,
                authors=[
                    creator["firstName"] + " " + creator["lastName"]
                    for creator in item["data"]["creators"]
                    if creator["creatorType"] == "author"
                ],
                abstract=item["data"]["abstractNote"],
                url=item["data"]["url"],
                zotero_url=f"zotero://open-pdf/library/items/{pdf_key}",
            )

        logger.warning(f"No PDF found for item: [red]{item_name}[/red]")
        return None

@cache.memoize(typed=True, expire=60 * 60 * 24 * 7)
def find_zotero_item(item_name: str) -> ZoteroItem | None:
    return ZoteroLibrary().lookup_item_and_pdf(item_name)
