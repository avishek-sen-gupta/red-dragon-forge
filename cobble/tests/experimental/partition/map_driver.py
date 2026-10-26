"""Drives the program map in headless Chromium: load it, read what it drew, search a program, click it."""

from __future__ import annotations

from pathlib import Path

from tests.experimental.partition.map_report import MapReport
from tests.experimental.partition.page_driver import WEBGL
from playwright.sync_api import Page, sync_playwright

PLACES = "[[graph.getNodeAttribute('S', 'x'), graph.getNodeAttribute('S', 'y')], [renderer.getCamera().x, renderer.getCamera().y]]"
ON_SCREEN = "(({ x, y }, box) => ({ x: x + box.left, y: y + box.top }))(renderer.graphToViewport(graph.getNodeAttributes('S')), renderer.getContainer().getBoundingClientRect())"
HREFS = "graph.filterNodes((id, d) => d.href).map(id => graph.getNodeAttribute(id, 'href')).sort()"


def _drive(page: Page, url: str, errors: list[str]) -> MapReport:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.wait_for_function("typeof renderer !== 'undefined'")
    counts = page.evaluate("[graph.order, graph.size]")
    hrefs = tuple(page.evaluate(HREFS))
    before = page.evaluate(PLACES)
    start = page.evaluate(ON_SCREEN)
    page.mouse.move(start["x"], start["y"])
    page.mouse.down()
    page.mouse.move(start["x"] + 40, start["y"] + 30, steps=5)
    page.mouse.up()
    after = page.evaluate(PLACES)
    dragged = (after[0] != before[0], after[1] != before[1])
    stayed = page.url.endswith("index.html")
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
        dragged=dragged,
        stayed=stayed,
        clicked=page.url.rsplit("/", 2)[1] + "/" + page.url.rsplit("/", 1)[1],
    )


def drive_map(path: Path) -> MapReport:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=list(WEBGL))
        report = _drive(browser.new_page(), path.resolve().as_uri(), [])
        browser.close()
        return report
