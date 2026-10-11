"""Offline UART timeline and read correlation. No device access."""

from collections import Counter

from drivers.xgo.sniffer_semantics import meaning


def analyze(events, *, firmware=None, response_timeout_ms=100, source="serial_calls"):
    if source not in {"serial_calls", "wire_export", "controller_bus_export"}:
        raise ValueError("unsupported_capture_source")
    if not 1 <= response_timeout_ms <= 5000:
        raise ValueError("response_timeout_ms_must_be_1_to_5000")
    pending, timeline, transactions, changes = [], [], [], []
    counts, faults, last_commands = Counter(), Counter(), {}
    write_times, sensors, states = {}, {}, []
    first = last = None
    inferred = firmware
    loss = False
    gaps = 0

    def finish(request, outcome, response=None, ambiguous=False):
        item = {
            "request_index": request["index"],
            "address": request["address"],
            "register": request["semantic"]["register"],
            "outcome": outcome,
            "requested_bytes": request["semantic"]["requested_bytes"],
        }
        if response is not None:
            start, end = request.get("time_ns"), response.get("time_ns")
            item.update(
                response_index=response["index"],
                latency_ms=(end - start) / 1e6 if start is not None and end is not None else None,
                latency_scope="host_serial_observation",
                pairing="ambiguous_same_address_length" if ambiguous else "inferred_address_length_no_transaction_id",
                value=response["semantic"].get("value"),
            )
        transactions.append(item)

    for event in events:
        event = dict(event)
        now = event.get("time_ns")
        if now is not None:
            first = now if first is None else first
            last = now
            alive = []
            for request in pending:
                at = request.get("time_ns")
                if at is not None and now - at > response_timeout_ms * 1e6:
                    finish(request, "no_response_within_observation_window")
                else:
                    alive.append(request)
            pending = alive
        if event.get("direction") == "gap" or event.get("event") == "gap":
            gaps += 1
            for request in pending:
                finish(request, "observation_gap")
            pending.clear()
        if event.get("event") in {"start", "end"}:
            for request in pending:
                finish(request, "capture_boundary_before_response")
            pending.clear()
            last_commands.clear()
        if event.get("dropped", 0) or event.get("truncated") or event.get("cause") == "capture_truncated":
            loss = True
        if event.get("event") != "frame":
            if event.get("event") not in {"start", "end"} and event.get("direction") != "gap":
                faults[event.get("event") or event.get("direction") or "unknown"] += 1
            timeline.append(event)
            continue
        if now is not None and first is not None:
            event["elapsed_ms"] = (now - first) / 1e6
        semantic = meaning(event, inferred)
        if semantic["register"] == "FIRMWARE_VERSION" and semantic.get("value"):
            inferred = semantic["value"]
        event.update(index=len(timeline), semantic=semantic)
        counts[f'{event["direction"]}:{semantic["register"]}'] += 1
        if semantic["kind"] == "read_request" and semantic["valid"]:
            if len(pending) >= 1024:
                finish(pending.pop(0), "correlation_capacity_limit")
            pending.append(event)
        elif semantic["kind"] == "read_response":
            value = semantic.get("value")
            if isinstance(value, dict):
                for name, number in value.items():
                    sensors.setdefault(name, []).append(number)
            elif type(value) in (int, float):
                sensors.setdefault(semantic["register"], []).append(value)
            if semantic["register"] == "WORK_STATUS" and value is not None:
                if not states or states[-1]["value"] != value:
                    states.append({"time_ns": now, "value": value, "label": semantic.get("label")})
            candidates = [
                r
                for r in pending
                if r["address"] == event["address"]
                and r["semantic"]["requested_bytes"] == len(bytes.fromhex(event["payload_hex"]))
            ]
            found = candidates[0] if candidates else None
            if found is None:
                event["correlation"] = "unmatched_response"
                faults["unmatched_response"] += 1
            else:
                finish(
                    found,
                    "response_observed_pairing_ambiguous" if len(candidates) > 1 else "response_observed",
                    event,
                    ambiguous=len(candidates) > 1,
                )
                pending.remove(found)
                event["request_index"] = found["index"]
        elif semantic["kind"] == "write_command":
            key = event["address"]
            if now is not None:
                write_times.setdefault(semantic["register"], []).append(now)
            if last_commands.get(key) != event["payload_hex"]:
                changes.append({"time_ns": now, "index": event["index"], "address": key, "semantic": semantic})
            last_commands[key] = event["payload_hex"]
        if semantic.get("decode_error"):
            faults["decode_error"] += 1
        timeline.append(event)
    for request in pending:
        finish(request, "capture_ended_before_response")
    latencies = [t["latency_ms"] for t in transactions if t.get("latency_ms") is not None]
    outcomes = Counter(t["outcome"] for t in transactions)
    intervals = {}
    for name, times in write_times.items():
        values = sorted((b - a) / 1e6 for a, b in zip(times, times[1:]) if b >= a)
        if values:
            intervals[name] = {
                "min_ms": values[0],
                "max_ms": values[-1],
                "median_ms": values[len(values) // 2],
                "scope": "host_serial_observation",
            }

    return {
        "contract_id": "rider.uart.analysis",
        "contract_version": 1,
        "scope": "observed_serial_calls_not_controller_internal_bus" if source == "serial_calls" else source,
        "source": source,
        "source_declared_by_operator": source != "serial_calls",
        "firmware": inferred,
        "firmware_override": firmware,
        "duration_s": (last - first) / 1e9 if first is not None and last is not None else None,
        "frame_counts": dict(counts),
        "fault_counts": dict(faults),
        "capture_loss_observed": loss,
        "continuity_gaps": gaps,
        "transaction_outcomes": dict(outcomes),
        "latency_ms": {"min": min(latencies), "max": max(latencies)} if latencies else None,
        "write_intervals": intervals,
        "sensor_ranges": {name: {"min": min(v), "max": max(v), "samples": len(v)} for name, v in sensors.items()},
        "work_status_changes": states,
        "write_acknowledgement": "not_confirmed",
        "physical_completion": "unverified",
        "transactions": transactions,
        "command_changes": changes,
        "timeline": timeline,
    }


def markdown(report):
    lines = [
        "# UART capture report",
        "",
        f'Firmware: {report["firmware"] or "unknown"}',
        f'Scope: {report["scope"]}',
        "",
        "Writes are observed commands, not proof of physical execution.",
        "Setpoints decoded using SDK mappings are not measured positions.",
        "Internal motor traffic is not visible through the Pi/controller UART.",
        "",
        "## Read transactions",
        "",
        "| Outcome | Count |",
        "| --- | ---: |",
    ]
    lines += [f"| {name} | {count} |" for name, count in report["transaction_outcomes"].items()]
    lines += ["", "## Observed frames", "", "| Direction / register | Count |", "| --- | ---: |"]
    lines += [f"| {name} | {count} |" for name, count in report["frame_counts"].items()]
    lines += [
        "",
        f'Capture loss observed: {report["capture_loss_observed"]}',
        f'Continuity gaps (including owner flushes): {report["continuity_gaps"]}',
        f'Faults: {report["fault_counts"]}',
        "",
        "## Command changes",
        "",
        "| Host monotonic ns | Register | Raw value | Meaning |",
        "| --- | --- | --- | --- |",
    ]
    for change in report["command_changes"]:
        s = change["semantic"]
        label = s.get("documented_name", s.get("sdk_setpoint", s.get("enabled", s.get("signed_byte_offset", ""))))
        lines.append(f'| {change["time_ns"]} | {s["register"]} | {s.get("value")} | {label} |')
    return "\n".join(lines) + "\n"
