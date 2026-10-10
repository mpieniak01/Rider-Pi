"""Navigation states shared by the controller and its motion producer."""

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
            "ts": self.wall_clock(),
            "observed_at": self.wall_clock(),
            "generation": getattr(self, "_request_generation", None),
            "request_id": getattr(self, "_request_id", None),
            "planning_only": True,
            "goal_pose": self.goal_pose,
            "planned_path": self.current_path[:128],
            "planned_path_length": len(self.current_path),
            "planned_path_truncated": len(self.current_path) > 128,
            "plan_observed_at": self.plan_observed_at,
            "plan_calibration_id": self.plan_frame[0] if self.plan_frame else None,
            "plan_reference_id": self.plan_frame[1] if self.plan_frame else None,
            "plan_home": self.plan_home,
        }
        state.update(self.navigation_quality())
        self.pub.publish("navigator.state", state, add_ts=True)
        self.state_changed = False
        self.last_state_publish_ts = self.wall_clock()
