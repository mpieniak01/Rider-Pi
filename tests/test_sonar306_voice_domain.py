"""Selected profile, validator, runner and keyboard boundaries without external I/O."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.voice import cli_commands, config_loader, domain_worker, kws, svc_stream_runner, voice_logging


class WorkerBaseError(BaseException):
    pass


@pytest.mark.parametrize("error_type", [RuntimeError, SystemExit, KeyboardInterrupt, WorkerBaseError])
def test_runner_propagates_exact_worker_exception_without_losing_base_errors(error_type):
    error = error_type("worker failed")

    async def failure():
        raise error

    coroutine = failure()
    with pytest.raises(error_type) as caught:
        svc_stream_runner._run_coro_in_thread(coroutine)
    assert caught.value is error


def test_runner_preserves_native_asyncio_cancellation_and_completes_cleanup():
    direct_cleanup, worker_cleanup = [], []

    async def cancelled(cleanup):
        try:
            raise asyncio.CancelledError("worker failed")
        finally:
            await asyncio.sleep(0)
            cleanup.append(asyncio.get_running_loop())

    direct_coroutine = cancelled(direct_cleanup)
    with pytest.raises(asyncio.CancelledError) as direct:
        asyncio.run(direct_coroutine)
    worker_coroutine = cancelled(worker_cleanup)
    with pytest.raises(asyncio.CancelledError) as worker:
        svc_stream_runner._run_coro_in_thread(worker_coroutine)
    # Python 3.9 creates a new cancellation exception; its identity/message need
    # not match the raised instance. The runner must preserve native run behavior.
    assert type(worker.value) is type(direct.value)
    assert worker.value.args == direct.value.args
    assert len(direct_cleanup) == 1
    assert len(worker_cleanup) == 1
    assert direct_cleanup[0].is_closed()
    assert worker_cleanup[0].is_closed()


@pytest.mark.asyncio
async def test_runner_uses_a_different_loop_and_returns_coroutine_result():
    main_loop = asyncio.get_running_loop()

    async def result():
        assert asyncio.get_running_loop() is not main_loop
        return {"result": 42}

    assert svc_stream_runner._run_coro_in_thread(result()) == {"result": 42}


@pytest.mark.parametrize(
    "host,expected",
    [
        ("0.0.0.0", "127.0.0.1"),
        ("localhost", "127.0.0.1"),
        ("::", "[::1]"),
        ("[::]", "[::1]"),
        ("127.0.0.2", "127.0.0.2"),
        ("::1", "[::1]"),
    ],
)
def test_profile_chat_endpoint_preserves_loopback_ipv4_ipv6(monkeypatch, host, expected):
    monkeypatch.setattr(domain_worker, "worker_bind", lambda: (host, 8092))
    assert domain_worker._chat_endpoint() == f"http://{expected}:8092/api/chat"


@pytest.mark.parametrize("stale,loaded,ready", [(False, True, True), (True, True, False), (False, False, False)])
def test_profile_confirmation_requires_fresh_loaded_worker(monkeypatch, stale, loaded, ready):
    monkeypatch.setattr(domain_worker, "availability", lambda domains: {"ready": True, "domains": sorted(domains)})
    observed = {"stale": stale, "capabilities": {"asr": {"ready": True, "model_loaded": loaded}}}
    result = domain_worker._observed_profile({"asr"}, lambda: observed)
    assert result['ready'] is ready
    assert result['worker'] is observed


@pytest.mark.parametrize("missing_domain", [True, False])
def test_validator_required_sections_and_unknown_policy_stay_independent(missing_domain):
    schema = config_loader.ConfigSchema()
    schema.sections["custom"] = {"needed": config_loader.FieldSchema(type=str, required=True)}
    loader = config_loader.ConfigLoader(schema=schema, lenient=True)
    data = {"compat": {"allow_unknown_keys": True}, "unrecognized": {"value": 1}}
    if not missing_domain:
        data["custom"] = {"needed": "value"}
    loader._validate(data)
    assert not loader.unknown_keys
    assert loader.validation_errors == (["Missing required field 'custom.needed'"] if missing_domain else [])


def test_validator_retains_error_order_and_clears_previous_failures():
    loader = config_loader.ConfigLoader(lenient=True)
    loader._validate(
        {"capture": {"channels": 3, "sample_rate": 8000}, "playback": {"volume": -1}, "hotword": {"engine": "invalid"}}
    )
    assert [error.split("'")[1] for error in loader.validation_errors] == [
        "capture.channels",
        "capture.sample_rate",
        "playback.volume",
        "hotword.engine",
    ]
    loader._validate({"capture": {"channels": 1, "sample_rate": 16000}})
    assert not loader.validation_errors
    assert not loader.unknown_keys


@pytest.mark.parametrize("tail", [0, 2, 10])
def test_secret_masking_retains_direct_nested_and_env_handling(monkeypatch, tail):
    monkeypatch.setenv("VOICE_TEST_FAKE_SECRET", "abcdef")
    data = {"token": "abcdef", "stream": {"auth": "abcdef", "source": "env:VOICE_TEST_FAKE_SECRET"}, "plain": 3}
    masked = config_loader.mask_secrets(data, keep_tail=tail)
    suffix = "abcdef"[-tail:] if tail > 0 else ""
    expected = "*" * max(0, 6 - tail) + suffix
    assert masked["token"] == masked["stream"]["auth"] == expected
    assert masked["stream"]["source"] == "env:" + expected
    assert data['token'] == 'abcdef'
    assert masked['plain'] == 3


def test_command_override_replacement_order_and_conservative_numeric_values():
    args = SimpleNamespace(
        mode="stream",
        tts=["voice=ash"],
        capture=["gain=-1", "rate=16.0", "enabled=true"],
        hotword="off",
        ding="on",
        lang="pl",
    )
    result = cli_commands._build_overrides(args)
    assert result["asr"] == {"transport": "realtime", "language": "pl"}
    assert result["tts"] == {"voice": "ash"}
    assert result["capture"] == {"gain": "-1", "rate": 16.0, "enabled": True}
    assert result["service"] == {"hotword_enabled": False}
    assert result["playback"] == {"ding": {"enabled": True}}


@pytest.mark.parametrize("line", ["\n", "", "text\n"])
def test_passive_keyboard_retains_pipe_readline_trigger(monkeypatch, line):
    detector = object.__new__(kws.HotwordDetector)
    detector._stop = threading.Event()
    detector.logger = Mock()
    stdin = SimpleNamespace(isatty=lambda: False, readline=lambda: line)
    monkeypatch.setattr(kws, "sys", SimpleNamespace(stdin=stdin))
    monkeypatch.setattr(kws, "select", SimpleNamespace(select=lambda *_args: ([stdin], [], [])))
    assert detector.wait_ptt(timeout=1)
    detector.logger.event.assert_called_once_with("hotword.trigger", engine="ptt-passive")


def test_porcupine_accumulates_partial_frame_and_keeps_signed_samples(monkeypatch):
    detector = object.__new__(kws.HotwordDetector)
    detector._stop = threading.Event()
    detector.logger = Mock()
    detector._porcupine = SimpleNamespace(frame_length=2, process=Mock(return_value=0))
    reader = Mock(side_effect=[b"\x00", b"\x80\xff\x7f"])
    monkeypatch.setattr(kws, "_make_reader", lambda _capture: reader)
    assert detector._wait_porcupine(object(), None, 0)
    detector._porcupine.process.assert_called_once_with([-32768, 32767])
    detector.logger.event.assert_called_once_with("hotword.trigger", engine="porcupine")


def test_json_logger_uses_utc_and_retains_millisecond_z_timestamp():
    record = logging.LogRecord("voice.test", logging.INFO, __file__, 1, "hello", (), None)
    record.created = 0.123456
    payload = json.loads(voice_logging.JsonLogFormatter().format(record))
    assert payload["ts"] == "1970-01-01T00:00:00.123Z"
    assert payload["msg"] == "hello"
