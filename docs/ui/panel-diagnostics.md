# Pi diagnostics and version footer

The Pi dashboard is served by Flask on port 8080. `/` and `/view` are the overview;
`/control` is Robot control; `/system/` is Diagnostics. Service administration remains
in the advanced section of Robot control. `/home` is the Google Feed screen, not the
landing page. `/home` and `/google_home` remain accessible directly but are omitted
from the current menu. Both Polish and English labels are supported.

Diagnostics displays service cards grouped by component and a collapsible details
table. Status counts distinguish inactive services from failures. Component connections
come from `SERVICE_META`; they do not represent systemd boot dependencies.
The page reads `GET /api/services/graph` every five seconds with one request in flight
and a twelve-second timeout. An error preserves the last successful data and marks
its timestamp as stale. This page sends no control or service commands.

The shared footer reads `GET /api/status/version` once after loading. Its response
contains `available`, `branch`, `commit`, `dirty`, `message`, and `ts`. Metadata comes
from the repository containing the running code, using read-only Git commands with
one-second command timeouts and a sixty-second cache. Missing metadata returns 200
with `available=false`; detached HEAD is identified explicitly. Commit copying also
works over LAN HTTP through the legacy clipboard fallback. On small screens the footer
wraps and follows normal document flow.

Verification includes API contracts and browser checks for four themes, four screen
widths, both languages, slow/failed API responses, and version display on every page.
See the [dated implementation and Pi/PC route audit](../../docs_pl/ui/panel-diagnostyka-20261010.md)
for results, screenshots, existing baseline test failures, and missing PC routes.
The changes have not been deployed to the robot.

```bash
PYTHONPATH=. RIDER_PI_CI=1 RIDER_PI_MOCK_HW=1 pytest -q tests/test_version_api.py tests/test_panel_route_contract.py tests/test_web_routes.py tests/test_services_dashboard_api.py
```

`tests/test_dashboard_browser.py` optionally uses an existing Playwright environment.
Set `RIDER_TEST_BROWSER` to an installed Chromium executable if necessary. No browser
dependency or new CI job is required by this change.
