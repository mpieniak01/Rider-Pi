"""Fail closed source quality for navigation; publication is never observation."""

from apps.navigator.state import NavigatorState
from common.data_quality import confirmed_home, finite_number, frame_identity, pose_status, sample_status

OBSTACLE_MAX_AGE_S = 0.5
POSE_MAX_AGE_S = 0.5
MAP_MAX_AGE_S = 3.0


class NavigationQuality:
    def _init_quality(self):
        self.obstacle_sample = None
        self.pose_sample = None
        self.map_sample = None
        self.last_observation = None
        self._obstacle_error = None
        self._intent_start_ts = None
        self._motion_started = False
        self._data_blocked = False
        self.data_error = "inputs_pending"
        self._map_inflight = False
        self._map_request_seq = 0
        self._map_requested_at = 0.0
        self._passive_planning = False
        self._clear_plan()

    def _clear_plan(self):
        self.current_path = []
        self.goal_pose = None
        self.plan_observed_at = None
        self.plan_frame = None
        self.plan_home = None

    def navigation_quality(self, *, returning=None):
        returning = self.state == NavigatorState.RETURNING_HOME if returning is None else returning
        obstacle = sample_status(self.obstacle_sample, max_age_s=OBSTACLE_MAX_AGE_S, now=self.wall_clock())
        pose = pose_status(self.pose_sample, max_age_s=POSE_MAX_AGE_S, now=self.wall_clock())
        mapping = sample_status(self.map_sample, max_age_s=MAP_MAX_AGE_S, now=self.wall_clock())
        error = self._obstacle_error or obstacle["error"]
        if obstacle["ready"]:
            if self.obstacle_sample.get("present") is True:
                error = "obstacle_present"
            elif self._intent_start_ts is not None and obstacle["observed_at"] < self._intent_start_ts:
                error = "observation_before_intent"
        geometry_error = pose["error"] or mapping["error"]
        home = confirmed_home(self.pose_sample)
        if not geometry_error and home is None:
            geometry_error = "current_confirmed_home_required"
        if not geometry_error and frame_identity(self.map_sample) != frame_identity(self.pose_sample):
            geometry_error = "map_pose_frame_mismatch"
        if not geometry_error and confirmed_home(self.map_sample) != home:
            geometry_error = "map_home_mismatch"
        if not geometry_error and (
            self.map_sample.get("stopping_horizon_verified") is not True
            or not finite_number(self.map_sample.get("stopping_horizon_m"))
            or self.map_sample["stopping_horizon_m"] <= 0
        ):
            geometry_error = "map_stopping_horizon_unverified"
        if not geometry_error:
            ranges = self.map_sample.get("range_quality")
            range_status = sample_status(ranges, max_age_s=OBSTACLE_MAX_AGE_S, now=self.wall_clock())
            if (
                not range_status["ready"]
                or not isinstance(ranges, dict)
                or ranges.get("ready") is not True
                or not isinstance(self.map_sample.get("range_calibration_id"), str)
                or not self.map_sample["range_calibration_id"]
            ):
                geometry_error = range_status["error"] or "verified_range_required"
        if returning and self.waiting_for_map:
            geometry_error = geometry_error or "map_pending"
        # Neither ROI clearance nor point A* establishes a swept corridor and
        # braking horizon for the physical robot. Both modes are passive until
        # that separately reviewed characterization/planner exists.
        geometry_error = geometry_error or "navigation_traversal_unverified"
        if self._data_blocked:
            error = self.data_error or "new_operator_intent_required"
        return {
            "data_ready": error is None,
            "navigation_ready": error is None and geometry_error is None,
            "data_error": error or geometry_error,
            "obstacle": obstacle,
            "pose": pose,
            "map": mapping,
            "physical_completion": "unverified",
        }

    def _quality_failure(self, reason, *, stop=False):
        self.data_error = reason
        if stop or self._motion_started:
            returning = self.state == NavigatorState.RETURNING_HOME
            self._data_blocked = True
            self.active = False
            self._clear_plan()
            self.waiting_for_map = False
            self._map_inflight = False
            self._passive_planning = False
            self.state = NavigatorState.PATH_BLOCKED if returning else NavigatorState.STOPPED
            self._send_motion_stop()
            self._motion_started = False
        self.state_changed = True

    def _quality_tick(self):
        quality = self.navigation_quality()
        if self._motion_started and not quality["navigation_ready"]:
            self._quality_failure(quality["data_error"], stop=True)
        elif not self._data_blocked:
            self.data_error = quality["data_error"]
        if self._map_inflight and self.clock() - self._map_requested_at > MAP_MAX_AGE_S:
            self._quality_failure("map_request_timeout", stop=True)
        if (self.active or self.state == NavigatorState.RETURNING_HOME) and not self._data_blocked:
            self._request_navigation_map()

    def _handle_obstacle_sample(self, payload):
        status = sample_status(
            payload, max_age_s=OBSTACLE_MAX_AGE_S, now=self.wall_clock(), previous_ts=self.last_observation
        )
        confidence = payload.get("confidence") if isinstance(payload, dict) else None
        present = payload.get("present") if isinstance(payload, dict) else None
        if status["ready"] and (type(present) is not bool or not finite_number(confidence) or not 0 <= confidence <= 1):
            status.update(ready=False, error="invalid_obstacle_sample")
        if status["ready"] and present is False and confidence == 0:
            status.update(ready=False, error="clear_space_unconfirmed")
        if not status["ready"]:
            self.obstacle_sample = None
            self._obstacle_error = status["error"]
            self._quality_failure(status["error"])
            return
        self.obstacle_sample = dict(payload, observed_at=status["observed_at"])
        self.last_observation = status["observed_at"]
        self._obstacle_error = None
        self.obstacle_present = present
        self.state_changed = True
        if self._data_blocked:
            return
        if self.state == NavigatorState.RETURNING_HOME and present:
            self._quality_failure("obstacle_present", stop=True)
        elif self.active:
            self._react_obstacle(present, confidence)
        self._quality_tick()

    def _handle_obstacle(self, present, confidence, *, observed_at=None):
        """Compatibility hook still requires the original observation time."""
        self._handle_obstacle_sample({"present": present, "confidence": confidence, "observed_at": observed_at})

    def _motion_data_permitted(self, lx, az):
        # No point-map metadata flag may enable autonomous SDK writes in PR06.
        self._quality_failure(self.navigation_quality()["data_error"] or "navigation_traversal_unverified", stop=True)
        return False
