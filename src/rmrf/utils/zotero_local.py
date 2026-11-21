"""
Read a Zotero library straight from the local ``zotero.sqlite``.

Works offline, without Zotero running and without a Web API key. The database is
opened read-only and ``immutable`` so a running Zotero's lock does not get in the way.
"""

import sqlite3
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from rmrf.utils.zotero_helper import ZoteroItem

_ITEMS = """
SELECT parent.itemID, parent.key, attachment.key, a.path,
       (SELECT v.value FROM itemData d
          JOIN fieldsCombined f ON f.fieldID = d.fieldID
          JOIN itemDataValues v ON v.valueID = d.valueID
         WHERE d.itemID = parent.itemID AND f.fieldName = 'title') AS title
  FROM itemAttachments a
  JOIN items attachment ON attachment.itemID = a.itemID
  JOIN items parent ON parent.itemID = a.parentItemID
 WHERE a.contentType = 'application/pdf'
   AND a.path LIKE 'storage:%'
   AND a.itemID NOT IN (SELECT itemID FROM deletedItems)
   AND parent.itemID NOT IN (SELECT itemID FROM deletedItems)
"""

_FIELD = """
SELECT v.value FROM itemData d
  JOIN fieldsCombined f ON f.fieldID = d.fieldID
  JOIN itemDataValues v ON v.valueID = d.valueID
 WHERE d.itemID = ? AND f.fieldName = ?
"""

_AUTHORS = """
SELECT c.firstName, c.lastName FROM itemCreators ic
  JOIN creators c ON c.creatorID = ic.creatorID
  JOIN creatorTypes t ON t.creatorTypeID = ic.creatorTypeID
 WHERE ic.itemID = ? AND t.creatorType = 'author'
 ORDER BY ic.orderIndex
"""


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


@dataclass
class _Attachment:
    item_id: int
    item_key: str
    attachment_key: str
    filename: str
    title: str


class LocalZotero:
    def __init__(self, data_dir: str | Path = Path.home() / "Zotero"):
        self.data_dir = Path(data_dir).expanduser()
        self.database = self.data_dir / "zotero.sqlite"
        if not self.database.exists():
            raise FileNotFoundError(f"Zotero database not found: {self.database}")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.database}?mode=ro&immutable=1", uri=True)

    def _attachments(self, connection: sqlite3.Connection) -> list[_Attachment]:
        return [
            _Attachment(item_id, item_key, attachment_key, path.removeprefix("storage:"), title or "")
            for item_id, item_key, attachment_key, path, title in connection.execute(_ITEMS)
        ]

    def _item(self, connection: sqlite3.Connection, attachment: _Attachment) -> ZoteroItem:
        def field(name: str) -> str:
            row = connection.execute(_FIELD, (attachment.item_id, name)).fetchone()
            return row[0] if row else ""

        pdf_path = self.data_dir / "storage" / attachment.attachment_key / attachment.filename
        return ZoteroItem(
            key=attachment.item_key,
            title=attachment.title,
            pdf_path=pdf_path if pdf_path.exists() else None,
            authors=[
                " ".join(part for part in (first, last) if part)
                for first, last in connection.execute(_AUTHORS, (attachment.item_id,))
            ],
            abstract=field("abstractNote"),
            url=field("url"),
            zotero_url=f"zotero://open-pdf/library/items/{attachment.attachment_key}",
        )

    def search(self, query: str, limit: int = 10) -> list[ZoteroItem]:
        """Items whose title or PDF filename best match ``query``, best first."""
        wanted = _normalize(query)
        with self._connect() as connection:
            scored = []
            for attachment in self._attachments(connection):
                best = 0.0
                for candidate in (attachment.title, Path(attachment.filename).stem):
                    text = _normalize(candidate)
                    if not text:
                        continue
                    score = 1.0 if wanted in text else SequenceMatcher(None, wanted, text).ratio()
                    best = max(best, score)
                scored.append((best, attachment))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [self._item(connection, attachment) for score, attachment in scored[:limit] if score > 0.5]

    def find_document(self, name: str, title: str | None = None) -> ZoteroItem | None:
        """The item for a document sent to the tablet.

        ``name`` is the document's name on the tablet, which is the PDF's filename
        without extension when it was sent from Zotero. Falls back to a close title match.
        """
        wanted_file = _normalize(name)
        wanted_title = _normalize(title or name)
        with self._connect() as connection:
            attachments = self._attachments(connection)
            for attachment in attachments:
                if _normalize(Path(attachment.filename).stem) == wanted_file:
                    return self._item(connection, attachment)
            best = max(
                attachments,
                key=lambda a: SequenceMatcher(None, wanted_title, _normalize(a.title)).ratio(),
                default=None,
            )
            if best and SequenceMatcher(None, wanted_title, _normalize(best.title)).ratio() >= 0.9:
                return self._item(connection, best)
        return None
