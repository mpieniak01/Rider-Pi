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

When verifying changes, cover API contracts, four themes, multiple screen
widths, both languages, slow/failed responses and the footer on every page.
Store individual audit results locally.

![Desktop diagnostics](../assets/ui/diagnostics-desktop.png)
![Mobile diagnostics](../assets/ui/diagnostics-mobile.png)
![Mobile version footer](../assets/ui/version-footer-mobile.png)
