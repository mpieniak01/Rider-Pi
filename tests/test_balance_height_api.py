#!/usr/bin/env python3
"""
Test balance and height control implementation without requiring Flask.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_bus_topics_defined():
    """Test that bus topics are defined in common.bus."""
    # Check the file directly since zmq might not be installed
    bus_file = project_root / "common" / "bus.py"
    with open(bus_file) as f:
        content = f.read()

    assert 'TOPIC_MOTION_BALANCE = "cmd.balance"' in content, "Balance topic should be defined"
    assert 'TOPIC_MOTION_HEIGHT = "cmd.height"' in content, "Height topic should be defined"
    return True


def test_api_file_structure():
    """Test that control_api.py has the expected functions."""
    import ast

    api_file = project_root / "services" / "api_core" / "control_api.py"
    with open(api_file) as f:
        tree = ast.parse(f.read())

    function_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]

    assert "api_balance" in function_names, "api_balance function should exist"
    assert "api_height" in function_names, "api_height function should exist"
    return True


def test_motion_bridge_subscriptions():
    """Test that motion_bridge.py subscribes to balance and height topics."""
    bridge_file = project_root / "services" / "motion_bridge.py"
    with open(bridge_file) as f:
        content = f.read()

    assert '"cmd.balance"' in content, "motion_bridge should subscribe to cmd.balance"
    assert '"cmd.height"' in content, "motion_bridge should subscribe to cmd.height"
    return True


def test_api_server_routes():
    """Test that api_server.py registers the new routes."""
    server_file = project_root / "services" / "api_server.py"
    with open(server_file) as f:
        content = f.read()

    assert 'control_api' in content, "control_api should be imported"
    assert '/api/control/balance' in content, "balance endpoint should be registered"
    assert '/api/control/height' in content, "height endpoint should be registered"
    return True


def test_html_controls_present():
    """Test that control.html contains the new UI controls."""
    html_file = project_root / "web" / "control.html"
    with open(html_file) as f:
        content = f.read()

    assert 'balanceToggle' in content, "Balance toggle should be in HTML"
    assert 'heightSlider' in content, "Height slider should be in HTML"
    assert 'sendBalance' in content, "sendBalance function should be in JavaScript"
    assert 'sendHeight' in content, "sendHeight function should be in JavaScript"
    assert '/api/control/balance' in content, "Balance API endpoint should be called"
    assert '/api/control/height' in content, "Height API endpoint should be called"
    return True


if __name__ == "__main__":
    tests = [
        ("Bus topics defined", test_bus_topics_defined),
        ("API file structure", test_api_file_structure),
        ("Motion bridge subscriptions", test_motion_bridge_subscriptions),
        ("API server routes", test_api_server_routes),
        ("HTML controls present", test_html_controls_present),
    ]

    print("Testing balance and height control implementation...\n")

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            print(f"✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {name}: Unexpected error: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")

    if failed > 0:
        sys.exit(1)

    print("\nAll tests passed!")
