# Pi diagnostics and version footer

Current operator views are described in [Operator panel](operator-panel.md).
System is read only by default; administration and autostart changes are explicit.
Service consumers and actual dependencies come from the version 2 catalog.
This page retains the network and version API details.

The **Network** section reports the actual `wlan0` state independently of service
statuses: carrier and an IPv4 address indicate a LAN connection. It reads radio blocks,
addresses, the default route and `dhcpcd` autostart. Missing tools or data mean unknown
state, rather than a disconnected link. This is not an Internet reachability check.
The `network.wifi` field in `/api/services/graph` uses sysfs and read-only `ip`/systemd
commands with one-second timeouts. It exposes no SSID, password or network config contents.

`wifi-unblock.service` only unblocks the radio before network configuration; its
success does not prove Wi-Fi connectivity. On the manufacturer image, `dhcpcd` and
its wpa_supplicant hook own `wlan0`. Do not start another `wpa_supplicant@wlan0`
instance or a competing interface manager. Inactive ConnMan does not need
`connman-wait-online`. Configure Wi-Fi locally on the device without publishing
password-bearing files. Radio unblocking and state persistence are documented in
[rfkill](https://manpages.debian.org/bullseye/rfkill/rfkill.8.en.html) and
[systemd-rfkill](https://manpages.debian.org/bullseye/systemd/systemd-rfkill.service.8.en.html).

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

## Historical screenshots

The images below show the previous diagnostic layout.

![Desktop diagnostics](../assets/ui/diagnostics-desktop.png)
![Mobile diagnostics](../assets/ui/diagnostics-mobile.png)
![Mobile version footer](../assets/ui/version-footer-mobile.png)
