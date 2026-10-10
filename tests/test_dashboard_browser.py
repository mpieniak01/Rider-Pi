"""Optional browser regression checks; use an installed Playwright environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[1]
VERSION = {"available": True, "branch": "main", "commit": "461fc4e", "dirty": True, "message": "test version"}
GRAPH = {
    "nodes": [
        {
            "id": "api",
            "unit": "rider-api.service",
            "label": "HTTP API",
            "group": "core",
            "status": "active",
            "edges_out": ["motion"],
        },
        {
            "id": "motion",
            "unit": "rider-" + "long-name-" * 12 + ".service",
            "label": "Motion",
            "group": "motion",
            "status": "inactive",
            "since": "Saturday 2026-10-10 10:00:00 CEST",
        },
        {"id": "failed", "unit": "test.service", "label": "Failed service", "group": "core", "status": "failed"},
        {
            "id": "unknown",
            "unit": "unknown.service",
            "label": "Unknown service",
            "group": "core",
            "status": "activating",
        },
    ]
}


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as driver:
        options = {"headless": True}
        executable = os.getenv("RIDER_TEST_BROWSER")
        if executable:
            options["executable_path"] = executable
        instance = driver.chromium.launch(**options)
        yield instance
        instance.close()


@pytest.fixture()
def panel(browser):
    context = browser.new_context(viewport={"width": 1365, "height": 900}, locale="pl-PL")
    state = {
        "graph": GRAPH,
        "version": VERSION,
        "graph_status": 200,
        "version_status": 200,
        "template_status": 200,
        "writes": [],
        "graph_requests": 0,
        "held_graph": [],
        "hold_graph": False,
        "held_version": [],
        "hold_version": False,
    }

    def route_handler(route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method not in {"GET", "HEAD"}:
            state["writes"].append((request.method, path))
            route.fulfill(status=409, content_type="application/json", body='{"error":"read_only_test"}')
        elif path == "/api/services/graph":
            state["graph_requests"] += 1
            if state["hold_graph"]:
                state["held_graph"].append(route)
                return
            route.fulfill(
                status=state["graph_status"], content_type="application/json", body=json.dumps(state["graph"])
            )
        elif path == "/api/status/version":
            if state["hold_version"]:
                state["held_version"].append(route)
                return
            route.fulfill(
                status=state["version_status"], content_type="application/json", body=json.dumps(state["version"])
            )
        elif path == "/web/dashboard_footer_template.html" and state["template_status"] != 200:
            route.fulfill(status=state["template_status"], body="unavailable")
        else:
            file = ROOT / (
                path.lstrip("/") if path.startswith("/web/") else "web/" + (path.strip("/") or "view") + ".html"
            )
            if file.is_file() and file.is_relative_to(ROOT):
                route.fulfill(path=str(file))
            else:
                route.fulfill(content_type="application/json", body="{}")

    context.route("**/*", route_handler)
    page = context.new_page()
    yield page, state
    context.close()


@pytest.mark.parametrize("width", [320, 390, 768, 1365])
@pytest.mark.parametrize("theme", ["classic", "classic-plus", "v2", "v3"])
def test_diagnostics_layout_and_scrolling(panel, width, theme):
    page, state = panel
    page.set_viewport_size({"width": width, "height": 900})
    page.add_init_script(f"localStorage.setItem('dashboard_theme', {json.dumps(theme)})")
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector(".service-node")
    assert page.locator(".service-node").count() == 4
    assert page.locator("#system-summary > *").all_text_contents() == [
        "Aktywne: 1",
        "Nieaktywne: 1",
        "Błędy: 1",
        "Nieznane: 1",
    ]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    columns = page.locator(".services-grid").first.evaluate(
        "e => getComputedStyle(e).gridTemplateColumns.split(' ').length"
    )
    assert columns >= 2 if width >= 768 else columns == 1
    page.locator("details summary").click()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width < 768:
        assert page.locator(".system-table-scroll").evaluate("e => e.scrollWidth > e.clientWidth")
    assert state["writes"] == []


def test_language_menu_and_details_survive_refresh(panel):
    page, state = panel
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector(".service-node")
    page.locator("details summary").click()
    page.wait_for_selector(".dashboard-menu")
    page.locator("button[data-lang=en]").click()
    assert page.locator("h1").inner_text().endswith("Diagnostics")
    assert "Robot control" in page.locator(".dashboard-menu").inner_text()
    assert page.locator(".dashboard-menu a[href='/home']").count() == 0
    assert page.locator(".dashboard-menu a[href='/google_home']").count() == 0
    page.wait_for_timeout(5200)
    assert page.locator("details").evaluate("e => e.open")
    assert page.locator(".service-node").count() == 4
    assert state["writes"] == []


def test_api_failure_keeps_last_data_and_recovers(panel):
    page, state = panel
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector(".service-node")
    state["graph_status"] = 500
    page.wait_for_selector("#status-line.is-stale", timeout=8000)
    assert page.locator(".service-node").count() == 4
    assert "Ostatnia aktualizacja" in page.locator("#status-line").inner_text()
    state["graph_status"] = 200
    page.wait_for_function("!document.querySelector('#status-line').classList.contains('is-stale')", timeout=8000)
    assert page.locator(".service-node").count() == 4


def test_empty_graph_and_unknown_version(panel):
    page, state = panel
    state["graph"] = {"nodes": []}
    state["version"] = {"available": False}
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector(".no-services")
    page.wait_for_selector("[data-footer-commit]:disabled")
    assert "Brak danych usług" in page.locator(".no-services").inner_text()
    assert "Wersja niedostępna" in page.locator("[data-footer-version-block]").inner_text()


def test_footer_fallback_and_http_copy(panel):
    page, state = panel
    state["template_status"] = 404
    page.add_init_script("document.execCommand = action => { window.lastCopy = action; return true; }")
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector("[data-footer-commit]:not(:disabled)")
    assert "main" in page.locator("[data-footer-version-block]").inner_text()
    assert "lokalne zmiany" in page.locator("[data-footer-version-block]").inner_text()
    page.locator("[data-footer-commit]").click()
    assert page.evaluate("window.lastCopy") == "copy"
    assert page.locator("[data-footer-commit]").inner_text() == "Skopiowano"


@pytest.mark.parametrize("status", [404, 500])
def test_version_failure_does_not_break_diagnostics(panel, status):
    page, state = panel
    state["version_status"] = status
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector(".service-node")
    page.wait_for_selector("[data-footer-commit]:disabled")
    assert "Wersja niedostępna" in page.locator("[data-footer-version-block]").inner_text()


def test_slow_graph_has_one_request_in_flight(panel):
    page, state = panel
    state["hold_graph"] = True
    page.goto("http://rider-pi.test/system/")
    page.wait_for_timeout(5500)
    assert state["graph_requests"] == 1
    assert "Ładowanie" in page.locator("#status-line").inner_text()
    state["held_graph"].pop().fulfill(content_type="application/json", body=json.dumps(GRAPH))
    state["hold_graph"] = False
    page.wait_for_selector(".service-node")
    assert page.locator(".service-node").count() == 4


def test_first_graph_error_recovers(panel):
    page, state = panel
    state["graph"] = {"nodes": None}
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector("#status-line.is-stale")
    assert page.locator(".service-node").count() == 0
    state["graph"] = GRAPH
    page.wait_for_selector(".service-node", timeout=8000)
    assert page.locator(".service-node").count() == 4


@pytest.mark.parametrize(
    "path", ["/", "/view", "/control", "/navigation", "/system/", "/home", "/google_home", "/chat"]
)
def test_shared_version_footer_on_every_page(panel, path):
    page, state = panel
    page.set_viewport_size({"width": 320, "height": 900})
    state["version"] = {**VERSION, "branch": "codex/" + "long-branch-name-" * 8}
    page.goto("http://rider-pi.test" + path)
    commit = page.locator("[data-footer-commit]:not(:disabled)")
    commit.wait_for()
    assert commit.inner_text() == "#461fc4e"
    footer = page.locator("[data-dashboard-footer-target]")
    assert footer.evaluate("e => getComputedStyle(e).position") == "static"
    block = page.locator("[data-footer-version-block]")
    assert block.evaluate("e => e.getBoundingClientRect().right <= innerWidth")
    assert block.evaluate("e => e.scrollWidth <= e.clientWidth")
    assert state["writes"] == []


def test_version_timeout_is_nonfatal(panel):
    page, state = panel
    state["hold_version"] = True
    page.goto("http://rider-pi.test/system/")
    page.wait_for_selector(".service-node")
    page.wait_for_timeout(5500)
    assert page.locator("[data-footer-commit]").is_disabled()
    assert "Wersja niedostępna" in page.locator("[data-footer-version-block]").inner_text()
    assert page.locator(".service-node").count() == 4
