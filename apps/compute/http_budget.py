"""One monotonic HTTP budget, including fragmented headers/body (Python 3.9)."""

from __future__ import annotations

import functools
import http.client
import io
import socket
import time


class CaptureBudgetExpired(TimeoutError):
    """The current capture exhausted its budget; its POST must not be replayed."""


def remaining(deadline, clock):
    value = deadline - clock()
    if value <= 0:
        raise CaptureBudgetExpired("navigation_capture_deadline")
    return value


class _BudgetReader(io.RawIOBase):
    def __init__(self, raw, sock, deadline, clock):
        super().__init__()
        self.raw, self.sock, self.deadline, self.clock = raw, sock, deadline, clock

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(remaining(self.deadline, self.clock))
        try:
            count = self.raw.readinto(buffer)
        except (TimeoutError, socket.timeout):
            remaining(self.deadline, self.clock)
            raise
        remaining(self.deadline, self.clock)
        return count

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _BudgetSocket:
    def __init__(self, sock, deadline, clock):
        self.sock, self.deadline, self.clock = sock, deadline, clock

    def makefile(self, mode):
        raw = self.sock.makefile(mode, buffering=0)
        return io.BufferedReader(_BudgetReader(raw, self.sock, self.deadline, self.clock))


class _BudgetResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, deadline, clock, **kwargs):
        super().__init__(_BudgetSocket(sock, deadline, clock), *args, **kwargs)


def apply_http_budget(connection, deadline, clock=time.monotonic):
    timeout = remaining(deadline, clock)
    connection.timeout = timeout
    if connection.sock is not None:
        connection.sock.settimeout(timeout)
    connection.response_class = functools.partial(_BudgetResponse, deadline=deadline, clock=clock)
