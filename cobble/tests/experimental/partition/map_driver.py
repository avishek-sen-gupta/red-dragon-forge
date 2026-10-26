"""Drives the program map in headless Chromium: load it, read what it drew, search a program, click it."""

from __future__ import annotations

from pathlib import Path

from tests.experimental.partition.map_report import MapReport
from tests.experimental.partition.page_driver import WEBGL
from playwright.sync_api import Page, sync_playwright

HREFS = "graph.filterNodes((id, d) => d.href).map(id => graph.getNodeAttribute(id, 'href')).sort()"


def _drive(page: Page, url: str, errors: list[str]) -> MapReport:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.wait_for_function("typeof renderer !== 'undefined'")
    counts = page.evaluate("[graph.order, graph.size]")
    hrefs = tuple(page.evaluate(HREFS))
    page.locator("#search").fill("q")
    page.locator("#search").press("Enter")
    searched = page.evaluate("selected")
    page.evaluate("renderer.emit('clickNode', { node: 'Q' })")
    page.wait_for_url("**/programs/Q.html")
    return MapReport(
        errors=tuple(errors),
        nodes=counts[0],
        edges=counts[1],
        hrefs=hrefs,
        searched=searched,
        clicked=page.url.rsplit("/", 2)[1] + "/" + page.url.rsplit("/", 1)[1],
    )


def drive_map(path: Path) -> MapReport:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=list(WEBGL))
        report = _drive(browser.new_page(), path.resolve().as_uri(), [])
        browser.close()
        return report
