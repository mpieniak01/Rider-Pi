"""Preparation uses its total deadline across legal delayed HTTP phases."""

from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_camera_pipeline_prepare import environment, publish  # noqa: F401

from apps.compute import navigation, stream_prepare


@contextlib.contextmanager
def delayed_status(producer, *, headers_delay=0, body_delay=0):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            calls.append(self.path)
            time.sleep(headers_delay)
            source = publish(producer)
            body = json.dumps({"stream": {"ready": True, "latest_source": source}}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                time.sleep(body_delay)
                self.wfile.write(body)
            except OSError:
                pass  # The bounded preparation client has already closed.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_legal_slow_http_warmup_can_use_remaining_two_second_budget(environment):
    producer, selection, _ = environment
    publish(producer)
    with delayed_status(producer, headers_delay=0.65) as (url, calls):
        started = time.monotonic()
        stream = stream_prepare.prepare_stream(selection=dict(selection, url=url))
        elapsed = time.monotonic() - started
        assert stream["ready"] is True and stream["latest_source"]["camera_session"] == producer.session
        assert 0.6 < elapsed < 2.0 and len(calls) == 1


def test_preparation_timeout_is_specific_and_does_not_retry_http(environment):
    producer, selection, _ = environment
    publish(producer)
    with delayed_status(producer, headers_delay=0.5) as (url, calls):
        started = time.monotonic()
        with pytest.raises(navigation.ComputeError) as failure:
            stream_prepare.prepare_stream(selection=dict(selection, url=url), timeout_s=0.15)
        assert failure.value.code == "navigation_stream_prepare_timeout" and failure.value.status == 504
        assert time.monotonic() - started < 0.4 and len(calls) == 1


def test_response_body_receives_only_budget_remaining_after_headers(environment):
    producer, selection, _ = environment
    publish(producer)
    with delayed_status(producer, headers_delay=0.3, body_delay=0.75) as (url, calls):
        started = time.monotonic()
        with pytest.raises(navigation.ComputeError, match="navigation_stream_prepare_timeout"):
            stream_prepare.prepare_stream(selection=dict(selection, url=url), timeout_s=0.7)
        assert 0.6 < time.monotonic() - started < 0.95 and len(calls) == 1
