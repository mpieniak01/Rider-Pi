"""Service administration shares the task manager lock and accepted intents."""

from __future__ import annotations

from common.service_catalog import CAMERA_CAPTURE_UNITS, UNIT_CATALOG


class FeatureAdminMixin:
    def service_action(self, unit: str, action: str, control: dict | None = None) -> dict:
        """Administration shares task serialization and cannot steal a lease."""
        with self.transaction():
            meta = UNIT_CATALOG[unit]
            previous_domain = self._service_domains.get(unit)
            consumers = [name for name in self._consumers().get(unit, []) if not name.startswith("admin:")]
            if consumers and action in {"stop", "restart", "disable"}:
                return {"ok": False, "error": "resource_in_use", "consumers": consumers, "http_status": 409}
            if action == "enable" and meta["lifecycle"] != "startup":
                return {"ok": False, "error": "on_demand_autostart_forbidden", "http_status": 409}
            if action in {"start", "restart"}:
                domain = (control or {}).get("domain", "voice")
                if unit == "rider-voice-web.service" and domain not in {"voice", "text", "asr", "tts"}:
                    return {"ok": False, "error": "invalid_voice_domain", "http_status": 400}
                if unit == "rider-voice-web.service" and previous_domain and previous_domain != domain:
                    return {"ok": False, "error": "stop_before_reconfigure", "http_status": 409}
                missing = self.dependency_check((unit,), {"domain": domain})
                if missing:
                    return {
                        "ok": False,
                        "error": "runtime_dependencies_missing",
                        "missing": missing,
                        "http_status": 503,
                    }
                if unit == "rider-voice-web.service":
                    self._service_domains[unit] = domain
                    if not self._persist_state():
                        if previous_domain:
                            self._service_domains[unit] = previous_domain
                        else:
                            self._service_domains.pop(unit, None)
                        return {"ok": False, "error": "profile_journal_unavailable", "http_status": 503}
            if meta["can_move"] and action in {"start", "restart"}:
                safety = self.safety_status()
                owner = meta["motion_owner"]
                if (
                    action == "restart"
                    or safety.get("ready") is not True
                    or safety.get("can_move") is not True
                    or safety.get("owner") != owner
                ):
                    return {
                        "ok": False,
                        "error": "operator_motion_permission_required",
                        "safety": safety,
                        "http_status": 409,
                    }
                required = ("action",) if unit == "rider-choreographer.service" else ("move", "turn")
                capabilities = safety.get("capabilities", {})
                if not isinstance(capabilities, dict) or any(
                    not isinstance(capabilities.get(name), dict)
                    or capabilities[name].get("available") is not True
                    or capabilities[name].get("stop_verified") is not True
                    for name in required
                ):
                    return {
                        "ok": False,
                        "error": "actuator_capability_unavailable",
                        "safety": safety,
                        "http_status": 409,
                    }
                denied = self._intent_permission(control)
                if denied:
                    return {**denied, "http_status": 409}
                if self._running(unit):
                    return {"ok": False, "error": "stop_before_reconfigure", "http_status": 409}
                self._admin_intents[unit] = dict(control)
                if not self._persist_state():
                    self._admin_intents.pop(unit, None)
                    return {"ok": False, "error": "control_journal_unavailable", "http_status": 503}
            if meta["can_move"] and action == "stop":
                stop = self.safety_stop(None)
                if not stop.get("ok") or not stop.get("confirmed"):
                    return {"ok": False, "error": "stop_unconfirmed", "safety": stop, "http_status": 409}
            capture = {unit} & CAMERA_CAPTURE_UNITS
            conflicts = [
                candidate for candidate in CAMERA_CAPTURE_UNITS - capture if capture and self._running(candidate)
            ]
            if action in {"start", "restart"} and conflicts:
                return {"ok": False, "error": "resource_conflict", "consumers": conflicts, "http_status": 409}
            result = self._run(unit, action)
            if not result.get("ok") and unit == "rider-voice-web.service":
                if previous_domain:
                    self._service_domains[unit] = previous_domain
                else:
                    self._service_domains.pop(unit, None)
            if meta["can_move"] and action == "start":
                failed = not result.get("ok") or not self._running(unit)
                safety = self.safety_status()
                capabilities = safety.get("capabilities", {})
                characterized = isinstance(capabilities, dict) and all(
                    isinstance(capabilities.get(name), dict)
                    and capabilities[name].get("available") is True
                    and capabilities[name].get("stop_verified") is True
                    for name in required
                )
                changed = (
                    safety.get("generation") != control.get("generation")
                    or safety.get("owner") != meta["motion_owner"]
                    or safety.get("can_move") is not True
                    or safety.get("ready") is not True
                    or not characterized
                )
                if failed and not self._running(unit):
                    self._admin_intents.pop(unit, None)
                    self._persist_state()
                    return {"ok": False, "error": "start_failed", "results": [result], "http_status": 503}
                elif failed or changed:
                    revoked = self.safety_stop(meta["motion_owner"])
                    rollback = [revoked]
                    if revoked.get("ok") and revoked.get("confirmed"):
                        rollback.append(self._run(unit, "stop"))
                    if all(row.get("ok") for row in rollback) and not self._running(unit):
                        self._admin_intents.pop(unit, None)
                    else:
                        self._admin_units.add(unit)
                    self._persist_state()
                    return {
                        "ok": False,
                        "error": "start_failed" if failed else "operator_generation_changed",
                        "rollback": rollback,
                        "results": [result],
                        "http_status": 409,
                    }
            if result.get("ok"):
                if action == "start":
                    self._admin_units.add(unit)
                elif action == "stop":
                    self._admin_units.discard(unit)
                    self._admin_intents.pop(unit, None)
                    self._service_domains.pop(unit, None)
                    self._managed_units.discard(unit)
            self._persist_state()
            return {
                "ok": bool(result.get("ok")),
                "results": [result],
                "sequence": [(unit, action)],
                "status": self._status(unit),
            }
