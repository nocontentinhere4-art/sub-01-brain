"""#89 live check (2026-10-05 02:10 UTC, his phone): sciencenews.org's ad-block modal ("Looks like your ad blocker is
on. ... Please support our site by disabling your ad blocker. [DISABLE] Continue without supporting us") stayed over
the article although its text matches OVERLAY_WALL. The check read only the first 20000 characters of the page's text
(a modal appended after a long article is past that), not shadow roots or script-written frames, and the banner step
before it could press a modal's close button. Here, in a local Chromium on fixture pages (no network: every request
is fulfilled or aborted by the test): the modal is found at the end of a long article, in a shadow root, in a frame
and when it pops up late; the page is left and nothing in the modal is ever pressed.

    python -m pytest tests/test_overlay_walls_chromium.py -q
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browse  # noqa: E402

URL = "https://www.sciencenews.org/article/new-map-rivers-worth-protecting"
MODAL = ("<p>Looks like your ad blocker is on.</p><p>We rely on ads to keep creating quality content for you to "
         "enjoy for free.</p><p>Please support our site by disabling your ad blocker.</p>"
         "<button id='disable'>DISABLE</button><button id='close' aria-label='Close'>×</button>"
         "<a href='#' id='cont'>Continue without supporting us</a>")
ARTICLE = "<h1>A new map points out U.S. rivers most worth protecting</h1>" + "<p>" + (
    "Rivers carry water, sediment and life across the continent, and a new map ranks them. " * 400) + "</p>"
FIXED = "position:fixed;inset:10% 5%;background:#fff;z-index:99;padding:20px"
CLICKS = ("<script>window.clicked=[];document.addEventListener('click',e=>window.clicked.push(e.target.id||"
          "e.target.textContent),true);</script>")

PAGES = {
    "end": f"<html><body>{CLICKS}{ARTICLE}<div role='dialog' style='{FIXED}'>{MODAL}</div></body></html>",
    "shadow": f"""<html><body>{CLICKS}{ARTICLE}<div id='host'></div><script>
        const r = document.getElementById('host').attachShadow({{mode:'open'}});
        r.innerHTML = `<div style="{FIXED}">{MODAL}</div>`;</script></body></html>""",
    "frame": f"""<html><body>{CLICKS}{ARTICLE}<iframe id='f' style='{FIXED};width:90%;height:60%'></iframe><script>
        const d = document.getElementById('f').contentDocument; d.open();
        d.write(`<html><body>{MODAL}</body></html>`); d.close();</script></body></html>""",
    "late": f"""<html><body>{CLICKS}{ARTICLE}<script>setTimeout(() => {{ const m = document.createElement('div');
        m.setAttribute('style', '{FIXED}'); m.innerHTML = `{MODAL}`; document.body.appendChild(m); }}, 300);
        </script></body></html>""",
    "about": "<html><body><h1>How ad blockers work</h1>" + "<p>" + (
        "Publishers worry about ad blockers, and the best ad blockers for 2026 are compared here. " * 400)
        + "</p></body></html>",
}


async def _page(kind):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright not installed")
    pw = await async_playwright().start()
    br = None
    for exe in [None, os.environ.get("BROWSE_CHROMIUM") or "/opt/pw-browsers/chromium"]:
        try:
            br = await pw.chromium.launch(args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
            break
        except Exception as e:                                                   # no usable Chromium here
            err = e
    if br is None:
        await pw.stop()
        pytest.skip(f"chromium did not start: {err!r}"[:200])
    page = await br.new_page(viewport={"width": 390, "height": 844})

    async def route(r):                                                          # no network at all
        if r.request.url.split("#")[0] == URL:
            return await r.fulfill(status=200, content_type="text/html", body=PAGES[kind])
        return await r.abort()
    await page.route("**/*", route)
    await page.goto(URL, wait_until="domcontentloaded")
    return pw, br, page


def run(kind, fn):
    async def go():
        pw, br, page = await _page(kind)
        try:
            return await fn(page)
        finally:
            await br.close()
            await pw.stop()
    return asyncio.run(go())


@pytest.mark.parametrize("kind", ["end", "shadow", "frame"])
def test_the_modal_is_found_past_the_first_20000_characters_in_a_shadow_root_and_in_a_frame(kind):
    async def fn(page):
        body = await page.evaluate("() => document.body.innerText.slice(0, 20000)")
        assert not browse.overlay_wall(body)                                    # what the old check read
        return await browse.Browser(decide=False)._overlay_walled(page)
    assert run(kind, fn)


def test_an_article_about_ad_blockers_is_not_a_wall():
    assert not run("about", lambda page: browse.Browser(decide=False)._overlay_walled(page))


@pytest.mark.parametrize("kind", ["end", "shadow", "frame"])
def test_the_page_is_left_and_nothing_in_the_modal_is_pressed(kind):
    async def fn(page):
        b = browse.Browser(decide=False)
        sc = b.screens["phone"]
        sc.page, sc.ctx = page, page.context
        shown, left = [], []

        async def show(sc_):
            shown.append(sc_.page.url)
            return True

        async def leave(sc_):
            left.append(sc_.page.url)
            return False
        b.show, b._leave = show, leave
        assert not await b._settle(sc, "followed a link", "page")
        clicked = await page.evaluate("() => window.clicked")
        return b, shown, left, clicked
    b, shown, left, clicked = run(kind, fn)
    assert b.last_skip == "overlay wall" and shown == [] and left == [URL]
    assert clicked == [] and b.dismissed == []                                   # never closed, never "continued"
    assert b.walled["sciencenews.org"] > time.time() + browse.OVERLAY_COOLDOWN_S - 60


def test_a_modal_that_pops_up_late_is_left_at_the_next_screenshot():
    async def fn(page):
        b = browse.Browser(decide=False)
        sc = b.screens["phone"]
        sc.page = page
        left = []

        async def leave(sc_):
            left.append(sc_.page.url)
        b._leave = leave
        first = await b._overlay_walled(page)                                   # before the popup
        await page.wait_for_timeout(600)
        return first, await b._shoot(sc), left, b
    first, shot, left, b = run("late", fn)
    assert first is False and shot is False and left == [URL] and b.last_skip == "overlay wall"
