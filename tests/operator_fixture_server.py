"""Local browser fixtures, independent of robot API, BUS, SDK and systemd.

Run explicitly with Python stdlib; localhost only. All POSTs are recorded and
change in-memory fixtures. No action is forwarded to any production process.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
MODE = "disarmed"
GENERATION = "offline-fixture-1"
SEQ = -1
OWNER = None
ACK = None
ACTIONS = []
REQUESTED = set()
OPTIONS = {}


def safety():
    now = time.time()
    state = {"disarmed": "DISARMED", "armed": "ARMED", "estop": "ESTOP"}.get(MODE, "UNKNOWN")
    enabled = MODE == "armed"
    return {
        "contract_version": 0 if MODE == "legacy" else 1,
        "state": state,
        "generation": GENERATION,
        "owner": OWNER,
        "ready": MODE in {"disarmed", "armed", "estop"},
        "can_move": enabled,
        "read_only": not enabled,
        "hardware_ready": True,
        "observed_at": now - 30 if MODE == "stale" else now,
        "last_seq": SEQ,
        "lease_remaining_s": 10 if enabled else 0,
        "last_ack": ACK,
        "capabilities": {
            action: {
                "available": action in {"move", "turn"},
                "stop_verified": action in {"move", "turn"},
                "verification": "sdk_source" if action in {"move", "turn"} else "manual_characterization_required",
                "physical_completion": "unverified",
            }
            for action in ("move", "turn", "balance", "height", "action")
        },
    }


def catalog():
    tasks = [
        ("s1_manual", "Sterowanie ręczne", "manual", None),
        ("s2_camera_preview", "Podgląd kamery", None, None),
        ("s3_follow_me_face", "Follow Me", "follow_me", None),
        ("s8_mapping", "Mapa pasywna", None, None),
        ("s9_navigation", "Nawigacja", "navigation", None),
        ("s5_voice", "Głos", None, "voice"),
        ("s10_ai_providers", "Domena AI", None, "provider"),
    ]
    features = []
    for name, title, owner, kind in tasks:
        features.append(
            {
                "name": name,
                "title": title,
                "description": "Dane izolowanego scenariusza. Brak urządzenia.",
                "scenario": "S8" if name == "s8_mapping" else name.split("_")[0].upper(),
                "installed": True,
                "state": "ready" if name in REQUESTED else "stopped",
                "requested": name in REQUESTED,
                "ready": name in REQUESTED,
                "can_move": owner is not None,
                "motion_owner": owner,
                "source": "offline_fixture",
                "observed_at": time.time(),
                "resources": ["camera"] if "camera" in name else [],
                "services": [],
                "option_kind": kind,
                "options": OPTIONS.get(name, {}),
                "option_schema": None
                if kind is None
                else {
                    "field": "domain",
                    "default": "tts" if kind == "voice" else "text",
                    "choices": [
                        {"value": value, "label": value}
                        for value in (["voice", "asr", "tts"] if kind == "voice" else ["text", "vision", "google"])
                    ],
                },
            }
        )
    return {
        "contract_version": 1 if MODE == "legacy" else 2,
        "catalog_version": 2,
        "observed_at": time.time(),
        "features": features,
        "units": [],
        "resource_consumers": {},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global MODE, OWNER
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/_fixture/actions":
            return self.json(ACTIONS)
        if route == "/_fixture/mode":
            MODE = parse_qs(parsed.query).get("mode", ["disarmed"])[0]
            OWNER = "manual" if MODE == "armed" else None
            return self.json(safety())
        if route in {"/api/control/state", "/api/safety"}:
            return self.json({"ok": True, "safety": safety(), "server_time": time.time()})
        if route == "/api/logic/catalog":
            return self.json(catalog())
        if route in {"/api/version", "/api/status/version"}:
            return self.json({"available": True, "branch": "offline-fixture", "commit": "0123456", "dirty": False})
        if route == "/healthz":
            return self.json({"ok": True, "status": "ok"})
        if route == "/state":
            return self.json(
                {
                    "devices": {
                        "xgo": {"observed_at": time.time(), "battery_pct": 0, "roll": 0, "pitch": None, "yaw": 0}
                    },
                    "camera": {"vision_enabled": False},
                }
            )
        if route == "/vision/snap-info":
            return self.json({kind: {"exists": False, "mtime": None} for kind in ["raw", "proc", "ssd", "tracker"]})
        if route == "/svc":
            return self.json(
                {
                    "contract_version": 2,
                    "observed_at": time.time(),
                    "services": [
                        {
                            "unit": "fixture-reader.service",
                            "label": "Odczyt izolowany",
                            "source": "fixture",
                            "observed_at": time.time(),
                            "active": "inactive",
                            "load": "loaded",
                            "enabled": "disabled",
                            "lifecycle": "on_demand",
                            "can_move": False,
                            "consumers": [],
                            "dependencies": ["fixture-broker.service"],
                        }
                    ],
                }
            )
        if route.startswith("/api/resource/"):
            return self.json(
                {
                    "state": "busy" if route.endswith("uart") else "free",
                    "source": "fixture",
                    "observed_at": time.time(),
                    "holders": [],
                    "consumers": [],
                }
            )
        if route == "/api/services/graph":
            return self.json(
                {
                    "nodes": [],
                    "network": {
                        "wifi": {"status": "connected", "addresses": ["fixture-only"], "interface": "fixture0"}
                    },
                }
            )
        if route == "/sysinfo":
            return self.json({"source": "fixture", "cpu_pct": 0, "mem": {"pct": 0}})
        if route == "/api/navigator/status":
            return self.json({"observed_at": time.time(), "state": "STOPPED", "quality": "fixture"})
        if route.startswith("/api/services/") and route.endswith("/logs"):
            return self.json(
                {
                    "ok": True,
                    "source": "offline_fixture",
                    "observed_at": time.time(),
                    "lines": ["Fixture journal; no process was queried."],
                }
            )
        if route == "/api/voice/providers":
            return self.json({"providers": []})
        if route == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": fixture stream\n\n")
            return
        aliases = {
            "/": "view",
            "/view": "view",
            "/control": "control",
            "/devices": "devices",
            "/system": "system",
            "/navigation": "navigation",
            "/chat": "chat",
        }
        relative = f"web/{aliases[route]}.html" if route in aliases else route.lstrip("/")
        filename = (ROOT / relative).resolve()
        if not filename.is_relative_to(ROOT / "web") or not filename.is_file():
            return self.json({"error": "fixture_route_unknown"}, 404)
        body = filename.read_bytes()
        content_type = (
            "text/css"
            if filename.suffix == ".css"
            else "text/javascript"
            if filename.suffix == ".js"
            else "text/html"
            if filename.suffix == ".html"
            else "image/svg+xml"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global MODE, SEQ, OWNER, ACK, GENERATION
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        ACTIONS.append({"path": self.path, "body": body})
        action = body.get("action")
        if self.path in {"/api/control", "/api/safety"}:
            if action == "arm":
                MODE, OWNER = "armed", body.get("owner")
            elif action in {"stop", "disarm", "clear_estop", "estop"}:
                MODE, OWNER = ("estop" if action == "estop" else "disarmed"), None
                GENERATION += "x"
            SEQ = body.get("seq", -1)
            ACK = {
                **body,
                "status": "executed",
                "accepted": True,
                "observed_at": time.time(),
                "physical_completion": "unverified",
            }
            return self.json(
                {"ok": True, "confirmed": True, "ack": ACK, "safety": safety(), "physical_completion": "unverified"}
            )
        if self.path.startswith("/api/logic/feature/"):
            name = self.path.rsplit("/", 1)[-1]
            REQUESTED.add(name) if body.get("enabled") else REQUESTED.discard(name)
            OPTIONS[name] = body.get("options", {}) if body.get("enabled") else {}
            row = next((item for item in catalog()["features"] if item["name"] == name), None)
            return self.json({"ok": True, "result": {"task": row}})
        if self.path == "/api/chat/send":
            return self.json({"reply": "Izolowana odpowiedź. Żadne urządzenie nie jest podłączone."})
        return self.json({"pending": True, "confirmed": False}, 202)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
