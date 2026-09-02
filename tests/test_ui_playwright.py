"""可选 Playwright 冒烟：未安装则跳过。

运行：
  pip install playwright
  playwright install chromium
  PLAYWRIGHT=1 python tests/test_ui_playwright.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _skip(msg: str) -> None:
    print(f"SKIP playwright: {msg}")
    sys.exit(0)


def main():
    if os.environ.get("PLAYWRIGHT") not in ("1", "true", "yes"):
        _skip("set PLAYWRIGHT=1 to enable")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _skip("pip install playwright && playwright install chromium")

    import uvicorn
    from server.app import app

    port = int(os.environ.get("PLAYWRIGHT_PORT", "8765"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(40):
        if server.started:
            break
        time.sleep(0.1)

    url = f"http://127.0.0.1:{port}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        assert "溯知" in page.title()
        assert page.locator("#dialogueThread").count() == 1
        page.fill("#topicInput", "")
        page.click("#startBtn")
        page.wait_for_timeout(300)
        page.fill("#topicInput", "自动化冒烟课题")
        assert page.locator("#openKnowledgeBtn").count() == 1
        browser.close()
    server.should_exit = True
    print("PLAYWRIGHT SMOKE PASSED")


if __name__ == "__main__":
    main()
