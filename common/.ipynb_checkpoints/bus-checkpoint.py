#!/usr/bin/env python3
import json, time, zmq
XPUB_ENDPOINT = "tcp://127.0.0.1:5556"  # SUB łączy się TU
XSUB_ENDPOINT = "tcp://127.0.0.1:5555"  # PUB łączy się TU
def now_ts() -> float: return time.time()
class BusPub:
    def __init__(self, topic_prefix=""):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.PUB)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(XSUB_ENDPOINT)
        self.prefix = topic_prefix.rstrip(".")
    def publish(self, topic: str, payload: dict):
        t = f"{self.prefix}.{topic}" if self.prefix else topic
        msg = json.dumps(payload, ensure_ascii=False)
        self.sock.send_multipart([t.encode("utf-8"), msg.encode("utf-8")])
class BusSub:
    def __init__(self, topics):
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.connect(XPUB_ENDPOINT)
        if isinstance(topics, str): topics = [topics]
        for t in topics:
            self.sock.setsockopt(zmq.SUBSCRIBE, t.encode("utf-8"))
    def recv(self, timeout_ms: int = None):
        if timeout_ms is not None:
            if self.sock.poll(timeout=timeout_ms) <= 0: return None, None
        topic, data = self.sock.recv_multipart()
        return topic.decode("utf-8"), json.loads(data.decode("utf-8"))
