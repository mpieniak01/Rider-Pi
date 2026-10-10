"""Navigation states shared by the controller and its motion producer."""

import time
from enum import Enum


class Strategy(Enum):
    """Navigation strategy when obstacle detected"""

    STOP = "STOP"
    AVOID = "AVOID"


class NavigatorState(Enum):
    """Navigator operational states"""

    IDLE = "idle"
    EXPLORING = "exploring"
    AVOIDING = "avoiding"
    STOPPED = "stopped"
    RETURNING_HOME = "returning_home"  # Stage 4: Navigating back to start
    PATH_BLOCKED = "path_blocked"  # Stage 4: Obstacle detected during return


class StatePublisher:
    def _publish_state(self, force: bool = False):
        """Publish navigator state to bus

        Args:
            force: If True, publish regardless of state change (for heartbeat)
        """
        if not force and not self.state_changed:
            return

        state = {
            "active": self.active,
            "state": self.state.value,
            "strategy": self.strategy.value,
            "obstacle_present": self.obstacle_present,
            "ts": time.time(),
            "observed_at": time.time(),
            "generation": getattr(self, "_motion_generation", None),
            "request_id": getattr(self, "_request_id", None),
        }
        self.pub.publish("navigator.state", state, add_ts=True)
        self.state_changed = False
        self.last_state_publish_ts = time.time()
