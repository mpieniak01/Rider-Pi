"""Return-home planning from verified source snapshots, never guessed origins."""

import logging

from apps.navigator import pathfinding
from apps.navigator.quality import MAP_MAX_AGE_S, POSE_MAX_AGE_S
from apps.navigator.state import NavigatorState
from common.bus import TOPIC_NAVIGATOR_MAP_REQUEST
from common.data_quality import confirmed_home, finite_number, frame_identity, pose_status, sample_status

LOG = logging.getLogger("navigator")
MAX_MAP_CELLS = 65536


def checked_grid(payload):
    """Bound CPU/memory and reject malformed/uncalibrated map geometry."""
    if not isinstance(payload, dict) or payload.get("planning_ready") is not True:
        raise ValueError("map_unverified")
    if frame_identity(payload) is None:
        raise ValueError("map_frame_unknown")
    if confirmed_home(payload) is None:
        raise ValueError("map_home_unconfirmed")
    if (
        payload.get("stopping_horizon_verified") is not True
        or not finite_number(payload.get("stopping_horizon_m"))
        or payload["stopping_horizon_m"] <= 0
    ):
        raise ValueError("map_stopping_horizon_unverified")
    width, height = payload.get("width_cells"), payload.get("height_cells")
    if type(width) is not int or type(height) is not int or min(width, height) <= 0 or width * height > MAX_MAP_CELLS:
        raise ValueError("map_dimensions_invalid")
    geometry = {key: payload.get(key) for key in ("resolution_m", "origin_x", "origin_y")}
    if not all(finite_number(value) for value in geometry.values()) or geometry["resolution_m"] <= 0:
        raise ValueError("map_geometry_invalid")
    grid = payload.get("grid")
    if not isinstance(grid, list) or len(grid) != height:
        raise ValueError("map_grid_invalid")
    for row in grid:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError("map_grid_invalid")
        if any(type(cell) is not int or cell not in (127, 0, 255) for cell in row):
            raise ValueError("map_cell_invalid")
    return dict(geometry, grid=grid, width_cells=width, height_cells=height)


class PathControl:
    def _request_navigation_map(self, *, force=False):
        if not isinstance(self._request_id, str) or not self._request_id.strip():
            return
        if self._map_inflight or not force and self.clock() - self._map_requested_at < 0.25:
            return
        self._map_request_seq += 1
        self._map_request_id = f"{self._request_id}:map:{self._map_request_seq}"
        self._map_requested_at = self.clock()
        self._map_inflight = True
        self.pub.publish(TOPIC_NAVIGATOR_MAP_REQUEST, {"request_id": self._map_request_id}, add_ts=True)

    def _handle_return_home_start(self, cmd):
        if not self._accept_motion_request(cmd):
            return
        quality = self.navigation_quality(returning=False)
        pose = pose_status(self.pose_sample, max_age_s=POSE_MAX_AGE_S, now=self.wall_clock())
        home = confirmed_home(self.pose_sample)
        if not quality["data_ready"] or not pose["ready"] or home is None:
            self._quality_failure(
                quality["obstacle"]["error"] or pose["error"] or "current_confirmed_home_required", stop=True
            )
            return
        self._send_motion_stop()
        self._clear_plan()
        self._passive_planning = True
        self.active = False
        self.state = NavigatorState.RETURNING_HOME
        self.goal_pose = home
        self._return_frame = frame_identity(self.pose_sample)
        self.current_path = []
        self.map_sample = None
        self.waiting_for_map = True
        self._map_inflight = False
        self.state_changed = True
        self._request_navigation_map(force=True)

    def _handle_map_data(self, payload):
        if not (self.active or self.state == NavigatorState.RETURNING_HOME):
            return
        if (
            self._map_request_id is None
            or not isinstance(payload, dict)
            or payload.get("request_id") != self._map_request_id
        ):
            return
        self._map_inflight = False
        status = sample_status(payload, max_age_s=MAP_MAX_AGE_S, now=self.wall_clock())
        try:
            if not status["ready"]:
                raise ValueError(status["error"])
            grid = checked_grid(payload)
            pose = pose_status(self.pose_sample, max_age_s=POSE_MAX_AGE_S, now=self.wall_clock())
            if not pose["ready"] or self.current_pose is None:
                raise ValueError(pose["error"] or "pose_unknown")
            if frame_identity(payload) != frame_identity(self.pose_sample):
                raise ValueError("map_pose_frame_mismatch")
            if confirmed_home(payload) != confirmed_home(self.pose_sample):
                raise ValueError("map_home_mismatch")
            if self.state == NavigatorState.RETURNING_HOME:
                if confirmed_home(payload) != self.goal_pose:
                    raise ValueError("return_home_changed")
                path = pathfinding.find_path(grid, self.current_pose[:2], self.goal_pose, allow_unknown=False)
                if not path:
                    raise ValueError("no_verified_path")
        except (ValueError, TypeError, OverflowError, IndexError) as exc:
            self._quality_failure(str(exc), stop=True)
            return
        self.map_sample = dict(payload)
        self.waiting_for_map = False
        if self.state == NavigatorState.RETURNING_HOME:
            self.current_path = path
            # The heartbeat proves the process is alive, not that the stored
            # point plan was computed from a new observation.
            self.plan_observed_at = min(status["observed_at"], pose["observed_at"])
            self.plan_frame = frame_identity(payload)
            self.plan_home = dict(self.pose_sample["home"])
        self.state_changed = True
        if self.state == NavigatorState.RETURNING_HOME:
            # Retain an inspectable point plan, never label it a traversable
            # physical route or execute it. STOP already revoked the task lease.
            self.active = False
            self.state = NavigatorState.PATH_BLOCKED
            self.data_error = "navigation_traversal_unverified"
            self._passive_planning = False
            self.state_changed = True
        else:
            self._quality_tick()

    def _handle_robot_pose(self, payload):
        previous = self.pose_sample.get("observed_at") if self.pose_sample else None
        status = pose_status(payload, max_age_s=POSE_MAX_AGE_S, now=self.wall_clock(), previous_ts=previous)
        if not status["ready"]:
            self.pose_sample = None
            self.current_pose = None
            if self.current_path:
                self._clear_plan()
                self.state_changed = True
            if self.state == NavigatorState.RETURNING_HOME:
                self._quality_failure(status["error"], stop=True)
            return
        identity = frame_identity(payload)
        if self.current_path and (self.plan_frame != identity or confirmed_home(payload) != self.goal_pose):
            self._clear_plan()
            self.map_sample = None
            self.data_error = "plan_frame_changed"
            self.state_changed = True
        if (self.active or self.state == NavigatorState.RETURNING_HOME) and (
            getattr(self, "_return_frame", identity) != identity
            or self.state == NavigatorState.RETURNING_HOME
            and confirmed_home(payload) != self.goal_pose
            or self.map_sample is not None
            and frame_identity(self.map_sample) != identity
        ):
            self.pose_sample = None
            self.current_pose = None
            self._quality_failure("pose_frame_changed", stop=True)
            return
        self.pose_sample = dict(payload, observed_at=status["observed_at"])
        self.current_pose = (payload["x"], payload["y"], payload["theta"])

    def _update_path_following(self):
        if self.state != NavigatorState.RETURNING_HOME or self.waiting_for_map:
            return
        self._quality_failure(self.navigation_quality()["data_error"] or "navigation_traversal_unverified", stop=True)
