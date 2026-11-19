"""Start headless Chromium via Playwright, tolerating a browser build that doesn't
exactly match the installed playwright version (common in pre-baked images)."""
from __future__ import annotations

import glob
import logging
import os
import shutil
from contextlib import contextmanager

log = logging.getLogger(__name__)


def _candidate_executables() -> list[str]:
    roots = [os.getenv("PLAYWRIGHT_BROWSERS_PATH", ""), "/opt/pw-browsers",
             os.path.expanduser("~/.cache/ms-playwright")]
    found: list[str] = []
    for r in filter(None, roots):
        found += sorted(glob.glob(f"{r}/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"),
                        reverse=True)
        found += sorted(glob.glob(f"{r}/chromium-*/chrome-linux*/chrome"), reverse=True)
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            found.append(p)
    exe = os.getenv("STUDIO_CHROMIUM")
    return ([exe] if exe else []) + found


def launch(p):
    """Launch chromium from a sync_playwright() handle."""
    try:
        return p.chromium.launch()
    except Exception as first:
        for exe in _candidate_executables():
            try:
                b = p.chromium.launch(executable_path=exe)
                log.info("Using Chromium at %s", exe)
                return b
            except Exception:
                continue
        raise RuntimeError(
            "Could not start Chromium. Run `playwright install chromium` "
            "or set STUDIO_CHROMIUM=/path/to/chrome."
        ) from first


@contextmanager
def browser_page(width: int = 1080, height: int = 1350):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = launch(p)
        try:
            ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            page = ctx.new_page()
            yield page
            ctx.close()
        finally:
            browser.close()
