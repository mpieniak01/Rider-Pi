#!/usr/bin/env python3
"""
Navigator - Autonomous Rekonesans (Reconnaissance) Mode

Stage 4: Return to Home
- Path planning with A* algorithm
- Autonomous navigation back to starting position
- Integration with mapper and odometry
"""

from __future__ import annotations

import logging
import math
import os
import time

from apps.navigator.ai_mode_adapter import log_navigator_mode_status
from apps.navigator.motion import MotionProducer
from apps.navigator.path_control import PathControl
from apps.navigator.quality import NavigationQuality
from apps.navigator.state import NavigatorState, StatePublisher, Strategy
from common.bus import (
    TOPIC_MAPPER_MAP_DATA,
    TOPIC_NAVIGATOR_RETURN_HOME_START,
    TOPIC_ROBOT_POSE,
    TOPIC_SYSTEM_AI_MODE_CHANGED,
    TOPIC_VISION_OBSTACLE_ENHANCED,
    BusPub,
    BusSub,
)

# Environment configuration
LOG_LEVEL = os.getenv("NAVIGATOR_LOG_LEVEL", "INFO").upper()
STRATEGY = os.getenv("NAVIGATOR_STRATEGY", "STOP")  # STOP or AVOID
FWD_SPEED = float(os.getenv("NAVIGATOR_FWD_SPEED", "0.3"))
TURN_SPEED = float(os.getenv("NAVIGATOR_TURN_SPEED", "0.4"))
TURN_DURATION = float(os.getenv("NAVIGATOR_TURN_DURATION", "0.5"))
COOLDOWN_AFTER_AVOID = float(os.getenv("NAVIGATOR_COOLDOWN", "1.0"))

# Path following parameters
WAYPOINT_TOLERANCE = float(os.getenv("NAVIGATOR_WAYPOINT_TOLERANCE", "0.15"))  # meters
ANGLE_TOLERANCE = float(os.getenv("NAVIGATOR_ANGLE_TOLERANCE", "0.2"))  # radians (~11 degrees)
GOAL_TOLERANCE = float(os.getenv("NAVIGATOR_GOAL_TOLERANCE", "0.1"))  # meters

# Bus topics
TOPIC_VISION_OBSTACLE = "vision.obstacle"
TOPIC_NAVIGATOR_STATE = "navigator.state"
TOPIC_NAVIGATOR_CONTROL = "navigator.control"
PUB_WARMUP_MS = int(os.getenv("NAVIGATOR_PUB_WARMUP_MS", "500"))

LOG = logging.getLogger("navigator")


class Navigator(MotionProducer, PathControl, NavigationQuality, StatePublisher):
    """Autonomous navigation controller"""

    def __init__(self, strategy: Strategy = Strategy.STOP, *, wall_clock=time.time, clock=time.monotonic):
        self.wall_clock, self.clock = wall_clock, clock
        self.strategy = strategy
        self.state = NavigatorState.IDLE
        self.active = False
        self._intent = None
        self._request_id = None
        self._consumed_intent = None
        self._intent_status_at = 0.0

        # Bus connections
        self.sub_obstacle = BusSub(TOPIC_VISION_OBSTACLE)
        self.sub_obstacle_enhanced: BusSub | None = None
        self.sub_control = BusSub(TOPIC_NAVIGATOR_CONTROL)
        self.sub_return_home = BusSub(TOPIC_NAVIGATOR_RETURN_HOME_START)
        self.sub_map_data = BusSub(TOPIC_MAPPER_MAP_DATA)
        self.sub_robot_pose = BusSub(TOPIC_ROBOT_POSE)
        # Subscribe to AI mode changes (local / pc_offload)
        self.sub_ai_mode = BusSub(TOPIC_SYSTEM_AI_MODE_CHANGED)
        self.pub = BusPub(warmup_ms=PUB_WARMUP_MS)

        # Start always in local mode; AI events will switch to pc_offload if needed
        self.use_pc_enhanced: bool = False

        # State tracking
        self.last_obstacle_ts = 0.0
        self.last_avoid_ts = 0.0
        self.obstacle_present = False
        self.last_state_publish_ts = 0.0
        self.state_changed = False

        # Configuration
        self.fwd_speed = FWD_SPEED
        self.turn_speed = TURN_SPEED

        # Return to home state
        self.current_path = []  # List of waypoints (x, y) in world coordinates
        self.goal_pose = None  # HOME is operator-confirmed in a current reference.
        self.current_pose = None  # Unknown until a verified pose arrives.
        self.waiting_for_map = False
        self.waypoint_tolerance = WAYPOINT_TOLERANCE
        self.angle_tolerance = ANGLE_TOLERANCE
        self.goal_tolerance = GOAL_TOLERANCE
        self._init_quality()

        LOG.info(f"Navigator initialized with strategy: {self.strategy.value}")

    def start(self):
        """Start autonomous exploration"""
        if self.active:
            LOG.warning("Navigator already active")
            return

        self.active = True
        self.state = NavigatorState.EXPLORING
        self._map_inflight = False
        self._request_navigation_map(force=True)
        LOG.info("Navigator started - beginning exploration")
        # This task remains passive until its physical corridor/stopping model
        # has been characterized. Starting a service never sends forward motion.
        self.data_error = self.navigation_quality()["data_error"]
        self.state_changed = True
        self._publish_state()

    def stop(self):
        """Stop autonomous exploration"""
        if (
            not self.active
            and self.state != NavigatorState.RETURNING_HOME
            and not self._passive_planning
            and not self.current_path
        ):
            return

        self.active = False
        self.state = NavigatorState.STOPPED
        self._passive_planning = False
        self._map_inflight = self.waiting_for_map = False
        self._clear_plan()
        self._send_motion_stop()
        LOG.info("Navigator stopped")
        self.state_changed = True
        self._publish_state()

    def set_strategy(self, strategy: Strategy):
        """Change navigation strategy"""
        self.strategy = strategy
        LOG.info(f"Strategy changed to: {self.strategy.value}")
        self.state_changed = True
        self._publish_state()

    def _react_obstacle(self, present: bool, confidence: float):
        """Handle obstacle detection event"""
        # Only react if navigator is active
        if not self.active:
            return

        old_obstacle = self.obstacle_present
        old_state = self.state

        self.obstacle_present = present
        self.last_obstacle_ts = self.last_observation

        if not present:
            # No obstacle - resume exploration
            if self.state != NavigatorState.EXPLORING:
                self.state = NavigatorState.EXPLORING
                LOG.info("Obstacle cleared - resuming exploration")
            self._send_motion_drive(self.fwd_speed)
        else:
            # Obstacle detected
            LOG.info("Obstacle detected (confidence: %.2f)", confidence)

            if self.strategy == Strategy.STOP:
                self._handle_stop_strategy()
            elif self.strategy == Strategy.AVOID:
                self._handle_avoid_strategy()

        # Mark state as changed if obstacle presence or state changed
        if old_obstacle != self.obstacle_present or old_state != self.state:
            self.state_changed = True

    def _handle_stop_strategy(self):
        """STOP strategy: stop when obstacle detected"""
        self._quality_failure("obstacle_present", stop=True)
        LOG.info("STOP strategy: robot stopped due to obstacle")

    def _handle_avoid_strategy(self):
        """AVOID strategy: turn and continue when obstacle detected"""
        now = time.monotonic()

        # Cooldown check to prevent rapid turns
        if now - self.last_avoid_ts < COOLDOWN_AFTER_AVOID:
            return

        self.last_avoid_ts = now
        self.state = NavigatorState.AVOIDING

        # Turn right (could be randomized or based on sensor data)
        LOG.info("AVOID strategy: turning to avoid obstacle")
        self._send_motion_drive(0.0, self.turn_speed, duration=TURN_DURATION)

        # Schedule return to forward motion after turn
        # Note: In a production system, this would be managed by a state machine
        # with proper timing. For now, we rely on the motion system's impulse duration.

    def _configure_navigation(self, cmd):
        from apps.safety.state import read_status

        config = cmd.get("config", {})
        if read_status().get("state") != "DISARMED" or not isinstance(config, dict):
            return
        try:
            speeds = {key: float(config[key]) for key in ("fwd_speed", "turn_speed") if key in config}
            if any(isinstance(config[k], bool) or not math.isfinite(v) or not 0 <= v <= 1 for k, v in speeds.items()):
                return
            if "strategy" in config and config["strategy"] not in {"STOP", "AVOID"}:
                return
        except (ValueError, TypeError, OverflowError):
            return
        self._apply_configuration(config)

    def _apply_configuration(self, config):
        changed = False

        if "strategy" in config:
            try:
                strategy = Strategy[config["strategy"].upper()]
                self.set_strategy(strategy)
                changed = True
            except KeyError:
                LOG.warning("Invalid strategy in config: %s", config["strategy"])

        if "fwd_speed" in config:
            self.fwd_speed = float(config["fwd_speed"])
            LOG.info("Forward speed set to: %s", self.fwd_speed)
            changed = True

        if "turn_speed" in config:
            self.turn_speed = float(config["turn_speed"])
            LOG.info("Turn speed set to: %s", self.turn_speed)
            changed = True

        if changed:
            self.state_changed = True

    def _handle_control_command(self, cmd: dict):
        """Handle control commands from API"""
        if not isinstance(cmd, dict) or not isinstance(cmd.get("action"), str):
            return
        action = cmd["action"].lower()

        if action == "start":
            strategy_str = cmd.get("strategy", "STOP")
            if not isinstance(strategy_str, str) or strategy_str.upper() not in {"STOP", "AVOID"}:
                return
            if not self._accept_motion_request(cmd):
                return
            try:
                strategy = Strategy[strategy_str.upper()]
                self.set_strategy(strategy)
            except KeyError:
                LOG.warning("Invalid strategy in start command: %s", strategy_str)
            self.start()

        elif action == "stop":
            self.stop()

        elif action == "config":
            self._configure_navigation(cmd)

        else:
            LOG.warning("Unknown control action: %s", action)

    def _handle_ai_mode_change(self, payload: dict):
        """Handle AI mode change event dynamically.

        Args:
            payload: Event payload containing new mode.
        """
        new_mode = payload.get("mode", "")
        LOG.info("AI mode change detected: %s", new_mode)

        old_use_pc_enhanced = self.use_pc_enhanced
        self.use_pc_enhanced = new_mode == "pc_offload"

        # If mode changed, update subscriptions
        if old_use_pc_enhanced != self.use_pc_enhanced:
            self.obstacle_sample = None
            self._quality_failure("obstacle_source_changed")
            if self.use_pc_enhanced:
                # Switched to pc_offload mode - create enhanced data subscription
                if self.sub_obstacle_enhanced is None:
                    self.sub_obstacle_enhanced = BusSub(TOPIC_VISION_OBSTACLE_ENHANCED)
                    LOG.info("Navigator: Switched to PC-enhanced obstacle data (vision.obstacle.enhanced)")
            else:
                # Switched to local mode - close enhanced data subscription if it exists
                if self.sub_obstacle_enhanced is not None:
                    try:
                        self.sub_obstacle_enhanced.close()
                    finally:
                        self.sub_obstacle_enhanced = None
                    LOG.info("Navigator: Switched to local obstacle data (vision.obstacle)")

            # Log the new mode
            if self.use_pc_enhanced:
                LOG.info("Navigator AI Mode: pc_offload - Using PC-enhanced obstacle data")
            else:
                LOG.info("Navigator AI Mode: local - Using local obstacle detection")

    def _receive_obstacles(self):
        # Receive obstacle events - check both local and enhanced sources
        if self.use_pc_enhanced and self.sub_obstacle_enhanced:
            # In pc_offload mode, prioritize enhanced obstacle data
            topic, payload = self.sub_obstacle_enhanced.recv(timeout_ms=10)
            if topic and payload and topic == TOPIC_VISION_OBSTACLE_ENHANCED:
                self._handle_obstacle_sample(payload)
        else:
            topic, payload = self.sub_obstacle.recv(timeout_ms=10)
            if topic and payload and topic == TOPIC_VISION_OBSTACLE:
                self._handle_obstacle_sample(payload)

    def _receive_navigation_events(self):
        # Receive control commands from API
        topic, payload = self.sub_control.recv(timeout_ms=10)
        if topic and payload and topic == TOPIC_NAVIGATOR_CONTROL:
            self._handle_control_command(payload)

        # Receive AI mode change events
        topic, payload = self.sub_ai_mode.recv(timeout_ms=10)
        if topic and payload and topic == TOPIC_SYSTEM_AI_MODE_CHANGED:
            self._handle_ai_mode_change(payload)

        # Receive return to home commands
        topic, payload = self.sub_return_home.recv(timeout_ms=10)
        if topic and payload and topic == TOPIC_NAVIGATOR_RETURN_HOME_START:
            self._handle_return_home_start(payload)

        # Receive map data from mapper
        topic, payload = self.sub_map_data.recv(timeout_ms=10)
        if topic and payload and topic == TOPIC_MAPPER_MAP_DATA:
            self._handle_map_data(payload)

        # Receive robot pose updates
        topic, payload = self.sub_robot_pose.recv(timeout_ms=10)
        if topic and payload and topic == TOPIC_ROBOT_POSE:
            self._handle_robot_pose(payload)

    def run(self):
        """Main navigation loop"""
        LOG.info("Navigator main loop started")
        log_navigator_mode_status()
        self.state_changed = True
        self._publish_state()

        # Keep the lightweight snapshot younger than the API's three-second TTL.
        HEARTBEAT_INTERVAL = 1.0
        # Path following update interval
        PATH_UPDATE_INTERVAL = 0.2  # 5Hz

        last_path_update = time.monotonic()

        try:
            while True:
                self._consume_task_intent()
                self._receive_obstacles()
                self._receive_navigation_events()

                self._quality_tick()

                # Update path following if in return to home mode
                if self.state == NavigatorState.RETURNING_HOME:
                    now = time.monotonic()
                    if now - last_path_update >= PATH_UPDATE_INTERVAL:
                        self._update_path_following()
                        last_path_update = now

                # Publish state if changed or heartbeat timeout
                now = time.time()
                if now - self.last_state_publish_ts >= HEARTBEAT_INTERVAL:
                    self._publish_state(force=True)
                else:
                    self._publish_state()

                time.sleep(0.1)

        except KeyboardInterrupt:
            LOG.info("Navigator interrupted by user")
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Error in navigator loop: %s", exc)
        finally:
            self.stop()
            self.sub_obstacle.close()
            if self.sub_obstacle_enhanced is not None:
                self.sub_obstacle_enhanced.close()
            self.sub_control.close()
            self.sub_ai_mode.close()
            self.sub_return_home.close()
            self.sub_map_data.close()
            self.sub_robot_pose.close()
            self.pub.close()
            LOG.info("Navigator shutdown complete")


def main():
    """Entry point"""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Parse strategy from environment
    try:
        strategy = Strategy[STRATEGY.upper()]
    except KeyError:
        LOG.warning("Invalid strategy '%s', using STOP", STRATEGY)
        strategy = Strategy.STOP

    navigator = Navigator(strategy=strategy)

    # Auto-start if configured
    auto_start = os.getenv("NAVIGATOR_AUTO_START", "0") == "1"
    if auto_start:
        navigator.start()

    navigator.run()


if __name__ == "__main__":
    main()
