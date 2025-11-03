#!/usr/bin/env python3
import sys

import zmq

BUS_PUB_PORT = 5555
ZMQ_ADDR_PUB = f"tcp://127.0.0.1:{BUS_PUB_PORT}"


def main():
    ctx = zmq.Context()
    socket = ctx.socket(zmq.SUB)
    socket.connect(ZMQ_ADDR_PUB)
    socket.setsockopt_string(zmq.SUBSCRIBE, "vision.tracking.offset")
    socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1s timeout

    print(f"Listening on {ZMQ_ADDR_PUB} for topic ‘vision.tracking.offset’ …")

    try:
        while True:
            try:
                topic = socket.recv_string()
                msg = socket.recv_json()
                print(f"{topic} → {msg}")
            except zmq.Again:
                # timeout expired: no message received
                continue
            except KeyboardInterrupt:
                print("\nInterrupted by user, shutting down.")
                break
            except Exception as e:
                print(f"Error receiving message: {e}", file=sys.stderr)
    finally:
        socket.close()
        ctx.term()


if __name__ == "__main__":
    main()
