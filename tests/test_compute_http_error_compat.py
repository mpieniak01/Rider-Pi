"""HTTPError may have no file wrapper on supported older Python versions."""

from __future__ import annotations

import io
import urllib.error

import pytest

from apps.compute.stream_prepare import http_error_code


class BodylessLegacyHTTPError(urllib.error.HTTPError):
    def __init__(self, code):
        # Python3.9 HTTPError(fp=None) skips addinfourl initialization. The
        # inherited tempfile __getattr__ then raises KeyError("file").
        self.code, self.msg, self.hdrs, self.fp = code, "fixture", {}, None
        self.filename = "http://fixture"


@pytest.mark.parametrize("code", [429, 503])
def test_bodyless_http_error_does_not_delegate_diagnostic_or_stream_attributes(code):
    error = BodylessLegacyHTTPError(code)
    with pytest.raises(KeyError, match="file"):
        getattr(error, "missing_wrapper_attribute", None)
    assert http_error_code(error) == "http_" + str(code)
    assert http_error_code(error) == "http_" + str(code)
    assert vars(error)["rider_domain_code"] == "http_" + str(code)


def test_real_error_body_is_bounded_closed_and_diagnostic_cached():
    body = io.BytesIO(b'{"detail":{"code":"vision_frame_expired"}}')
    error = urllib.error.HTTPError("http://fixture", 409, "fixture", {}, body)
    assert http_error_code(error) == "vision_frame_expired"
    assert body.closed
    assert http_error_code(error) == "vision_frame_expired"
