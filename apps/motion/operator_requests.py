"""Bounded command ledger for idempotent warm operations, without output replay."""

from __future__ import annotations

import copy


class OperatorRequests:
    def __init__(self):
        self.rows = {}

    def begin(self, command):
        key = command.get("request_id")
        previous = self.rows.get(key)
        if previous is not None:
            return previous if previous["command"] == command else {"conflict": True}
        self.rows[key] = {"command": copy.deepcopy(command), "ack": None}
        while len(self.rows) > 32:
            del self.rows[next(iter(self.rows))]
        return None

    def observe(self, command, ack):
        if ack.get("operator_replay"):
            return
        key = command.get("request_id")
        if not isinstance(key, str):
            return
        row = self.rows.get(key)
        if row is not None and all(
            row["command"].get(key) == command.get(key) for key in ("action", "source", "generation", "seq")
        ):
            row["ack"] = dict(ack)
