from rmrf.export.note import MANAGED_END
from rmrf.export.note import merge_note
from rmrf.export.note import recorded_last_modified

RENDERED = """---
title: "Differential Transformer"
alias:
- "Differential Transformer"
created: 2026-06-07T11:46
updated: 2026-06-07T11:46
modified: 2026-11-21T15:00:00
authors: ['Tianzhu Ye', 'Li Dong']
tags:
- reMarkable
---

# Differential Transformer
## Pages
### Page 2
<mark>new highlight</mark>
"""


def test_new_note_uses_obsidian_style_frontmatter():
    note = merge_note(None, RENDERED, 1700000100000)
    assert note.startswith("---\ntitle: Differential Transformer\nalias:\n  - Differential Transformer\n")
    assert "created: 2026-06-07T11:46\n" in note
    assert "authors:\n  - Tianzhu Ye\n  - Li Dong\n" in note
    assert "<!-- rmrf:managed:start lastModified=1700000100000 -->\n# Differential Transformer" in note
    assert note.endswith(f"new highlight</mark>\n{MANAGED_END}\n")
    assert recorded_last_modified(note) == 1700000100000


def test_resync_keeps_user_frontmatter_and_text_outside_the_region():
    first = merge_note(None, RENDERED, 1)
    edited = (
        first.replace("tags:\n  - reMarkable\n", "tags:\n  - reMarkable\n  - speech\npublish: true\n")
        .replace("created: 2026-06-07T11:46", "created: 2024-01-01T09:00")
        .replace("---\n\n<!--", "---\n\nMy summary before.\n\n<!--")
        + "\nMy thoughts after.\n"
    )
    rendered = RENDERED.replace("new highlight", "newer highlight").replace("Li Dong", "Furu Wei")
    note = merge_note(edited, rendered, 2)

    assert "publish: true\n" in note
    assert "  - speech\n" in note  # tags belong to the user once the note exists
    assert "created: 2024-01-01T09:00\n" in note  # so does created
    assert "  - Furu Wei\n" in note and "Li Dong" not in note  # template keys refresh
    assert "My summary before.\n\n<!-- rmrf:managed:start lastModified=2 -->" in note
    assert note.endswith(f"{MANAGED_END}\n\nMy thoughts after.\n")
    assert "newer highlight" in note and "new highlight<" not in note
    assert recorded_last_modified(note) == 2


def test_legacy_note_without_markers_is_replaced_but_keeps_publish():
    legacy = """---
title: Differential Transformer
created: 2025-12-26
updated: 2026-10-23T17:04
modified: 2025-12-26 12:05:44:271441
tags:
  - reMarkable
publish: true
---

# Differential Transformer
old generated body
"""
    note = merge_note(legacy, RENDERED, 3)
    assert "old generated body" not in note
    assert "created: 2025-12-26\n" in note
    assert "updated: 2026-10-23T17:04\n" in note  # newer than the tablet's, so kept
    assert "modified: 2026-11-21T15:00:00\n" in note
    assert "publish: true\n" in note
    assert note.count("---\n") == 2


def test_rm_local_sync_region_is_taken_over():
    old = "---\ntitle: X\npublish: true\n---\n\n# X\n\n<!-- rm-local-sync:managed:start -->\nold\n<!-- rm-local-sync:managed:end -->\n"
    note = merge_note(old, RENDERED, 4)
    assert "rm-local-sync" not in note
    assert "\nold\n" not in note
    assert "publish: true\n" in note


def test_unchanged_input_is_stable():
    once = merge_note(None, RENDERED, 5)
    assert merge_note(once, RENDERED, 5) == once


def test_updated_moves_forward_only():
    older = merge_note(None, RENDERED.replace("updated: 2026-06-07T11:46", "updated: 2025-01-01T00:00"), 1)
    assert "updated: 2026-06-07T11:46\n" in merge_note(older, RENDERED, 2)
