#!/usr/bin/env python3
"""
Navigator - Autonomous Rekonesans (Reconnaissance) Mode

Stage 1: Reactive obstacle avoidance
- Subscribes to vision.obstacle topic
- Implements STOP and AVOID strategies
- Publishes movement commands to motion topic
"""

from __future__ import annotations

import logging
import os
import time
from enum import Enum

from common.bus import BusPub, BusSub

# Environment configuration
LOG_LEVEL = os.getenv("NAVIGATOR_LOG_LEVEL", "INFO").upper()
STRATEGY = os.getenv("NAVIGATOR_STRATEGY", "STOP")  # STOP or AVOID
FWD_SPEED = float(os.getenv("NAVIGATOR_FWD_SPEED", "0.3"))
TURN_SPEED = float(os.getenv("NAVIGATOR_TURN_SPEED", "0.4"))
TURN_DURATION = float(os.getenv("NAVIGATOR_TURN_DURATION", "0.5"))
COOLDOWN_AFTER_AVOID = float(os.getenv("NAVIGATOR_COOLDOWN", "1.0"))

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


class Navigator:
    """Autonomous navigation controller"""

    def __init__(self, strategy: Strategy = Strategy.STOP):
        self.strategy = strategy
        self.state = NavigatorState.IDLE
        self.active = False

        # Bus connections
        self.sub_obstacle = BusSub(TOPIC_VISION_OBSTACLE)
        self.sub_control = BusSub(TOPIC_NAVIGATOR_CONTROL)
        self.pub = BusPub()

        # State tracking
        self.last_obstacle_ts = 0.0
        self.last_avoid_ts = 0.0
        self.obstacle_present = False

        # Configuration
        self.fwd_speed = FWD_SPEED
        self.turn_speed = TURN_SPEED

        LOG.info(f"Navigator initialized with strategy: {self.strategy.value}")

    def start(self):
        """Start autonomous exploration"""
        if self.active:
            LOG.warning("Navigator already active")
            return

        self.active = True
        self.state = NavigatorState.EXPLORING
        LOG.info("Navigator started - beginning exploration")
        self._publish_state()

    def stop(self):
        """Stop autonomous exploration"""
        if not self.active:
            return

        self.active = False
        self.state = NavigatorState.STOPPED
        self._send_motion_stop()
        LOG.info("Navigator stopped")
        self._publish_state()

    def set_strategy(self, strategy: Strategy):
        """Change navigation strategy"""
        self.strategy = strategy
        LOG.info(f"Strategy changed to: {self.strategy.value}")
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

        self.obstacle_present = present
        self.last_obstacle_ts = time.time()

        if not present:
            # No obstacle - resume exploration
            if self.state != NavigatorState.EXPLORING:
                self.state = NavigatorState.EXPLORING
                LOG.info("Obstacle cleared - resuming exploration")
            self._send_motion_drive(self.fwd_speed)
            self._publish_state()
            return

        # Obstacle detected
        LOG.info(f"Obstacle detected (confidence: {confidence:.2f})")

        if self.strategy == Strategy.STOP:
            self._handle_stop_strategy()
        elif self.strategy == Strategy.AVOID:
            self._handle_avoid_strategy()

    def _handle_stop_strategy(self):
        """STOP strategy: stop when obstacle detected"""
        self._send_motion_stop()
        self.state = NavigatorState.STOPPED
        LOG.info("STOP strategy: robot stopped due to obstacle")
        self._publish_state()

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

        self._publish_state()

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
            if "strategy" in config:
                try:
                    strategy = Strategy[config["strategy"].upper()]
                    self.set_strategy(strategy)
                except KeyError:
                    LOG.warning(f"Invalid strategy in config: {config['strategy']}")

            if "fwd_speed" in config:
                self.fwd_speed = float(config["fwd_speed"])
                LOG.info(f"Forward speed set to: {self.fwd_speed}")

            if "turn_speed" in config:
                self.turn_speed = float(config["turn_speed"])
                LOG.info(f"Turn speed set to: {self.turn_speed}")

            self._publish_state()

        else:
            LOG.warning(f"Unknown control action: {action}")

    def _publish_state(self):
        """Publish navigator state to bus"""
        state = {
            "active": self.active,
            "state": self.state.value,
            "strategy": self.strategy.value,
            "obstacle_present": self.obstacle_present,
            "ts": time.time(),
        }
        self.pub.publish(TOPIC_NAVIGATOR_STATE, state, add_ts=True)

    def run(self):
        """Main navigation loop"""
        LOG.info("Navigator main loop started")
        self._publish_state()

        try:
            while True:
                # Receive obstacle events from vision
                topic, payload = self.sub_obstacle.recv(timeout_ms=50)
                if topic and payload and topic == TOPIC_VISION_OBSTACLE:
                    present = payload.get("present", False)
                    confidence = payload.get("confidence", 0.0)
                    if self.active:
                        self._handle_obstacle(present, confidence)

                # Receive control commands from API
                topic, payload = self.sub_control.recv(timeout_ms=50)
                if topic and payload and topic == TOPIC_NAVIGATOR_CONTROL:
                    self._handle_control_command(payload)

                # Publish state periodically
                self._publish_state()

                time.sleep(0.1)

        except KeyboardInterrupt:
            LOG.info("Navigator interrupted by user")
        except Exception as e:
            LOG.exception(f"Error in navigator loop: {e}")
        finally:
            self.stop()
            self.sub_obstacle.close()
            self.sub_control.close()
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
