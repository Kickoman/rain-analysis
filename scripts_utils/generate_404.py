#!/usr/bin/env python3
"""Generate 404.html — the page GitHub Pages serves for a missing address.

This was the seventh hand-written copy of the page shell, and the only one no
generator produced: a static file under ``site/`` that the deploy copied
verbatim. It carried its own header, its own nav and its own footer, so every
change to the chrome had to be made here too, and nothing failed when it was
not. It also spelled ``/rain-analysis/`` into every href by hand, because a
404 is served from whatever depth the reader was browsing at.

Now it renders through ``page_shell.render_page`` like everything else, with
``root`` carrying that absolute prefix in one place.

No nav item is marked current: the reader is not on any of them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_shell import render_page  # noqa: E402

# GitHub Pages serves this project at /<repo>/, and a 404 can be served from
# any depth, so every link on it has to be absolute.
ROOT = "/rain-analysis/"

BODY = f"""        <section class="intro">
            <h1>page not found</h1>

<pre>$ curl -sI {ROOT}2026-13-45.html
HTTP/1.1 404 Not Found</pre>

            <p>That address does not exist here. Daily reports live under
            <a href="{ROOT}history/index.html">history</a>, and older ones are never
            removed — if you followed a link to a specific date, it should still be
            listed there.</p>

            <p><a href="{ROOT}index.html" class="btn">back to the homepage</a></p>
        </section>"""


def main() -> int:
    Path("404.html").write_text(render_page(
        title="Page not found",
        description="That page does not exist on the Rain Analysis site.",
        body=BODY,
        active="",
        root=ROOT,
    ), encoding="utf-8")
    print("[ok] 404.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
