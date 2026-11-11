"""Replay bounded JSON decisions through the real lease with mock actuation only."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.compute.decision_lease import DecisionLease  # noqa: E402


def main():
    data = json.loads(sys.stdin.read(256 * 1024))
    now, outputs = [0.0], []
    lease = DecisionLease(
        data["config"],
        "offline",
        lambda *args: outputs.append(("go", *args)),
        lambda: outputs.append(("halt",)),
        pause=lambda *args: outputs.append(("zero", *args)),
        steer=lambda *args: outputs.append(("steer", *args)),
        clock=lambda: now[0],
        feedback_wait=True,
    )
    for row in data["replies"]:
        now[0] = row["captured"]
        decision = row["decision"]
        lease.accept(decision, decision["frame_id"], decision["sequence"], row["captured"])
    print(json.dumps({"outputs": outputs, "latched": lease.latched, "reason": lease.reason}))


if __name__ == "__main__":
    main()
