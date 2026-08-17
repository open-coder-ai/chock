"""Render promo.html to PNG frames via headless Chromium.

Usage:
  python render_frames.py test              -> sample stills into frames_test/
  python render_frames.py full [fps]        -> every frame into frames/
  python render_frames.py range <t0> <t1>   -> re-render a slice of frames/ after an edit
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
URL = (HERE / "promo.html").as_uri()

TEST_TIMES = [3.0, 6.5, 9.8, 17.0, 28.0, 32.5, 38.5, 41.5, 47.0, 53.5, 64.5, 72.0]


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    fps = int(sys.argv[2]) if mode == "full" and len(sys.argv) > 2 else 30

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(URL)
        page.wait_for_function("typeof window.seek === 'function'")
        canvas = page.locator("#c")
        total = page.evaluate("window.TOTAL")

        if mode == "test":
            out = HERE / "frames_test"
            out.mkdir(exist_ok=True)
            for t in TEST_TIMES:
                page.evaluate(f"window.seek({t})")
                canvas.screenshot(path=str(out / f"t{t:05.1f}.png"))
            print(f"wrote {len(TEST_TIMES)} test frames to {out}")
        elif mode == "range":
            t0, t1 = float(sys.argv[2]), float(sys.argv[3])
            fps = int(sys.argv[4]) if len(sys.argv) > 4 else 30
            out = HERE / "frames"
            out.mkdir(exist_ok=True)
            for i in range(int(t0 * fps), min(int(t1 * fps), int(total * fps))):
                page.evaluate(f"window.seek({i / fps})")
                canvas.screenshot(path=str(out / f"f{i:05d}.png"))
            print(f"re-rendered frames {int(t0 * fps)}..{int(t1 * fps)}")
        else:
            out = HERE / "frames"
            out.mkdir(exist_ok=True)
            n = int(total * fps)
            for i in range(n):
                page.evaluate(f"window.seek({i / fps})")
                canvas.screenshot(path=str(out / f"f{i:05d}.png"))
                if i % 300 == 0:
                    print(f"{i}/{n}", flush=True)
            print(f"wrote {n} frames at {fps}fps to {out}")

        browser.close()


if __name__ == "__main__":
    main()
