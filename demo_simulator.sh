#!/bin/bash
# Demo script for Rider-Pi 2D Simulator
# 
# This script demonstrates:
# 1. Starting the ZMQ broker
# 2. Running the simulator
# 3. Sending control commands
#
# Usage: ./demo_simulator.sh

set -e

echo "======================================"
echo "Rider-Pi 2D Simulator Demo"
echo "======================================"
echo ""

# Check dependencies
echo "Checking dependencies..."
python3 -c "import pygame" 2>/dev/null || {
    echo "ERROR: pygame not installed. Run: pip install pygame"
    exit 1
}

python3 -c "import zmq" 2>/dev/null || {
    echo "ERROR: pyzmq not installed. Run: pip install pyzmq"
    exit 1
}

echo "✓ Dependencies OK"
echo ""

# Start broker in background
echo "Starting ZMQ broker..."
python3 services/broker.py &
BROKER_PID=$!
sleep 1

# Check if broker started successfully
if ! kill -0 $BROKER_PID 2>/dev/null; then
    echo "⚠ Broker may already be running or failed to start"
    BROKER_PID=""
else
    echo "✓ Broker started (PID: $BROKER_PID)"
fi

# Cleanup function
cleanup() {
    echo ""
    echo "Cleaning up..."
    if [ ! -z "$BROKER_PID" ]; then
        kill $BROKER_PID 2>/dev/null || true
        echo "✓ Broker stopped"
    fi
}

trap cleanup EXIT

echo ""
echo "======================================"
echo "Running simulator tests..."
echo "======================================"
echo ""

# Run tests
python3 tests/test_simulator_robot.py
echo ""
python3 tests/test_simulator_mqtt.py

echo ""
echo "======================================"
echo "✓ All tests passed!"
echo "======================================"
echo ""
echo "To run the simulator manually:"
echo "  1. Start broker:    python3 services/broker.py"
echo "  2. Start simulator: python3 run_simulation.py"
echo "  3. Control robot:   python3 tools/sim_keyboard_control.py"
echo ""
echo "Or send commands directly:"
echo "  python3 tools/pub.py motion '{\"type\":\"drive\",\"lx\":1.0,\"az\":0.0}'"
echo "  python3 tools/pub.py motion '{\"type\":\"stop\"}'"
echo ""
