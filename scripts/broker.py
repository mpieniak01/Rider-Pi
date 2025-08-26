#!/usr/bin/env python3
"""
ZeroMQ broker XSUB↔XPUB
- PUB-y (demo, scripts/pub.py) łączą się do tcp://*:5555
- SUB-y (apps/motion) łączą się do tcp://*:5556
"""

import os
import signal
import logging

import zmq

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("broker")

FRONT_ADDR = os.getenv("BROKER_FRONTEND_ADDR", "tcp://*:5555")  # XSUB (od publisherów)
BACK_ADDR  = os.getenv("BROKER_BACKEND_ADDR",  "tcp://*:5556")  # XPUB (do subscriberów)

def main():
    ctx = zmq.Context.instance()
    frontend = ctx.socket(zmq.XSUB)
    backend  = ctx.socket(zmq.XPUB)

    # (opcjonalnie) pokaż SUBSCRIBE/UNSUB na XPUB:
    # backend.setsockopt(zmq.XPUB_VERBOSE, 1)

    frontend.bind(FRONT_ADDR)
    backend.bind(BACK_ADDR)

    LOG.info(f"Broker XSUB {FRONT_ADDR}  <->  XPUB {BACK_ADDR}")

    stop = [False]
    def _sig(_a,_b): stop[0] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        zmq.proxy(frontend, backend)
    except KeyboardInterrupt:
        pass
    finally:
        LOG.info("Broker: shutting down")
        try:
            frontend.close(0)
            backend.close(0)
        finally:
            ctx.term()

if __name__ == "__main__":
    main()
