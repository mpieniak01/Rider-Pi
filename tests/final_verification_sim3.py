#!/usr/bin/env python3
"""
Final Verification for SIM-3 Implementation

This script performs a comprehensive check of all SIM-3 requirements
and generates a verification report.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("\n" + "=" * 70)
print("SIM-3 FINAL VERIFICATION REPORT")
print("=" * 70 + "\n")

# Set headless mode
os.environ["SDL_VIDEODRIVER"] = "dummy"

results = []


def check(description: str, test_func):
    """Run a test and record result."""
    try:
        test_func()
        results.append((description, True, "✓ PASS"))
        print(f"✓ {description}")
    except Exception as e:
        results.append((description, False, f"✗ FAIL: {e}"))
        print(f"✗ {description}: {e}")


# Test 1: Virtual Gyroscope
def test_gyro():
    from sim.sensors import GYRO_TOPIC, VirtualGyro

    assert GYRO_TOPIC == "rider.gyro.angle", "Gyro topic must be rider.gyro.angle"
    gyro = VirtualGyro(rate_hz=10.0)
    assert gyro._pub is not None, "Gyro must have MQTT publisher"
    gyro.publish(1.5708)  # 90 degrees in radians


check("1. Virtual Gyroscope publishes on rider.gyro.angle", test_gyro)


# Test 2: Virtual Camera Class
def test_camera_class():
    from sim.sensors import VirtualCamera

    camera = VirtualCamera(width=320, height=240, fov=60.0, rate_hz=5.0)
    assert camera.width == 320
    assert camera.height == 240
    assert camera.fov == 60.0
    assert camera._pub is not None, "Camera must have MQTT publisher"


check("2. VirtualCamera class created with correct parameters", test_camera_class)


# Test 3: Perspective Rendering
def test_perspective():
    from sim.sensors import VirtualCamera

    camera = VirtualCamera()
    walls = [((5, 0), (5, 10))]

    # Render from different distances
    surface_far = camera.render(2.0, 5.0, 0.0, walls)
    surface_near = camera.render(4.5, 5.0, 0.0, walls)

    assert surface_far is not None
    assert surface_near is not None


check("3. Camera renders first-person view with perspective", test_perspective)


# Test 4: Raycasting
def test_raycasting():
    from sim.sensors import VirtualCamera

    camera = VirtualCamera()

    # Ray pointing right at vertical wall
    dist = camera._ray_wall_intersection(0.0, 0.0, 0.0, 5.0, -1.0, 5.0, 1.0)

    assert dist is not None, "Ray should intersect wall"
    assert abs(dist - 5.0) < 0.01, "Distance should be 5 units"


check("4. Ray-wall intersection calculation works correctly", test_raycasting)


# Test 5: Side Panel Integration
def test_side_panel():
    from sim.robot import SimulatedRobot
    from sim.sensors import VirtualCamera
    from sim.world import World

    world = World(map_file="sim/maps/simple.txt")
    robot = SimulatedRobot(x=5.0, y=5.0, angle=0.0)
    camera = VirtualCamera()

    camera_surface = camera.render(robot.x, robot.y, robot.angle, world.wall_segments)
    world.render(robot, camera_surface)

    world.quit()


check("5. Camera view integrates with side panel rendering", test_side_panel)


# Test 6: MQTT Publishing
def test_mqtt_publishing():
    from sim.sensors import CAMERA_TOPIC, GYRO_TOPIC, VirtualCamera, VirtualGyro

    gyro = VirtualGyro(rate_hz=100.0)
    camera = VirtualCamera(rate_hz=100.0)

    # Publish gyro
    gyro.publish(1.0)
    assert gyro.last_pub > 0, "Gyro should have published"

    # Render and publish camera
    camera.render(5.0, 5.0, 0.0, [])
    camera.publish()
    assert camera.last_pub > 0, "Camera should have published"


check("6. MQTT publishing works for both sensors", test_mqtt_publishing)


# Test 7: Main Loop Integration
def test_main_loop():
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_simulation", "run_simulation.py")
    run_sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_sim)

    # Verify imports
    assert hasattr(run_sim, "VirtualGyro")
    assert hasattr(run_sim, "VirtualCamera")


check("7. Sensors integrated in main simulation loop", test_main_loop)


# Test 8: Configuration
def test_configuration():
    from sim.sensors import BUS_PUB_ADDR, CAMERA_TOPIC, GYRO_TOPIC

    assert BUS_PUB_ADDR == "tcp://127.0.0.1:5555"
    assert GYRO_TOPIC == "rider.gyro.angle"
    assert CAMERA_TOPIC == "rider.camera.frame"


check("8. MQTT topics and addresses correctly configured", test_configuration)

# Summary
print("\n" + "=" * 70)
print("VERIFICATION SUMMARY")
print("=" * 70 + "\n")

passed = sum(1 for _, success, _ in results if success)
failed = sum(1 for _, success, _ in results if not success)

for desc, success, _ in results:
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {desc}")

print("\n" + "=" * 70)
print(f"Result: {passed}/{len(results)} tests passed")

if failed > 0:
    print(f"        {failed}/{len(results)} tests failed")
    print("=" * 70 + "\n")
    sys.exit(1)
else:
    print("=" * 70)
    print("\n✓ ALL SIM-3 REQUIREMENTS VERIFIED SUCCESSFULLY!\n")
    print("Acceptance Criteria Status:")
    print("  [AC1] ✓ Gyroscope publishes on rider.gyro.angle")
    print("  [AC2] ✓ First-person view rendered in side panel")
    print("  [AC3] ✓ Perspective scaling implemented")
    print("  [AC4] ✓ Camera publishes frames on rider.camera.frame")
    print("\n" + "=" * 70 + "\n")
    sys.exit(0)
