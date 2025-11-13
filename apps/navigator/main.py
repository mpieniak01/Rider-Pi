#!/usr/bin/env python3
"""
Navigator - Autonomous Rekonesans (Reconnaissance) Mode

Stage 1: Reactive obstacle avoidance
- Subscribes to vision.obstacle topic
- Implements STOP and AVOID strategies
- Publishes movement commands to motion topic

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
from enum import Enum

from apps.navigator import pathfinding
from apps.navigator.ai_mode_adapter import log_navigator_mode_status, should_use_pc_enhanced_data
from common.bus import (
    TOPIC_MAPPER_MAP_DATA,
    TOPIC_NAVIGATOR_MAP_REQUEST,
    TOPIC_NAVIGATOR_RETURN_HOME_START,
    TOPIC_ROBOT_POSE,
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
TOPIC_MOTION = "motion"
TOPIC_NAVIGATOR_STATE = "navigator.state"
TOPIC_NAVIGATOR_CONTROL = "navigator.control"

LOG = logging.getLogger("navigator")


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


class Navigator:
    """Autonomous navigation controller"""

    def __init__(self, strategy: Strategy = Strategy.STOP):
        self.strategy = strategy
        self.state = NavigatorState.IDLE
        self.active = False

        # Bus connections
        self.sub_obstacle = BusSub(TOPIC_VISION_OBSTACLE)
        self.sub_obstacle_enhanced = None  # Will be initialized if needed
        self.sub_control = BusSub(TOPIC_NAVIGATOR_CONTROL)
        self.sub_return_home = BusSub(TOPIC_NAVIGATOR_RETURN_HOME_START)
        self.sub_map_data = BusSub(TOPIC_MAPPER_MAP_DATA)
        self.sub_robot_pose = BusSub(TOPIC_ROBOT_POSE)
        self.pub = BusPub()

        # Check if we should use enhanced PC data
        self.use_pc_enhanced = should_use_pc_enhanced_data()
        if self.use_pc_enhanced:
            # In pc_offload mode, subscribe to enhanced obstacle data from PC
            self.sub_obstacle_enhanced = BusSub(TOPIC_VISION_OBSTACLE_ENHANCED)
            LOG.info("Navigator: Using PC-enhanced obstacle data (vision.obstacle.enhanced)")

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
        self.goal_pose = (0.0, 0.0)  # Default goal is origin
        self.current_pose = (0.0, 0.0, 0.0)  # (x, y, theta)
        self.waiting_for_map = False

        LOG.info(f"Navigator initialized with strategy: {self.strategy.value}")

    def start(self):
        """Start autonomous exploration"""
        if self.active:
            LOG.warning("Navigator already active")
            return

        self.active = True
        self.state = NavigatorState.EXPLORING
        LOG.info("Navigator started - beginning exploration")
        self._send_motion_drive(self.fwd_speed)
        self.state_changed = True
        self._publish_state()

    def stop(self):
        """Stop autonomous exploration"""
        if not self.active:
            return

        self.active = False
        self.state = NavigatorState.STOPPED
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

    def _send_motion_drive(self, lx: float, az: float = 0.0):
        """Send drive command to motion system"""
        cmd = {"type": "drive", "lx": lx, "az": az}
        self.pub.publish(TOPIC_MOTION, cmd)
        LOG.debug(f"Motion command: {cmd}")

    def _send_motion_stop(self):
        """Send stop command to motion system"""
        cmd = {"type": "stop"}
        self.pub.publish(TOPIC_MOTION, cmd)
        LOG.debug("Motion STOP command sent")

    def _handle_obstacle(self, present: bool, confidence: float):
        """Handle obstacle detection event"""
        # Only react if navigator is active
        if not self.active:
            return

        old_obstacle = self.obstacle_present
        old_state = self.state

        self.obstacle_present = present
        self.last_obstacle_ts = time.time()

        if not present:
            # No obstacle - resume exploration
            if self.state != NavigatorState.EXPLORING:
                self.state = NavigatorState.EXPLORING
                LOG.info("Obstacle cleared - resuming exploration")
            self._send_motion_drive(self.fwd_speed)
        else:
            # Obstacle detected
            LOG.info(f"Obstacle detected (confidence: {confidence:.2f})")

            if self.strategy == Strategy.STOP:
                self._handle_stop_strategy()
            elif self.strategy == Strategy.AVOID:
                self._handle_avoid_strategy()

        # Mark state as changed if obstacle presence or state changed
        if old_obstacle != self.obstacle_present or old_state != self.state:
            self.state_changed = True

    def _handle_stop_strategy(self):
        """STOP strategy: stop when obstacle detected"""
        self._send_motion_stop()
        self.state = NavigatorState.STOPPED
        LOG.info("STOP strategy: robot stopped due to obstacle")

    def _handle_avoid_strategy(self):
        """AVOID strategy: turn and continue when obstacle detected"""
        now = time.time()

        # Cooldown check to prevent rapid turns
        if now - self.last_avoid_ts < COOLDOWN_AFTER_AVOID:
            return

        self.last_avoid_ts = now
        self.state = NavigatorState.AVOIDING

        # Turn right (could be randomized or based on sensor data)
        LOG.info("AVOID strategy: turning to avoid obstacle")
        self._send_motion_drive(0.0, -self.turn_speed)  # Turn right

        # Schedule return to forward motion after turn
        # Note: In a production system, this would be managed by a state machine
        # with proper timing. For now, we rely on the motion system's impulse duration.

    def _handle_control_command(self, cmd: dict):
        """Handle control commands from API"""
        action = cmd.get("action", "").lower()

        if action == "start":
            strategy_str = cmd.get("strategy", "STOP")
            try:
                strategy = Strategy[strategy_str.upper()]
                self.set_strategy(strategy)
            except KeyError:
                LOG.warning(f"Invalid strategy in start command: {strategy_str}")
            self.start()

        elif action == "stop":
            self.stop()

        elif action == "config":
            config = cmd.get("config", {})
            changed = False

            if "strategy" in config:
                try:
                    strategy = Strategy[config["strategy"].upper()]
                    self.set_strategy(strategy)
                    changed = True
                except KeyError:
                    LOG.warning(f"Invalid strategy in config: {config['strategy']}")

            if "fwd_speed" in config:
                self.fwd_speed = float(config["fwd_speed"])
                LOG.info(f"Forward speed set to: {self.fwd_speed}")
                changed = True

            if "turn_speed" in config:
                self.turn_speed = float(config["turn_speed"])
                LOG.info(f"Turn speed set to: {self.turn_speed}")
                changed = True

            if changed:
                self.state_changed = True

        else:
            LOG.warning(f"Unknown control action: {action}")

    def _handle_return_home_start(self, cmd: dict):
        """Handle return to home command from API"""
        LOG.info("Return to home command received")

        # Stop current activity
        if self.active:
            self._send_motion_stop()
            self.active = False

        # Set state to returning home
        self.state = NavigatorState.RETURNING_HOME
        self.goal_pose = (0.0, 0.0)  # Return to origin
        self.current_path = []
        self.waiting_for_map = True
        self.state_changed = True

        # Request map from mapper
        LOG.info("Requesting map from mapper")
        self.pub.publish(TOPIC_NAVIGATOR_MAP_REQUEST, {"request_id": time.time()}, add_ts=True)

    def _handle_map_data(self, payload: dict):
        """Handle map data from mapper"""
        if self.state != NavigatorState.RETURNING_HOME or not self.waiting_for_map:
            return

        LOG.info("Received map data from mapper")
        self.waiting_for_map = False

        # Prepare grid data
        grid_data = {
            "grid": payload.get("grid", []),
            "width_cells": payload.get("width_cells", 0),
            "height_cells": payload.get("height_cells", 0),
            "resolution_m": payload.get("resolution_m", 0.05),
            "origin_x": payload.get("origin_x", 5.0),
            "origin_y": payload.get("origin_y", 5.0),
        }

        # Get current position
        start_pose = (self.current_pose[0], self.current_pose[1])

        LOG.info(f"Planning path from {start_pose} to {self.goal_pose}")

        # Find path using A*
        try:
            path = pathfinding.find_path(grid_data, start_pose, self.goal_pose, allow_unknown=True)
        except Exception as e:
            LOG.exception(f"Error during pathfinding: {e}")
            path = None

        if path is None or len(path) == 0:
            LOG.error("No path found to goal")
            self.state = NavigatorState.PATH_BLOCKED
            self.state_changed = True
            self._send_motion_stop()
            return

        LOG.info(f"Path found with {len(path)} waypoints")
        self.current_path = path
        self.state_changed = True

        # Start following the path
        self._update_path_following()

    def _handle_robot_pose(self, payload: dict):
        """Update current robot pose from odometry"""
        self.current_pose = (
            float(payload.get("x", 0.0)),
            float(payload.get("y", 0.0)),
            float(payload.get("theta", 0.0)),
        )

    def _update_path_following(self):
        """Update path following logic"""
        if self.state != NavigatorState.RETURNING_HOME:
            return

        if not self.current_path:
            # Path is empty, check if we're actually at the goal
            current_x, current_y, _ = self.current_pose
            goal_x, goal_y = self.goal_pose[0], self.goal_pose[1]
            goal_dx = goal_x - current_x
            goal_dy = goal_y - current_y
            goal_distance = math.sqrt(goal_dx**2 + goal_dy**2)

            if goal_distance < GOAL_TOLERANCE:
                LOG.info("Reached goal position!")
                self.state = NavigatorState.IDLE
                self.state_changed = True
                self._send_motion_stop()
            else:
                LOG.warning(
                    f"Path is empty but robot is not at goal "
                    f"(distance={goal_distance:.2f}m > tolerance={GOAL_TOLERANCE:.2f}m)"
                )
                # Stay in RETURNING_HOME state for potential replan
            return

        # Loop to process consecutive waypoints within tolerance
        current_x, current_y, current_theta = self.current_pose

        while self.current_path:
            target_x, target_y = self.current_path[0]
            dx = target_x - current_x
            dy = target_y - current_y
            distance = math.sqrt(dx**2 + dy**2)

            # Check if we've reached the waypoint
            if distance < WAYPOINT_TOLERANCE:
                LOG.info(f"Reached waypoint ({target_x:.2f}, {target_y:.2f})")
                self.current_path.pop(0)

                # Check if this was the last waypoint
                if not self.current_path:
                    # Check if we're close enough to the goal
                    goal_dx = self.goal_pose[0] - current_x
                    goal_dy = self.goal_pose[1] - current_y
                    goal_distance = math.sqrt(goal_dx**2 + goal_dy**2)

                    if goal_distance < GOAL_TOLERANCE:
                        LOG.info("Successfully reached home position!")
                        self.state = NavigatorState.IDLE
                        self.state_changed = True
                        self._send_motion_stop()
                        return
                # Continue to next waypoint in the loop
                continue
            else:
                break

        # If there are no more waypoints after the loop, return
        if not self.current_path:
            return

        # Calculate required heading to waypoint
        target_x, target_y = self.current_path[0]
        current_x, current_y, current_theta = self.current_pose
        dx = target_x - current_x
        dy = target_y - current_y
        target_angle = math.atan2(dy, dx)

        # Normalize angle difference to [-pi, pi]
        angle_error = target_angle - current_theta
        while angle_error > math.pi:
            angle_error -= 2 * math.pi
        while angle_error < -math.pi:
            angle_error += 2 * math.pi

        # If angle error is large, turn in place
        if abs(angle_error) > ANGLE_TOLERANCE:
            # Turn towards waypoint
            turn_direction = 1.0 if angle_error > 0 else -1.0
            self._send_motion_drive(0.0, turn_direction * self.turn_speed)
            LOG.debug(f"Turning: angle_error={math.degrees(angle_error):.1f}°")
        else:
            # Move forward towards waypoint
            self._send_motion_drive(self.fwd_speed, 0.0)
            LOG.debug(f"Moving forward: distance={distance:.2f}m")

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
        }
        self.pub.publish(TOPIC_NAVIGATOR_STATE, state, add_ts=True)
        self.state_changed = False
        self.last_state_publish_ts = time.time()

    def run(self):
        """Main navigation loop"""
        LOG.info("Navigator main loop started")
        log_navigator_mode_status()
        self.state_changed = True
        self._publish_state()

        # Heartbeat interval: publish state every 5 seconds even if unchanged
        HEARTBEAT_INTERVAL = 5.0
        # Path following update interval
        PATH_UPDATE_INTERVAL = 0.2  # 5Hz

        last_path_update = time.time()

        try:
            while True:
                # Receive obstacle events - check both local and enhanced sources
                if self.use_pc_enhanced and self.sub_obstacle_enhanced:
                    # In pc_offload mode, prioritize enhanced obstacle data
                    topic, payload = self.sub_obstacle_enhanced.recv(timeout_ms=10)
                    if topic and payload and topic == TOPIC_VISION_OBSTACLE_ENHANCED:
                        present = payload.get("present", False)
                        confidence = payload.get("confidence", 0.0)
                        # Enhanced data includes distance and angle from PC
                        distance = payload.get("distance")
                        angle = payload.get("angle")
                        if distance is not None and angle is not None:
                            LOG.debug(
                                f"Enhanced obstacle data from PC: present={present}, "
                                f"distance={distance:.2f}m, angle={angle:.1f}°"
                            )
                        if self.active:
                            self._handle_obstacle(present, confidence)
                        # Check for obstacles during return to home
                        elif self.state == NavigatorState.RETURNING_HOME and present:
                            LOG.warning("Obstacle detected during return to home - stopping")
                            self.state = NavigatorState.PATH_BLOCKED
                            self.state_changed = True
                            self._send_motion_stop()
                else:
                    # Local mode: use local vision obstacle data
                    topic, payload = self.sub_obstacle.recv(timeout_ms=10)
                    if topic and payload and topic == TOPIC_VISION_OBSTACLE:
                        present = payload.get("present", False)
                        confidence = payload.get("confidence", 0.0)
                        if self.active:
                            self._handle_obstacle(present, confidence)
                        # Check for obstacles during return to home
                        elif self.state == NavigatorState.RETURNING_HOME and present:
                            LOG.warning("Obstacle detected during return to home - stopping")
                            self.state = NavigatorState.PATH_BLOCKED
                            self.state_changed = True
                            self._send_motion_stop()

                # Receive control commands from API
                topic, payload = self.sub_control.recv(timeout_ms=10)
                if topic and payload and topic == TOPIC_NAVIGATOR_CONTROL:
                    self._handle_control_command(payload)

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

                # Update path following if in return to home mode
                if self.state == NavigatorState.RETURNING_HOME:
                    now = time.time()
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
        except Exception as e:
            LOG.exception(f"Error in navigator loop: {e}")
        finally:
            self.stop()
            self.sub_obstacle.close()
            if self.sub_obstacle_enhanced:
                self.sub_obstacle_enhanced.close()
            self.sub_control.close()
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
        LOG.warning(f"Invalid strategy '{STRATEGY}', using STOP")
        strategy = Strategy.STOP

    navigator = Navigator(strategy=strategy)

    # Auto-start if configured
    auto_start = os.getenv("NAVIGATOR_AUTO_START", "0") == "1"
    if auto_start:
        navigator.start()

    navigator.run()


if __name__ == "__main__":
    main()
