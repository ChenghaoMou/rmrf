"""
Merge a freshly rendered note into an existing one without losing what the user wrote.

A note has two parts that the exporter owns:

- frontmatter keys present in the rendered template; everything else in the existing
  frontmatter (``publish``, extra tags, ...) is kept verbatim, in place.
- the body between ``MANAGED_START`` and ``MANAGED_END``; text before and after the
  markers is kept.

The start marker also records the tablet's ``lastModified`` so an unchanged document
can be skipped without extracting its highlights again.
"""

import math
import re

import yaml

MANAGED_START = "<!-- rmrf:managed:start -->"
MANAGED_END = "<!-- rmrf:managed:end -->"

# Older markers that are replaced by ours on the next sync.
_START = re.compile(r"<!-- (?:rmrf|rm-local-sync):managed:start(?: lastModified=(\d+))? -->")
_END = re.compile(r"<!-- (?:rmrf|rm-local-sync):managed:end -->")
_TOP_LEVEL_KEY = re.compile(r"^([^\s#\-][^:]*):(?:\s|$)")

# Keys the user (or an Obsidian plugin) owns once the note exists.
KEEP_EXISTING = frozenset({"created", "tags"})
# ISO dates that only move forward: an Obsidian edit can be newer than the tablet's.
NEVER_BACKWARDS = frozenset({"updated"})


class _Loader(yaml.SafeLoader):
    """Safe loader that keeps dates as the strings they were written as."""


class _Dumper(yaml.SafeDumper):
    """Safe dumper that writes dates unquoted and indents lists the way Obsidian does."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


for _cls in (_Loader, _Dumper):
    _cls.yaml_implicit_resolvers = {
        first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter without the --- fences, body)."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    after = text.find("\n", end + 4)
    body = "" if after == -1 else text[after + 1 :]
    return text[4 : end + 1], body


def _key_blocks(frontmatter: str) -> list[tuple[str | None, str]]:
    """Split frontmatter text into (key, text) blocks; leading comments get key None."""
    blocks: list[tuple[str | None, str]] = []
    for line in frontmatter.splitlines(keepends=True):
        match = _TOP_LEVEL_KEY.match(line)
        if match:
            blocks.append((match.group(1).strip(), line))
        elif blocks:
            key, text = blocks[-1]
            blocks[-1] = (key, text + line)
        else:
            blocks.append((None, line))
    return blocks


def dump_key(key: str, value) -> str:
    return yaml.dump(
        {key: value},
        Dumper=_Dumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=math.inf,
    )


def _is_newer(key: str | None, text: str, fresh) -> bool:
    if key not in NEVER_BACKWARDS:
        return False
    try:
        existing = (yaml.load(text, Loader=_Loader) or {}).get(key)
    except yaml.YAMLError:
        return False
    return isinstance(existing, str) and isinstance(fresh, str) and existing > fresh


def merge_frontmatter(existing: str | None, rendered: str) -> str:
    """Refresh the keys the template renders; keep every other existing key verbatim."""
    fresh = yaml.load(rendered, Loader=_Loader) or {}
    if not isinstance(fresh, dict):
        raise ValueError(f"Template frontmatter is not a mapping: {rendered!r}")

    blocks = _key_blocks(existing) if existing else []
    present = {key for key, _ in blocks}
    lines: list[str] = []
    for key, text in blocks:
        if key in fresh and key not in KEEP_EXISTING and not _is_newer(key, text, fresh[key]):
            lines.append(dump_key(key, fresh[key]))
        else:
            lines.append(text if text.endswith("\n") else text + "\n")
    for key, value in fresh.items():
        if key not in present:
            lines.append(dump_key(key, value))
    return "".join(lines)


def managed_region(body: str, last_modified: int | None) -> str:
    start = (
        MANAGED_START if last_modified is None else MANAGED_START.replace(" -->", f" lastModified={last_modified} -->")
    )
    return f"{start}\n{body.strip()}\n{MANAGED_END}"


def recorded_last_modified(text: str) -> int | None:
    match = _START.search(text)
    return int(match.group(1)) if match and match.group(1) else None


def merge_note(existing: str | None, rendered: str, last_modified: int | None) -> str:
    """Combine a rendered note with the existing note on disk.

    Without an existing managed region (a note from before managed regions), the whole
    existing body is replaced, because it was entirely generated.
    """
    rendered_fm, rendered_body = split_frontmatter(rendered)
    region = managed_region(rendered_body, last_modified)

    if existing is None:
        existing_fm, existing_body = None, ""
    else:
        existing_fm, existing_body = split_frontmatter(existing)

    start = _START.search(existing_body)
    end = _END.search(existing_body, start.end()) if start else None
    if start and end:
        body = existing_body[: start.start()] + region + existing_body[end.end() :]
    else:
        body = region + "\n"

    if rendered_fm is None:
        return body
    return f"---\n{merge_frontmatter(existing_fm, rendered_fm)}---\n\n{body.lstrip(chr(10))}"
