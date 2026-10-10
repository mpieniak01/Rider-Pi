#!/usr/bin/env python3
"""
Unit tests for Navigator module (Rekonesans mode Stage 1)
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from apps.navigator.main import Navigator, NavigatorState, Strategy


class TestNavigator(unittest.TestCase):
    """Test Navigator functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Mock the bus connections
        self.bus_sub_patch = patch("apps.navigator.main.BusSub")
        self.bus_pub_patch = patch("apps.navigator.main.BusPub")

        self.mock_sub = self.bus_sub_patch.start()
        self.mock_pub = self.bus_pub_patch.start()

        # Create mock instances for multiple subscriptions
        self.mock_sub_obstacle = MagicMock()
        self.mock_sub_control = MagicMock()
        self.mock_pub_instance = MagicMock()

        # Return different instances for different topics
        def sub_side_effect(topic):
            if topic == "vision.obstacle":
                return self.mock_sub_obstacle
            elif topic == "navigator.control":
                return self.mock_sub_control
            return MagicMock()

        self.mock_sub.side_effect = sub_side_effect
        self.mock_pub.return_value = self.mock_pub_instance

        self.safety = {
            "contract_version": 1,
            "state": "ARMED",
            "ready": True,
            "hardware_ready": True,
            "can_move": True,
            "owner": "navigation",
            "generation": "operator-navigation",
            "last_seq": -1,
            "capabilities": {name: {"available": True, "stop_verified": True} for name in ("move", "turn")},
        }
        self.intent = {
            "generation": "operator-navigation",
            "request_id": "task-click",
            "seq": 0,
            "source": "manual",
            "ts": time.time(),
            "ttl_ms": 500,
        }
        self.sequence = 0
        self.extra_patches = []
        for target in (
            "services.safety_contract.read_status",
            "apps.safety.state.read_status",
            "apps.navigator.safety.read_status",
        ):
            item = patch(target, side_effect=lambda *args, **kwargs: dict(self.safety))
            item.start()
            self.extra_patches.append(item)
        for target in (
            "apps.navigator.motion.read_service_intent",
            "apps.safety.intent.read_service_intent",
            "apps.navigator.safety.read_service_intent",
        ):
            item = patch(
                target,
                create=True,
                side_effect=lambda unit, generation: dict(self.intent)
                if generation == self.intent["generation"]
                else None,
            )
            item.start()
            self.extra_patches.append(item)
        item = patch("apps.navigator.motion.write_intent_status", return_value=True)
        self.intent_writer = item.start()
        self.extra_patches.append(item)

    def envelope(self, **values):
        self.sequence += 1
        return {
            "source": "manual",
            "generation": self.safety["generation"],
            "seq": self.sequence,
            "ts": time.time(),
            "ttl_ms": 500,
            "request_id": f"operator-{self.sequence}",
            **values,
        }

    def authorized_start(self, nav):
        nav._handle_control_command(self.envelope(action="start", strategy=nav.strategy.value))

    def authorize(self, nav):
        self.assertTrue(nav._accept_motion_request(self.envelope()))

    def motion_calls(self, action):
        return [
            call
            for call in self.mock_pub_instance.publish.call_args_list
            if call[0][0] == "motion.command" and call[0][1].get("action") == action
        ]

    def tearDown(self):
        """Clean up patches"""
        for item in reversed(self.extra_patches):
            item.stop()
        self.bus_sub_patch.stop()
        self.bus_pub_patch.stop()

    def test_navigator_initialization(self):
        """Test navigator initializes with correct defaults"""
        nav = Navigator(strategy=Strategy.STOP)
        self.assertEqual(nav.strategy, Strategy.STOP)
        self.assertEqual(nav.state, NavigatorState.IDLE)
        self.assertFalse(nav.active)
        self.assertFalse(nav.obstacle_present)

    def test_navigator_start(self):
        """Test navigator starts correctly"""
        nav = Navigator(strategy=Strategy.STOP)
        self.authorized_start(nav)

        self.assertTrue(nav.active)
        self.assertEqual(nav.state, NavigatorState.EXPLORING)

        # Should publish state
        self.mock_pub_instance.publish.assert_called()

    def test_navigator_stop(self):
        """Test navigator stops correctly"""
        nav = Navigator(strategy=Strategy.STOP)
        self.authorized_start(nav)
        nav.stop()

        self.assertFalse(nav.active)
        self.assertEqual(nav.state, NavigatorState.STOPPED)

        # Should send stop command to motion
        calls = self.mock_pub_instance.publish.call_args_list
        motion_stop_calls = [c for c in calls if c[0][0] == "motion.command" and c[0][1].get("action") == "stop"]
        self.assertGreater(len(motion_stop_calls), 0)

    def test_strategy_change(self):
        """Test changing navigation strategy"""
        nav = Navigator(strategy=Strategy.STOP)
        self.assertEqual(nav.strategy, Strategy.STOP)

        nav.set_strategy(Strategy.AVOID)
        self.assertEqual(nav.strategy, Strategy.AVOID)

    def test_obstacle_detected_stop_strategy(self):
        """Test obstacle handling with STOP strategy"""
        nav = Navigator(strategy=Strategy.STOP)
        self.authorized_start(nav)

        # Simulate obstacle detection
        nav._handle_obstacle(present=True, confidence=0.8)

        self.assertEqual(nav.state, NavigatorState.STOPPED)
        self.assertTrue(nav.obstacle_present)

        # Should send stop command
        calls = self.mock_pub_instance.publish.call_args_list
        motion_stop_calls = [c for c in calls if c[0][0] == "motion.command" and c[0][1].get("action") == "stop"]
        self.assertGreater(len(motion_stop_calls), 0)

    def test_obstacle_cleared_requires_new_operator_request(self):
        """A cleared obstacle cannot restore the generation revoked by STOP."""
        nav = Navigator(strategy=Strategy.STOP)
        self.authorized_start(nav)

        # First detect obstacle
        nav._handle_obstacle(present=True, confidence=0.8)

        # STOP invalidates the bound generation; clearing data grants no consent.
        self.mock_pub_instance.publish.reset_mock()
        nav._handle_obstacle(present=False, confidence=0.0)

        self.assertFalse(nav.obstacle_present)
        self.assertEqual(nav.state, NavigatorState.STOPPED)
        self.assertFalse(nav.active)

        # Should send drive command
        calls = self.mock_pub_instance.publish.call_args_list
        motion_drive_calls = [c for c in calls if c[0][0] == "motion.command" and c[0][1].get("action") == "move"]
        self.assertEqual(len(motion_drive_calls), 0)

    def test_obstacle_detected_avoid_strategy(self):
        """Test obstacle handling with AVOID strategy"""
        nav = Navigator(strategy=Strategy.AVOID)
        self.authorized_start(nav)

        # Simulate obstacle detection
        nav._handle_obstacle(present=True, confidence=0.8)

        self.assertEqual(nav.state, NavigatorState.AVOIDING)
        self.assertTrue(nav.obstacle_present)

        # Should send turn command (az != 0)
        calls = self.mock_pub_instance.publish.call_args_list
        motion_turn_calls = [
            c
            for c in calls
            if c[0][0] == "motion.command" and c[0][1].get("action") == "move" and c[0][1].get("yaw", 0.0) != 0.0
        ]
        self.assertGreater(len(motion_turn_calls), 0)

    def test_send_motion_drive(self):
        """Test sending drive commands"""
        nav = Navigator()

        self.authorize(nav)
        nav._send_motion_drive(lx=0.3, az=0.0)

        command = self.motion_calls("move")[-1][0][1]
        self.assertEqual(command["vx"], 0.3)
        self.assertEqual(command["yaw"], 0.0)
        self.assertEqual(command["source"], "navigation")
        self.assertEqual(command["generation"], self.safety["generation"])
        self.assertLessEqual(command["duration"], 0.25)

    def test_send_motion_stop(self):
        """Test sending stop commands"""
        nav = Navigator()

        self.authorize(nav)
        nav._send_motion_stop()
        command = self.motion_calls("stop")[-1][0][1]
        self.assertEqual(command["source"], "navigation")

    def test_publish_state(self):
        """Test state publishing"""
        nav = Navigator(strategy=Strategy.AVOID)
        nav.active = True
        nav.state = NavigatorState.EXPLORING
        nav.state_changed = True  # Mark state as changed

        nav._publish_state()

        # Check that state was published
        calls = self.mock_pub_instance.publish.call_args_list
        state_calls = [c for c in calls if c[0][0] == "navigator.state"]
        self.assertGreater(len(state_calls), 0)

        # Verify state content
        state_payload = state_calls[-1][0][1]
        self.assertTrue(state_payload["active"])
        self.assertEqual(state_payload["state"], "exploring")
        self.assertEqual(state_payload["strategy"], "AVOID")

    def test_inactive_navigator_ignores_obstacles(self):
        """Test that inactive navigator doesn't react to obstacles"""
        nav = Navigator(strategy=Strategy.STOP)
        # Don't start the navigator

        initial_state = nav.state

        nav._handle_obstacle(present=True, confidence=0.8)

        # State should not change
        self.assertEqual(nav.state, initial_state)

    def test_avoid_cooldown(self):
        """Test that avoid strategy respects cooldown period"""
        nav = Navigator(strategy=Strategy.AVOID)
        self.authorized_start(nav)

        # First obstacle triggers avoid
        nav._handle_obstacle(present=True, confidence=0.8)
        first_avoid_ts = nav.last_avoid_ts

        # Immediate second obstacle should be ignored (cooldown)
        nav._handle_obstacle(present=True, confidence=0.8)
        second_avoid_ts = nav.last_avoid_ts

        # Timestamps should be the same (second call was in cooldown)
        self.assertEqual(first_avoid_ts, second_avoid_ts)

    def test_state_publish_on_change_only(self):
        """Test that state is only published when it changes"""
        nav = Navigator(strategy=Strategy.STOP)

        # Clear any initial publish calls
        self.mock_pub_instance.publish.reset_mock()

        # Call _publish_state without state change
        nav.state_changed = False
        nav._publish_state()

        # Should not publish
        state_calls = [c for c in self.mock_pub_instance.publish.call_args_list if c[0][0] == "navigator.state"]
        self.assertEqual(len(state_calls), 0)

        # Now mark state as changed
        nav.state_changed = True
        nav._publish_state()

        # Should publish
        state_calls = [c for c in self.mock_pub_instance.publish.call_args_list if c[0][0] == "navigator.state"]
        self.assertEqual(len(state_calls), 1)

    def test_state_publish_force_heartbeat(self):
        """Test that force=True publishes even without state change"""
        nav = Navigator(strategy=Strategy.STOP)

        # Clear any initial publish calls
        self.mock_pub_instance.publish.reset_mock()

        # Call _publish_state with force=True
        nav.state_changed = False
        nav._publish_state(force=True)

        # Should publish even without state change
        state_calls = [c for c in self.mock_pub_instance.publish.call_args_list if c[0][0] == "navigator.state"]
        self.assertEqual(len(state_calls), 1)

    def test_return_home_state_transition(self):
        """Test transition to RETURNING_HOME state"""
        nav = Navigator(strategy=Strategy.STOP)
        self.authorized_start(nav)  # Start in exploring mode

        # Trigger return to home
        nav._handle_return_home_start(self.envelope(action="return_home"))

        # Should transition to RETURNING_HOME state
        self.assertEqual(nav.state, NavigatorState.RETURNING_HOME)
        self.assertFalse(nav.active)  # No longer in autonomous exploration
        self.assertTrue(nav.waiting_for_map)

        # Should have published map request
        calls = self.mock_pub_instance.publish.call_args_list
        # Note: The actual topic is imported from bus, so we check for the publish call
        self.assertGreater(len([c for c in calls if "map" in str(c).lower()]), 0)

    def test_handle_robot_pose_update(self):
        """Test updating robot pose from odometry"""
        nav = Navigator()

        pose_payload = {"x": 1.5, "y": 2.3, "theta": 0.785}  # ~45 degrees
        nav._handle_robot_pose(pose_payload)

        self.assertAlmostEqual(nav.current_pose[0], 1.5)
        self.assertAlmostEqual(nav.current_pose[1], 2.3)
        self.assertAlmostEqual(nav.current_pose[2], 0.785)

    def test_path_following_waypoint_reached(self):
        """Test path following removes waypoint when reached"""
        nav = Navigator()
        self.authorize(nav)
        nav.state = NavigatorState.RETURNING_HOME
        nav.current_pose = (1.0, 1.0, 0.0)
        nav.current_path = [(1.05, 1.05), (2.0, 2.0)]  # First waypoint very close

        nav._update_path_following()

        # First waypoint should be removed since we're within tolerance
        self.assertEqual(len(nav.current_path), 1)
        self.assertEqual(nav.current_path[0], (2.0, 2.0))

    def test_path_following_goal_reached(self):
        """Test reaching final goal"""
        nav = Navigator()
        self.authorize(nav)
        nav.state = NavigatorState.RETURNING_HOME
        nav.goal_pose = (0.0, 0.0)
        nav.current_pose = (0.05, 0.05, 0.0)  # Very close to goal
        nav.current_path = []  # No more waypoints

        nav._update_path_following()

        # Should transition to IDLE
        self.assertEqual(nav.state, NavigatorState.IDLE)

        # Should send stop command
        calls = self.mock_pub_instance.publish.call_args_list
        motion_stop_calls = [c for c in calls if c[0][0] == "motion.command" and c[0][1].get("action") == "stop"]
        self.assertGreater(len(motion_stop_calls), 0)

    def test_start_without_fresh_operator_envelope_stays_inactive(self):
        nav = Navigator()
        nav._handle_control_command({"action": "start"})
        self.assertFalse(nav.active)
        self.assertEqual(self.motion_calls("move"), [])

    def test_new_process_cannot_resume_consumed_intent(self):
        nav = Navigator()
        self.intent_writer.return_value = False  # persistent claim belongs to previous process
        nav._consume_task_intent()
        self.assertFalse(nav.active)
        self.assertEqual(self.motion_calls("move"), [])

    def test_stale_generation_cannot_restart_navigation(self):
        nav = Navigator()
        stale = self.envelope(action="start")
        self.safety["generation"] = "new-operator-plan"
        nav._handle_control_command(stale)
        self.assertFalse(nav.active)
        self.assertEqual(self.motion_calls("move"), [])

    def test_expired_operator_request_is_denied(self):
        nav = Navigator()
        nav._handle_control_command(self.envelope(action="start", ts=time.time() - 2))
        self.assertFalse(nav.active)
        self.assertEqual(self.motion_calls("move"), [])

    def test_disarmed_configuration_does_not_activate_navigation(self):
        nav = Navigator()
        self.safety.update(state="DISARMED", can_move=False)
        nav._handle_control_command({"action": "config", "config": {"fwd_speed": 0.2, "strategy": "AVOID"}})
        self.assertEqual(nav.fwd_speed, 0.2)
        self.assertFalse(nav.active)
        self.assertEqual(self.motion_calls("move"), [])

    def test_armed_configuration_is_denied(self):
        nav = Navigator()
        initial = nav.fwd_speed
        nav._handle_control_command({"action": "config", "config": {"fwd_speed": 0.2}})
        self.assertEqual(nav.fwd_speed, initial)


if __name__ == "__main__":
    unittest.main()
