"""End-to-end UI check in the locally installed Google Chrome (Playwright, channel="chrome").

Needs a backend connected to scripts/fake_dres.py (target 00031:3586-8008) and a Vite dev server.
Exercises: countdown, text search, keyboard navigation, HEVC playback + seek + loop, KIS submit (WRONG
then CORRECT via pasted image), AVS queue + crowding warning, auto-reset when the DRES task changes.

Usage: .venv/bin/python scripts/ui_e2e.py [--headed]
A separate test stack (so the real backend stays on the course DRES):
  .venv/bin/uvicorn scripts.fake_dres:app --port 8081
  DRES_URL=http://127.0.0.1:8081 DRES_USER=team DRES_PASS=secret VBS_SUBMIT_LOG=logs/submissions_test.jsonl \
      .venv/bin/uvicorn backend.app:app --port 8001
  (cd frontend && VBS_BACKEND=http://127.0.0.1:8001 npx vite --port 5174)
  VBS_UI_URL=http://localhost:5174 .venv/bin/python scripts/ui_e2e.py
"""
import os
import re
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

URL = os.getenv("VBS_UI_URL", "http://localhost:5173")
OUT = Path(__file__).resolve().parent.parent / "index" / "samples"


def video_state(page):
    return page.evaluate("""() => { const v = document.querySelector('video');
        return v && {t: v.currentTime * 1000, w: v.videoWidth, ready: v.readyState, paused: v.paused,
                     err: v.error && v.error.code} }""")


def range_inputs(page):
    return [int(x) for x in page.locator(".range input").evaluate_all("els => els.map(e => e.value)")]


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        check.failed = True


check.failed = False


def main():
    headed = "--headed" in sys.argv
    # This test deliberately submits WRONG answers: refuse to run against anything but the local fake DRES.
    url = httpx.get(f"{URL}/dres/status", timeout=10).json().get("url", "")
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        sys.exit(f"Refusing to run: backend is connected to {url or 'no DRES'}, not the local fake DRES. "
                 "Point .env at http://127.0.0.1:8081 (scripts/fake_dres.py) and restart the backend.")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=not headed,
                                    args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL)
        expect(page.locator(".dres")).to_contain_text("Practice run", timeout=10000)
        check(True, "DRES indicator shows active evaluation")
        expect(page.locator(".countdown")).to_have_text(re.compile(r"^\d+:\d\d$"), timeout=10000)
        check(True, f"countdown shows time left ({page.locator('.countdown').inner_text()})")
        page.click(".tasktype button:has-text('KIS')")
        page.locator(".qform input").focus()

        # --- KIS: text search -> play -> loop -> wrong submission
        page.fill(".qform input", "a person balancing on a highline rope above a valley")
        page.keyboard.press("Enter")
        expect(page.locator(".card").first).to_be_visible(timeout=10000)
        n = page.locator(".card").count()
        check(n >= 100, f"text search returned {n} result cards")
        page.keyboard.press("Escape")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowLeft")
        page.keyboard.press(" ")
        page.wait_for_function("() => { const v = document.querySelector('video'); return v && v.readyState >= 2 && v.currentTime > 0 }",
                               timeout=15000)
        start, end = range_inputs(page)
        st = video_state(page)
        check(st["w"] > 0 and st["err"] is None, f"HEVC decodes in Chrome (videoWidth={st['w']})")
        check(start - 100 <= st["t"] <= end + 300, f"seeked into shot: t={st['t']:.0f} in [{start}, {end}]")
        time.sleep((end - start) / 1000 + 1.5)
        st = video_state(page)
        check(start - 100 <= st["t"] <= end + 300 and not st["paused"], f"loop keeps playback in range: t={st['t']:.0f}")
        check(page.locator(".strip img").count() > 1, "shot timeline strip rendered")

        page.keyboard.press("s")
        expect(page.locator(".dialog")).to_be_visible()
        page.keyboard.press("y")
        expect(page.locator(".logrow").first).to_contain_text("WRONG", timeout=10000)
        check(True, "KIS submission of wrong video -> WRONG shown in log")

        # --- paste the target thumbnail as an image query -> correct submission
        page.evaluate("""async () => {
            const blob = await (await fetch('/thumb/shot00031_2')).blob();
            const dt = new DataTransfer(); dt.items.add(new File([blob], 'shot.png', {type: 'image/png'}));
            window.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt}));
        }""")
        expect(page.locator(".status")).to_contain_text("image:", timeout=10000)
        first = page.locator(".card .cap span").first.inner_text()
        check(first.startswith("00031 #2"), f"pasted image query -> top result {first}")
        page.keyboard.press(" ")
        expect(page.locator(".ptitle")).to_contain_text("00031")
        page.keyboard.press("s")
        expect(page.locator(".dialog .banner")).to_contain_text("WRONG")
        check(True, "confirm dialog warns after a previous WRONG")
        page.keyboard.press("Enter")
        expect(page.locator(".banner.ok")).to_contain_text("solved", timeout=10000)
        check(True, "CORRECT submission marks KIS task solved")
        page.keyboard.press("s")
        expect(page.locator(".status")).to_contain_text("already solved")
        check(page.locator(".dialog").count() == 0, "no second submission after solve")
        page.screenshot(path=str(OUT / "ui_kis.png"))

        # --- AVS: queue 5 shots from one video -> crowding warning -> submit all
        page.keyboard.press("Shift+N")
        page.keyboard.press("Escape")
        page.keyboard.press("t")
        expect(page.locator(".task-head")).to_contain_text("AVS task")
        # speech mode on words unique to one video's title -> top results all from 00057
        page.keyboard.press("2")
        page.fill(".qform input", "Grente Zwillinge")
        page.keyboard.press("Enter")
        expect(page.locator(".status")).to_contain_text("results", timeout=10000)
        page.keyboard.press("Escape")
        for _ in range(5):
            page.keyboard.press("a")
            page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("a")       # toggle off the last one again -> 4 queued
        check(page.locator(".qitem").count() == 4, f"AVS queue has {page.locator('.qitem').count()} shots")
        expect(page.locator(".task .banner.warn")).to_contain_text("More than 3")
        check(True, "crowding warning for >3 segments of one video")
        page.keyboard.press("s")
        expect(page.locator(".dialog pre")).to_be_visible()
        page.keyboard.press("y")
        expect(page.locator(".task-head")).to_contain_text("4 submitted", timeout=15000)
        check(page.locator(".qitem").count() == 0, "queue emptied after submit")
        page.keyboard.press("ArrowLeft")   # onto a submitted shot
        page.keyboard.press("a")
        expect(page.locator(".status")).to_contain_text("already submitted")
        check(True, "re-queueing a submitted shot is blocked")
        page.screenshot(path=str(OUT / "ui_avs.png"))

        # --- the DRES task changes: the UI must reset itself and pick KIS/AVS from the task group
        nxt = httpx.post(f"{url}/fake/next_task", timeout=10).json()
        want = "AVS" if "Ad-hoc" in nxt["taskGroup"] else "KIS"
        expect(page.locator(".status")).to_contain_text("New DRES task", timeout=8000)
        expect(page.locator(".task-head")).to_contain_text(f"{want} task")
        check(page.locator(".card").count() == 0 and page.locator(".qitem").count() == 0,
              f"task change '{nxt['name']}' -> UI reset itself and switched to {want}")

        check(not errors, f"no page errors {errors}")
        browser.close()
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
