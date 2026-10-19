"""Shared frame subscription modes use fake ZMQ; no camera or physical BUS."""

import json
from types import SimpleNamespace

import pytest

from common import frame_stream


class Again(Exception):
    pass


class Socket:
    def __init__(self, queue):
        self.queue = queue
        self.options = []
        self.reads = 0
        self.closed = False

    def setsockopt(self, key, value):
        self.options.append((key, value))

    def connect(self, _):
        pass

    def recv_multipart(self, *_):
        self.reads += 1
        if not self.queue:
            raise Again()
        return self.queue.pop(0)

    def close(self):
        self.closed = True


def message(index=1, *, data=b'\xff\xd8\xffjpeg', metadata=None):
    return [b'camera.frame.raw', json.dumps(metadata or {'captured_at': 990 + index, 'id': index}).encode(), data]


def create(monkeypatch, queue, **options):
    sock = Socket(queue)

    class Poller:
        def register(self, *_):
            pass

        def unregister(self, *_):
            pass

        def poll(self, _):
            return [(sock, 1)] if sock.queue else []

    zmq = SimpleNamespace(
        SUB=1,
        LINGER=2,
        RCVHWM=3,
        SUBSCRIBE=4,
        NOBLOCK=5,
        POLLIN=6,
        Again=Again,
        Poller=Poller,
        Context=SimpleNamespace(instance=lambda: SimpleNamespace(socket=lambda _: sock)),
    )
    monkeypatch.setattr(frame_stream, 'zmq', zmq)
    client = frame_stream.FrameStreamClient('fixture://camera', 'camera.frame.raw', **options)
    return client, sock


def test_encoded_mode_is_dependency_lazy_and_byte_exact(monkeypatch):
    imports = []
    monkeypatch.setattr(frame_stream, 'cv2', None)
    monkeypatch.setattr(frame_stream, 'np', None)
    monkeypatch.setattr(frame_stream.importlib, 'import_module', lambda name: imports.append(name) or pytest.fail(name))
    data = b'\xff\xd8\xffjpeg'
    client, sock = create(monkeypatch, [message(data=data)], encoded=True)
    assert client.recv(0) is data
    assert client.metadata['observed_at'] == 991
    assert imports == []
    client.close()
    assert sock.closed


def test_encoded_cache_preserves_source_time_and_immutable_payload(monkeypatch):
    data = b'\xff\xd8\xffjpeg'
    client, _ = create(monkeypatch, [message(data=data)], encoded=True, return_last=True, copy_frame=True)
    assert client.recv(0) is data
    assert client.recv(0) is data
    assert client.last_frame is data
    assert client.metadata['observed_at'] == 991
    client.close()


@pytest.mark.parametrize(
    'bad',
    [
        [b'camera.frame.raw', b'not-json', b'\xff\xd8\xffjpeg'],
        [b'camera.frame.raw', b'[]', b'\xff\xd8\xffjpeg'],
        [b'camera.frame.raw', b'{}', b'not-image'],
        [b'wrong-topic', b'{}', b'\xff\xd8\xffjpeg'],
        [b'camera.frame.raw', b'{}'],
        [b'camera.frame.raw', b'x' * 8193, b'\xff\xd8\xffjpeg'],
        [b'camera.frame.raw', b'{}', b'\xff\xd8\xff' + b'x' * (2 * 1024 * 1024)],
    ],
)
def test_malformed_messages_never_replace_last_valid_metadata(monkeypatch, bad):
    client, sock = create(monkeypatch, [message()], encoded=True, return_last=True)
    previous = client.recv(0)
    metadata = client.metadata
    sock.queue.append(bad)
    assert client.recv(0) == previous
    assert client.metadata == metadata
    client.close()


def test_latest_uses_latest_valid_candidate_with_bounded_drain(monkeypatch):
    queue = [message(index) for index in range(20)]
    client, sock = create(monkeypatch, queue, encoded=True, latest=True, max_pending=2)
    assert client.recv(0) is not None
    assert client.metadata['id'] == 16
    assert sock.reads == 17
    assert len(sock.queue) == 3
    assert (3, 2) in sock.options
    client.close()


def test_invalid_latest_message_does_not_drop_new_valid_candidate(monkeypatch):
    queue = [message(1), message(2), [b'camera.frame.raw', b'not-json', b'bad']]
    client, _ = create(monkeypatch, queue, encoded=True, latest=True)
    assert client.recv(0) is not None
    assert client.metadata['id'] == 2
    client.close()


@pytest.mark.parametrize('size', [0, 17, True, '2'])
def test_invalid_queue_bound_does_not_create_socket(monkeypatch, size):
    called = []
    monkeypatch.setattr(
        frame_stream,
        'zmq',
        SimpleNamespace(
            Context=SimpleNamespace(instance=lambda: called.append('socket')),
        ),
    )
    with pytest.raises(ValueError):
        frame_stream.FrameStreamClient(
            'fixture://camera', 'camera.frame.raw', encoded=True, latest=True, max_pending=size
        )
    assert not called


def test_decoded_latest_decodes_once_and_bad_decode_keeps_metadata(monkeypatch):
    calls = []

    class Frame:
        def copy(self):
            return self

    frame = Frame()
    monkeypatch.setattr(frame_stream, 'np', SimpleNamespace(frombuffer=lambda data, **_: data, uint8=1))
    monkeypatch.setattr(
        frame_stream,
        'cv2',
        SimpleNamespace(
            imdecode=lambda data, *_: calls.append(data) or frame,
            IMREAD_COLOR=1,
        ),
    )
    client, sock = create(monkeypatch, [message(1), message(2)], latest=True, return_last=True)
    assert client.recv(0) is frame
    assert len(calls) == 1
    assert client.metadata['id'] == 2
    monkeypatch.setattr(frame_stream.cv2, 'imdecode', lambda *a: None)
    sock.queue.append(message(3))
    assert client.recv(0) is frame
    assert client.metadata['id'] == 2
    client.close()


def test_oversized_decoded_payload_is_rejected_before_decoder(monkeypatch):
    monkeypatch.setattr(frame_stream, 'np', SimpleNamespace(frombuffer=lambda **_: pytest.fail('array decoded')))
    monkeypatch.setattr(frame_stream, 'cv2', SimpleNamespace(imdecode=lambda **_: pytest.fail('image decoded')))
    client, _ = create(monkeypatch, [message(data=b'x' * (2 * 1024 * 1024 + 1))])
    assert client.recv(0) is None
    assert client.metadata == {}
    client.close()
