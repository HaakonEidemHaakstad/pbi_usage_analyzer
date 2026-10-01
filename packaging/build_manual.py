"""Render docs/manual/USER_MANUAL.md as one self-contained HTML file.

Usage: python packaging/build_manual.py OUTPUT.html

Images are embedded, so the file can be opened, printed or saved as PDF from any
browser without the docs folder. Needs the `markdown` package (requirements-build.txt).
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import markdown

MANUAL = Path(__file__).resolve().parent.parent / "docs" / "manual" / "USER_MANUAL.md"

STYLE = """
body { font-family: "Segoe UI", Arial, sans-serif; line-height: 1.5; color: #1f1f1f;
       max-width: 920px; margin: 2em auto; padding: 0 1.5em; }
h1 { border-bottom: 2px solid #f2c811; padding-bottom: .3em; }
h2 { margin-top: 2em; border-bottom: 1px solid #ddd; padding-bottom: .2em; page-break-after: avoid; }
table { border-collapse: collapse; margin: 1em 0; width: 100%; }
th, td { border: 1px solid #ccc; padding: .4em .6em; text-align: left; vertical-align: top; }
th { background: #f4f4f4; }
code, pre { font-family: Consolas, monospace; background: #f4f4f4; border-radius: 3px; }
code { padding: .1em .3em; }
pre { padding: .8em; overflow-x: auto; }
img { max-width: 100%; border: 1px solid #ccc; margin: .5em 0; }
blockquote { border-left: 4px solid #f2c811; margin: 1em 0; padding: .2em 1em; background: #fffbea; }
a { color: #0b5cad; }
@media print { body { margin: 0; max-width: none; } a { color: inherit; text-decoration: none; }
               img, table, pre { page-break-inside: avoid; } }
"""


def embed_images(html: str, base: Path) -> str:
    def data_uri(match: re.Match) -> str:
        path = base / match.group(2)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'{match.group(1)}"data:image/png;base64,{encoded}"'
    return re.sub(r'(<img[^>]*?src=)"([^"]+\.png)"', data_uri, html)


def build(output: Path) -> None:
    text = MANUAL.read_text(encoding="utf-8")
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"], output_format="html")
    body = embed_images(body, MANUAL.parent)
    title = text.splitlines()[0].lstrip("# ").strip()
    output.write_text(f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{STYLE}</style></head>
<body>
{body}
</body></html>
""", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python packaging/build_manual.py OUTPUT.html")
    build(Path(sys.argv[1]))
