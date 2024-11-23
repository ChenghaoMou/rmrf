# rmrf

> **Warning**
> This project is under active development for my personal use. APIs may change.

rmrf is a Python library for processing and converting reMarkable tablet files (`.rm`). It provides utilities for parsing, rendering, and exporting reMarkable documents to Markdown and SVG. It is built on top of [rmscene](https://github.com/ricklupton/rmscene) and is mainly for my personal use.

## Features

- Only works locally with a reMarkable backup folder (only RMPP is tested)
- Parse reMarkable file formats (only v3 or v6 in terms of lines format is tested)
- Extract highlights and annotations from reMarkable files and convert them into Markdown or SVG, ideally for Obsidian with **Jinja** templates

## Installation

To install rmrf, you need Python 3.10 or later. You can install it using pip:

```bash
pip install git+https://github.com/ChenghaoMou/rmrf.git
```

## Usage

Here's a basic example of how to use rmrf:

```python
from rmrf import FileSystem, MarkdownWriter, update, paper_title_getter

BACKUP_DIR = Path("path to your reMarkable backup folder locally")
CACHE_DIR = Path("path to your cache folder locally")
TARGET_DIR = Path("path to your target obsidian folder locally")
STATIC_DIR = Path("path to your obsidian static folder locally")

TEMPLATE = Path("path to your jinja template")

fs = FileSystem(BACKUP_DIR, CACHE_DIR)
writer = MarkdownWriter(
    target_dir=TARGET_DIR,
    static_dir=STATIC_DIR,
    cache_dir=CACHE_DIR,
    title_getter=paper_title_getter,
    template=TEMPLATE,
    enable_zotero=False,
)
# Parse papers from the reMarkable backup folder 
# and export to Markdown in the target folder
update(
    fs=fs,
    prefix="/Root/Papers",
    writer=writer,
    force=True,  # overwrite existing files
)
```

## Template

<details>

<summary>Default Template</summary>

```markdown
---
title: "{{ title | default('Untitled') }}"
{%- if alias is defined and alias %}
alias:
- "{{ alias }}"
{%- endif %}
{%- if created is defined and created %}
created: {{ created }}
{%- endif %}
{%- if updated is defined and updated %}
updated: {{ updated }}
{%- endif %}
{%- if modified is defined and modified %}
modified: {{ modified }}
{%- endif %}
tags:
- reMarkable
---

# {{ original_title | default(title) }}

{%- if pages is defined and pages %}
## Pages

{%- for page_idx, tags, highlights in pages %}
### Page {{ page_idx }}

{%- if tags %}
**Tags**: {{ tags | join(', ') }}
{%- endif %}
{%- if highlights %}
**Highlights**:
{% for highlight in highlights %}
{%- if highlight is string %}
{{ highlight }}
{%- else %}
{%- if highlight|length == 5 %}
{%- set r, g, b, a, text = highlight %}
<mark style="background-color: rgba({{ r }}, {{ g }}, {{ b }}, {{ a }})">{{ text }}</mark>
{%- else %}
{{ highlight }}
{%- endif %}
{%- endif %}
{%- endfor %}
{%- endif %}

{%- endfor %}
{%- endif %}
```

</details>

<details>

<summary>Zotero Template</summary>

```markdown
---
title: "{{ title | default('Untitled') }}"
{%- if alias is defined and alias %}
alias:
- "{{ alias }}"
{%- endif %}
{%- if created is defined and created %}
created: {{ created }}
{%- endif %}
{%- if updated is defined and updated %}
updated: {{ updated }}
{%- endif %}
{%- if modified is defined and modified %}
modified: {{ modified }}
{%- endif %}
{%- if authors is defined and authors %}
authors: {{ authors }}
{%- endif %}
{%- if url is defined and url %}
url: {{ url }}
{%- endif %}
{%- if zotero_url is defined and zotero_url %}
zotero_url: {{ zotero_url }}
{%- endif %}
tags:
- reMarkable
---

# {{ original_title | default(title) }}

{%- if zotero_url is defined and zotero_url %}
[Open in Zotero]({{ zotero_url }})
{%- endif %}

{%- if abstract is defined and abstract %}
## Abstract

{{ abstract }}
{%- endif %}

{%- if pages is defined and pages %}
## Pages

{%- for page_idx, tags, highlights in pages %}
### Page {{ page_idx }}

{%- if tags %}
**Tags**: {{ tags | join(', ') }}
{%- endif %}

{%- if highlights %}
**Highlights**:
{% for highlight in highlights %}
{%- if highlight is string %}
{{ highlight }}
{%- else %}
{%- if highlight|length == 5 %}
{%- set r, g, b, a, text = highlight %}
<mark style="background-color: rgba({{ r }}, {{ g }}, {{ b }}, {{ a }})">{{ text }}</mark>
{%- else %}
{{ highlight }}
{%- endif %}
{%- endif %}
{%- endfor %}
{%- endif %}

{%- endfor %}
{%- endif %}
```

</details>

### Default Templates

```python
Template = """---
title: "{title}"
alias:
  - "{alias}"
created: {created}
updated: {updated}
modified: {modified}
tags:
  - reMarkable
---

# {original_title}

## Pages
{pages}
"""

Highlight_Template = """
<mark style="background-color: #{r:02x}{g:02x}{b:02x};">{text}</mark>
"""

Page_Template = """
## Page {page_index}

{tags}

{highlights}
"""
```

## Zotero Template

To work with Zotero, you need to provide the following environment variables:

```bash
ZOTERO_USER_ID=""
ZOTERO_LIB_KEY=""
STORAGE_FOLDER="/Path/to/your/Zotero/storage"
```

For zotero template, you can use the following additional variables:

- `authors`: the authors of the paper, joined by `,`
- `url`: the url of the paper
- `zotero_url`: the url of the zotero item
- `abstract`: the abstract of the paper

```python
Zotero_Template = """---
title: "{title}"
alias:
  - "{alias}"
created: {created}
updated: {updated}
modified: {modified}
authors: {authors}
url: {url}
zotero_url: {zotero_url}
tags:
  - reMarkable
---

# {original_title}

[Open in Zotero]({zotero_url})

## Abstract
{abstract}

## Pages
{pages}
"""
```

## Annotation Conventions

This is what you see in the reMarkable app:
![Screenshot](./static/screenshot.png)

This is what you get after exporting to Markdown:
![Exported Markdown](./static/export.png)

Another set of example for text rendering misalignment:
![Screenshot 2](./static/screenshot2.png)

This is what you get after exporting to SVG:
![Exported SVG](./static/export2.png)

1. For PDF or EPub files
   1. you can draw a box (in one stroke) to crop out a part of the page. It will be embedded in the markdown as an image. (See the first set of screenshots above) (This is differentiated from handwriting by some crude heuristics, which means you *can't* draw box-adjacent shapes freely as they will create multiple cropped images)
   2. highlights will be rendered in markdown as `<mark>` tags.
   3. Handwriting is exported as SVG for annotated pages.
2. Typed text may **interfere** with the rendering with misalignment. They may have **incorrect styles**, though I try to preserve as much as possible. (See the second set of screenshots above)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgements

This project is based on various open-source projects and research into the reMarkable file format. Special thanks to:

- [maxio](https://github.com/lschwetlick/maxio)
- [rmc](https://github.com/ricklupton/rmc)
- [rmscene](https://github.com/ricklupton/rmscene)

## Sponsors

This project is supported by [@Azeirah](https://github.com/Azeirah) who created the [Scrybble](https://scrybble.ink/) project. If you want to export your reMarkable highlights to Obsidian without any technical setup, feel free to check it out!
