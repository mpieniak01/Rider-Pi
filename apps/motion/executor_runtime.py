"""Process lifecycle for the sole motion executor; no permission policy here."""

import signal
import time


def run(executor_factory, sub_topics, command_topics) -> int:
    from common import bus

    executor = None
    sub = pub = None
    stopping = False

    def stop_signal(_signum, _frame):
        nonlocal stopping
        stopping = True
        if executor is not None:
            executor.gate.disarm("process_signal")
            executor.controller.stop()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop_signal)
    try:
        sub, pub = bus.BusSub(sub_topics), bus.BusPub()
        executor = executor_factory(publisher=pub)
        previous = time.monotonic()
        while not stopping:
            topic, payload = sub.recv(timeout_ms=20)
            messages = []
            if topic in command_topics:
                messages.append((topic, payload))
            # Drain a bounded burst before executing a goal. Any STOP wins this
            # burst and invalidates earlier or later queued generation tokens.
            for _ in range(63):
                topic, payload = sub.recv(timeout_ms=0)
                if topic is None:
                    break
                if topic in command_topics:
                    messages.append((topic, payload))
            executor.process_batch(messages)
            now = time.monotonic()
            executor.tick(now - previous)
            previous = now
            executor.poll_sensors()
        return 0
    finally:
        if executor is not None:
            executor.close()
        if sub is not None:
            sub.close()
        if pub is not None:
            pub.close()
