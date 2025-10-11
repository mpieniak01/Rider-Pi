#!/bin/bash
# Demo script for Rider-Pi 2D Simulator
# This script demonstrates the complete workflow

set -e

echo "=== Rider-Pi 2D Simulator Demo ==="
echo ""

# Check dependencies
echo "[1/5] Checking dependencies..."
python3 -c "import pygame, zmq" 2>/dev/null && echo "  ✓ pygame and zmq installed" || {
    echo "  ✗ Missing dependencies. Install with: pip install pygame pyzmq"
    exit 1
}

# Start broker in background
echo "[2/5] Starting ZMQ broker..."
python3 services/broker.py &
BROKER_PID=$!
sleep 2
echo "  ✓ Broker running (PID: $BROKER_PID)"

# Start simulator in background (headless mode for demo)
echo "[3/5] Starting simulator..."
SDL_VIDEODRIVER=dummy python3 scripts/sim/run_simulation.py &
SIM_PID=$!
sleep 2
echo "  ✓ Simulator running (PID: $SIM_PID)"

# Send test commands
echo "[4/5] Sending control commands..."

# Monitor in background
timeout 10 python3 scripts/diag_bus-spy.py &
SPY_PID=$!

sleep 1

# Send some commands
python3 -c "
import zmq, json, time
ctx = zmq.Context.instance()
pub = ctx.socket(zmq.PUB)
pub.connect('tcp://127.0.0.1:5555')
time.sleep(0.3)

print('  → Sending forward command')
for _ in range(3):
    pub.send_multipart([b'motion', json.dumps({'type': 'drive', 'lx': 0.5, 'az': 0.0}).encode()])
    time.sleep(0.1)

time.sleep(1)
print('  → Sending rotation command')
for _ in range(3):
    pub.send_multipart([b'motion', json.dumps({'type': 'drive', 'lx': 0.0, 'az': 0.3}).encode()])
    time.sleep(0.1)

time.sleep(1)
print('  → Sending stop command')
for _ in range(3):
    pub.send_multipart([b'motion', json.dumps({'type': 'stop'}).encode()])
    time.sleep(0.1)

print('  ✓ Commands sent successfully')
"

sleep 2

# Cleanup
echo "[5/5] Cleaning up..."
kill $SPY_PID 2>/dev/null || true
kill $SIM_PID 2>/dev/null || true
kill $BROKER_PID 2>/dev/null || true
sleep 1
echo "  ✓ All processes stopped"

echo ""
echo "=== Demo Complete ==="
echo ""
echo "To run interactively:"
echo "  Terminal 1: python services/broker.py"
echo "  Terminal 2: python scripts/sim/run_simulation.py"
echo "  Terminal 3: python scripts/diag_bus-spy.py"
echo "  Terminal 4: python scripts/dev_send-cmd.py"
