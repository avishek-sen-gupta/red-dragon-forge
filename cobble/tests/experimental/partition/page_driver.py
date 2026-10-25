"""Drives a rendered partition page in headless Chromium: load it, list datasets, follow one, search one."""

from __future__ import annotations

from pathlib import Path

from tests.experimental.partition.page_report import PageReport
from playwright.sync_api import Page, sync_playwright

WEBGL = ("--use-angle=swiftshader", "--enable-unsafe-swiftshader")
DATASET_EDGES = "graph.filterEdges((e, d) => d.dataset)"
VISIBLE = f"{DATASET_EDGES}.filter(e => !renderer.getEdgeDisplayData(e).hidden).length"
LAYOUT = "[...document.querySelectorAll('#layout tr')].map(r => [...r.children].map(c => c.innerText))"
OTHERS = "graph.filterNodes(id => !chain.has(id)).map(id => renderer.getNodeDisplayData(id)).filter(d => !d.hidden)"
OTHER_EDGES = "graph.filterEdges((e, d, s, t) => !(chain.has(s) && chain.has(t))).filter(e => !renderer.getEdgeDisplayData(e).hidden).length"
PLAIN_FIELD = "graph.filterNodes((id, d) => d.kind === 'field' && d.component >= 0 && !graph.neighbors(id).some(isSlot))[0]"
ISOLATED_FIELD = (
    "graph.filterNodes((id, d) => d.kind === 'field' && d.component < 0)[0]"
)
CHAIN_DATASETS = "[...new Set([...chain].filter(isSlot).map(i => graph.getNodeAttribute(i, 'record')))].sort()"


def _headline(page: Page) -> str:
    return page.locator("#detail").inner_text().split("\n")[0]


def _drive(page: Page, url: str, errors: list[str]) -> PageReport:
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.wait_for_function("typeof renderer !== 'undefined'")
    total = page.evaluate(f"{DATASET_EDGES}.length")
    before = page.evaluate(VISIBLE)
    page.locator("input[name=group][value=dataset]").check()
    rows = tuple(page.locator("#list .c").all_inner_texts())
    page.locator("#list .c").first.click()
    followed, chained, after = (
        _headline(page),
        page.evaluate(CHAIN_DATASETS),
        page.evaluate(VISIBLE),
    )
    layout = tuple(tuple(row) for row in page.evaluate(LAYOUT))
    others = page.evaluate(f"{OTHERS}.length")
    colours = tuple(sorted(set(page.evaluate(f"{OTHERS}.map(d => d.color)"))))
    other_edges = page.evaluate(OTHER_EDGES)
    page.evaluate(f"renderer.emit('clickNode', {{ node: {PLAIN_FIELD} }})")
    field_click = (page.evaluate("grouping"), _headline(page))
    page.evaluate(f"renderer.emit('clickNode', {{ node: {ISOLATED_FIELD} }})")
    isolated_click = (page.evaluate("grouping"), _headline(page))
    page.evaluate("select(null)")
    page.locator("#search").fill(followed)
    page.locator("#search").press("Enter")
    return PageReport(
        errors=tuple(errors),
        dataset_edges=total,
        visible_before=before,
        rows=rows,
        followed=followed,
        chain_datasets=tuple(chained),
        visible_after=after,
        layout=layout,
        others_shown=others,
        other_colours=colours,
        other_edges_shown=other_edges,
        field_click=field_click,
        isolated_click=isolated_click,
        searched=_headline(page),
    )


def drive(path: Path) -> PageReport:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=list(WEBGL))
        report = _drive(browser.new_page(), path.resolve().as_uri(), [])
        browser.close()
        return report
