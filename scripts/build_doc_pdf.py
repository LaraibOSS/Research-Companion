#!/usr/bin/env python3
"""Render a markdown document to PDF, with Mermaid diagrams drawn as diagrams.

The docs carry Mermaid blocks. Every markdown-to-PDF converter that does not run
a browser leaves them as unreadable code listings -- the diagrams are the point,
so this drives headless Chromium and prints from there.

Usage::

    python scripts/build_doc_pdf.py docs/WALKTHROUGH.md
    python scripts/build_doc_pdf.py docs/WALKTHROUGH.md -o out.pdf

Needs `markdown` and `playwright` (with Chromium installed), and network access
on first run to fetch the Mermaid bundle -- the fetched copy is cached beside the
script so later builds are offline.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import urllib.request

MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
CACHE = pathlib.Path(__file__).with_name(".mermaid.min.js")

# Print CSS. Sized for reading on paper rather than mirroring the screen: a
# narrower measure, real margins, and diagrams that never straddle a page break.
STYLE = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 10.5pt; line-height: 1.55; color: #1f2328; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1 { font-size: 22pt; margin: 0 0 4pt; letter-spacing: -0.4pt; }
h2 {
  font-size: 14pt; margin: 22pt 0 8pt; padding-top: 8pt;
  border-top: 1px solid #d1d9e0; break-after: avoid; break-inside: avoid;
}
h3 { font-size: 11.5pt; margin: 14pt 0 5pt; break-after: avoid; }
h1 + p { color: #59636e; font-size: 11pt; }
p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 18pt; }
li { margin: 2pt 0; }
a { color: #0969da; text-decoration: none; }
code {
  font-family: "SF Mono", Consolas, "Liberation Mono", monospace;
  font-size: 9pt; background: #f6f8fa; padding: 1pt 4pt; border-radius: 3px;
}
pre {
  background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px;
  padding: 9pt 11pt; overflow-x: auto; break-inside: avoid;
}
pre code { background: none; padding: 0; font-size: 8.5pt; line-height: 1.45; }
blockquote {
  margin: 10pt 0; padding: 6pt 12pt; border-left: 3px solid #8250df;
  background: #fbfaff; color: #3b3555; break-inside: avoid;
}
table {
  border-collapse: collapse; width: 100%; margin: 10pt 0;
  font-size: 9.5pt; break-inside: avoid;
}
th, td { border: 1px solid #d1d9e0; padding: 5pt 8pt; text-align: left; vertical-align: top; }
th { background: #f6f8fa; font-weight: 600; }
hr { border: 0; border-top: 1px solid #d1d9e0; margin: 16pt 0; }
.mermaid {
  text-align: center; margin: 12pt 0; break-inside: avoid; page-break-inside: avoid;
}
.mermaid svg { max-width: 100%; height: auto; }
/* The rendered table of contents is navigation; on paper it is dead weight
   beyond the first page, so keep it compact. */
h2#contents + ul { columns: 2; column-gap: 22pt; font-size: 9.5pt; }
"""


def _mermaid_js() -> str:
    if CACHE.is_file():
        return CACHE.read_text(encoding="utf-8")
    with urllib.request.urlopen(MERMAID_URL, timeout=60) as resp:  # noqa: S310
        js = resp.read().decode("utf-8")
    CACHE.write_text(js, encoding="utf-8")
    return js


def _to_html(md_text: str, title: str, mermaid_js: str) -> str:
    import markdown as md

    # Pull the mermaid blocks out before markdown sees them: the code-fence
    # renderer would escape the arrows into entities that mermaid cannot parse.
    blocks: list[str] = []

    def _stash(match: re.Match) -> str:
        blocks.append(match.group(1))
        return f"@@MERMAID{len(blocks) - 1}@@"

    md_text = re.sub(r"```mermaid\n(.*?)```", _stash, md_text, flags=re.S)

    html = md.markdown(md_text, extensions=["tables", "fenced_code", "toc", "attr_list"])

    for i, block in enumerate(blocks):
        # markdown wraps the lone placeholder in a paragraph; replace either form.
        div = f'<div class="mermaid">{block}</div>'
        html = html.replace(f"<p>@@MERMAID{i}@@</p>", div).replace(f"@@MERMAID{i}@@", div)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{STYLE}</style></head>
<body>{html}
<script>{mermaid_js}</script>
<script>
  mermaid.initialize({{ startOnLoad: false, theme: 'default',
                        flowchart: {{ useMaxWidth: true, htmlLabels: true }} }});
  window.__diagrams = document.querySelectorAll('.mermaid').length;
  mermaid.run().then(() => {{ window.__mermaidDone = true; }})
               .catch(e => {{ window.__mermaidError = String(e); }});
</script>
</body></html>"""


def build(src: pathlib.Path, out: pathlib.Path) -> int:
    from playwright.sync_api import sync_playwright

    text = src.read_text(encoding="utf-8")
    title = next((ln.lstrip("# ").strip() for ln in text.splitlines()
                  if ln.startswith("# ")), src.stem)

    html_path = out.with_suffix(".build.html")
    html_path.write_text(_to_html(text, title, _mermaid_js()), encoding="utf-8")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(html_path.resolve().as_uri(), wait_until="load")

        # Fail loudly rather than shipping a PDF of unrendered code blocks.
        page.wait_for_function("window.__mermaidDone === true || window.__mermaidError",
                               timeout=90_000)
        err = page.evaluate("window.__mermaidError || null")
        if err:
            print(f"mermaid failed to render: {err}", file=sys.stderr)
            browser.close()
            return 1

        expected = page.evaluate("window.__diagrams")
        drawn = page.evaluate("document.querySelectorAll('.mermaid svg').length")
        if drawn != expected:
            print(f"only {drawn}/{expected} diagrams rendered", file=sys.stderr)
            browser.close()
            return 1

        page.pdf(path=str(out), format="A4", print_background=True,
                 margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
                 display_header_footer=True,
                 header_template="<div></div>",
                 footer_template=(
                     '<div style="width:100%;font-size:8pt;color:#8b949e;'
                     'padding:0 16mm;display:flex;justify-content:space-between">'
                     f'<span>{title}</span>'
                     '<span class="pageNumber"></span></div>'))
        browser.close()

        if errors:
            print(f"note: {len(errors)} page error(s): {errors[0][:120]}", file=sys.stderr)

    html_path.unlink(missing_ok=True)
    kb = out.stat().st_size // 1024
    print(f"{out}  ({kb} KB, {expected} diagrams)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=pathlib.Path, help="markdown file to render")
    ap.add_argument("-o", "--output", type=pathlib.Path, help="output .pdf")
    args = ap.parse_args()

    if not args.source.is_file():
        print(f"no such file: {args.source}", file=sys.stderr)
        return 1
    return build(args.source, args.output or args.source.with_suffix(".pdf"))


if __name__ == "__main__":
    raise SystemExit(main())
