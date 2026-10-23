"""HTTP upload and receive share one capture budget, with inert sockets."""

import http.client
import socket

import pytest

from apps.compute.http_budget import CaptureBudgetExpired, apply_http_budget


def test_headers_and_body_upload_cannot_each_spend_the_full_capture_budget():
    now, writes = [10.0], []

    class SlowSocket:
        def __init__(self):
            self.timeout = 1.0

        def settimeout(self, timeout):
            self.timeout = timeout

        def sendall(self, data):
            writes.append((len(data), self.timeout))
            spent = min(0.06, self.timeout)
            now[0] += spent
            if spent < 0.06:
                raise socket.timeout("fixture slow upload")

    connection = http.client.HTTPConnection("upload.fixture")
    connection.sock = SlowSocket()
    apply_http_budget(connection, 10.1, lambda: now[0])
    with pytest.raises(CaptureBudgetExpired):
        connection.request("POST", "/decision", body=b"fixture")
    assert len(writes) == 2
    assert writes[1][1] == pytest.approx(0.04)
    assert now[0] == pytest.approx(10.1)
