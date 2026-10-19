"""Offline UART timeline and read correlation. No device access."""

from collections import Counter

from drivers.xgo.sniffer_semantics import meaning


class _Analysis:
    def __init__(self, firmware, response_timeout_ms, source):
        self.firmware = firmware
        self.response_timeout_ms = response_timeout_ms
        self.source = source
        self.pending, self.timeline, self.transactions, self.changes = ([], [], [], [])
        self.counts, self.faults, self.last_commands = (Counter(), Counter(), {})
        self.write_times, self.sensors, self.states = ({}, {}, [])
        self.first = self.last = None
        self.inferred = self.firmware
        self.loss = False
        self.gaps = 0

    def finish(self, request, outcome, response=None, ambiguous=False):
        item = {
            'request_index': request['index'],
            'address': request['address'],
            'register': request['semantic']['register'],
            'outcome': outcome,
            'requested_bytes': request['semantic']['requested_bytes'],
        }
        if response is not None:
            start, end = (request.get('time_ns'), response.get('time_ns'))
            item.update(
                response_index=response['index'],
                latency_ms=(end - start) / 1000000.0 if start is not None and end is not None else None,
                latency_scope='host_serial_observation',
                pairing='ambiguous_same_address_length' if ambiguous else 'inferred_address_length_no_transaction_id',
                value=response['semantic'].get('value'),
            )
        self.transactions.append(item)

    def _observe_time(self, now):
        if now is not None:
            self.first = now if self.first is None else self.first
            self.last = now
            alive = []
            for request in self.pending:
                at = request.get('time_ns')
                if at is not None and now - at > self.response_timeout_ms * 1000000.0:
                    self.finish(request, 'no_response_within_observation_window')
                else:
                    alive.append(request)
            self.pending = alive

    def _observe_boundary(self, event):
        if event.get('direction') == 'gap' or event.get('event') == 'gap':
            self.gaps += 1
            for request in self.pending:
                self.finish(request, 'observation_gap')
            self.pending.clear()
        if event.get('event') in {'start', 'end'}:
            for request in self.pending:
                self.finish(request, 'capture_boundary_before_response')
            self.pending.clear()
            self.last_commands.clear()
        if event.get('dropped', 0) or event.get('truncated') or event.get('cause') == 'capture_truncated':
            self.loss = True

    def add(self, raw_event):
        event = dict(raw_event)
        now = event.get('time_ns')
        self._observe_time(now)
        self._observe_boundary(event)
        if event.get('event') != 'frame':
            if event.get('event') not in {'start', 'end'} and event.get('direction') != 'gap':
                self.faults[event.get('event') or event.get('direction') or 'unknown'] += 1
            self.timeline.append(event)
            return
        if now is not None and self.first is not None:
            event['elapsed_ms'] = (now - self.first) / 1000000.0
        semantic = meaning(event, self.inferred)
        if semantic['register'] == 'FIRMWARE_VERSION' and semantic.get('value'):
            self.inferred = semantic['value']
        event.update(index=len(self.timeline), semantic=semantic)
        self.counts[f"{event['direction']}:{semantic['register']}"] += 1
        if semantic['kind'] == 'read_request' and semantic['valid']:
            self._read_request(event, semantic)
        elif semantic['kind'] == 'read_response':
            self._read_response(event, semantic)
        elif semantic['kind'] == 'write_command':
            self._write_command(event, semantic)
        if semantic.get('decode_error'):
            self.faults['decode_error'] += 1
        self.timeline.append(event)

    def _read_request(self, event, semantic):
        if len(self.pending) >= 1024:
            self.finish(self.pending.pop(0), 'correlation_capacity_limit')
        self.pending.append(event)

    def _record_sensor_value(self, event, semantic):
        now = event.get('time_ns')
        value = semantic.get('value')
        if isinstance(value, dict):
            for name, number in value.items():
                self.sensors.setdefault(name, []).append(number)
        elif type(value) in (int, float):
            self.sensors.setdefault(semantic['register'], []).append(value)
        if semantic['register'] == 'WORK_STATUS' and value is not None:
            if not self.states or self.states[-1]['value'] != value:
                self.states.append({'time_ns': now, 'value': value, 'label': semantic.get('label')})

    def _read_response(self, event, semantic):
        self._record_sensor_value(event, semantic)
        candidates = [
            r
            for r in self.pending
            if r['address'] == event['address']
            and r['semantic']['requested_bytes'] == len(bytes.fromhex(event['payload_hex']))
        ]
        found = candidates[0] if candidates else None
        if found is None:
            event['correlation'] = 'unmatched_response'
            self.faults['unmatched_response'] += 1
        else:
            self.finish(
                found,
                'response_observed_pairing_ambiguous' if len(candidates) > 1 else 'response_observed',
                event,
                ambiguous=len(candidates) > 1,
            )
            self.pending.remove(found)
            event['request_index'] = found['index']

    def _write_command(self, event, semantic):
        now = event.get('time_ns')
        key = event['address']
        if now is not None:
            self.write_times.setdefault(semantic['register'], []).append(now)
        if self.last_commands.get(key) != event['payload_hex']:
            self.changes.append({'time_ns': now, 'index': event['index'], 'address': key, 'semantic': semantic})
        self.last_commands[key] = event['payload_hex']

    def report(self):
        for request in self.pending:
            self.finish(request, 'capture_ended_before_response')
        latencies = [t['latency_ms'] for t in self.transactions if t.get('latency_ms') is not None]
        outcomes = Counter(t['outcome'] for t in self.transactions)
        intervals = {}
        for name, times in self.write_times.items():
            values = sorted(((b - a) / 1000000.0 for a, b in zip(times, times[1:]) if b >= a))
            if values:
                intervals[name] = {
                    'min_ms': values[0],
                    'max_ms': values[-1],
                    'median_ms': values[len(values) // 2],
                    'scope': 'host_serial_observation',
                }
        return {
            'contract_id': 'rider.uart.analysis',
            'contract_version': 1,
            'scope': 'observed_serial_calls_not_controller_internal_bus'
            if self.source == 'serial_calls'
            else self.source,
            'source': self.source,
            'source_declared_by_operator': self.source != 'serial_calls',
            'firmware': self.inferred,
            'firmware_override': self.firmware,
            'duration_s': (self.last - self.first) / 1000000000.0
            if self.first is not None and self.last is not None
            else None,
            'frame_counts': dict(self.counts),
            'fault_counts': dict(self.faults),
            'capture_loss_observed': self.loss,
            'continuity_gaps': self.gaps,
            'transaction_outcomes': dict(outcomes),
            'latency_ms': {'min': min(latencies), 'max': max(latencies)} if latencies else None,
            'write_intervals': intervals,
            'sensor_ranges': {
                name: {'min': min(v), 'max': max(v), 'samples': len(v)} for name, v in self.sensors.items()
            },
            'work_status_changes': self.states,
            'write_acknowledgement': 'not_confirmed',
            'physical_completion': 'unverified',
            'transactions': self.transactions,
            'command_changes': self.changes,
            'timeline': self.timeline,
        }


def analyze(events, *, firmware=None, response_timeout_ms=100, source="serial_calls"):
    if source not in {"serial_calls", "wire_export", "controller_bus_export"}:
        raise ValueError("unsupported_capture_source")
    if not 1 <= response_timeout_ms <= 5000:
        raise ValueError("response_timeout_ms_must_be_1_to_5000")
    analysis = _Analysis(firmware, response_timeout_ms, source)
    for event in events:
        analysis.add(event)
    return analysis.report()


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
