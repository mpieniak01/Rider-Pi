"""PNG export boundaries; renderers are mocked and no animation or hardware runs."""

from __future__ import annotations

import os
import stat
from unittest.mock import Mock

import pytest

from services.api_core import face_api, face_exports
from services.api_server import app

PNG = b"\x89PNG\r\n\x1a\nmock-preview"


@pytest.fixture(params=["/face/render", "/api/draw/face", "/draw/face"])
def route(request):
    return request.param


@pytest.fixture
def export_dir(tmp_path, monkeypatch):
    directory = tmp_path / "exports"
    directory.mkdir(mode=0o700)
    monkeypatch.setenv("FACE_RENDER_DIR", str(directory))
    monkeypatch.setenv("FACE_LCD_ROTATE", "0")
    return directory


@pytest.fixture
def renderer(monkeypatch):
    render = Mock(return_value=PNG)
    monkeypatch.setattr(face_api, "_render_png_bytes", render)
    return render


@pytest.fixture
def client():
    return app.test_client()


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"] == code


@pytest.mark.parametrize(
    "output",
    [
        "../face.png",
        "nested/face.png",
        "./face.png",
        "face/../face.png",
        "face.jpg",
        "face.png.txt",
        "face.PNG",
        "other.png",
        "face_.png",
        "face_" + "a" * 101 + ".png",
        "face_unsafe name.png",
        "",
        None,
        False,
        123,
        [],
        {},
    ],
)
def test_invalid_output_is_rejected_before_rendering(client, route, export_dir, renderer, output):
    response = client.post(route, json={"out": output})

    assert_error(response, 400, "invalid_face_output")
    renderer.assert_not_called()
    assert list(export_dir.iterdir()) == []


@pytest.mark.parametrize("kind", ["outside", "sibling", "nested", "traversal"])
def test_absolute_output_cannot_escape_export_directory(client, route, export_dir, renderer, kind):
    if kind == "outside":
        output = export_dir.parent / "face.png"
    elif kind == "sibling":
        output = export_dir.with_name(export_dir.name + "-other") / "face.png"
    elif kind == "nested":
        output = export_dir / "nested" / "face.png"
    else:
        output = export_dir / ".." / "face.png"

    response = client.post(route, json={"out": str(output)})

    assert_error(response, 400, "invalid_face_output")
    renderer.assert_not_called()
    assert list(export_dir.iterdir()) == []
    assert not (export_dir.parent / "face.png").exists()


@pytest.mark.parametrize(
    "patch",
    [
        {"size": 15},
        {"size": 1025},
        {"size": "invalid"},
        {"size": None},
        {"size": []},
        {"rotate": -90},
        {"rotate": 45},
        {"rotate": 360},
        {"rotation": 1},
        {"rotate": "invalid"},
        {"rotate": None},
    ],
)
@pytest.mark.parametrize("preview", [False, True])
def test_invalid_dimensions_or_rotation_do_not_render(client, route, export_dir, renderer, patch, preview):
    payload = patch if preview else {"out": "face.png", **patch}
    response = client.post(route, json=payload, headers={"Accept": "image/png"} if preview else {})

    assert_error(response, 400, "invalid_face_preview")
    renderer.assert_not_called()
    assert list(export_dir.iterdir()) == []


@pytest.mark.parametrize("output", ["face.png", "face_api-1_A.png", "absolute"])
def test_approved_output_names_are_written_privately(client, route, export_dir, renderer, output):
    destination = export_dir / ("face_absolute.png" if output == "absolute" else output)
    request_output = str(destination) if output == "absolute" else output

    response = client.post(route, json={"out": request_output})

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert destination.read_bytes() == PNG
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(export_dir.iterdir()) == [destination]
    renderer.assert_called_once_with("neutral", 240)


@pytest.mark.parametrize("size", [16, 1024])
def test_in_memory_preview_keeps_size_boundaries_and_creates_no_file(client, route, export_dir, renderer, size):
    response = client.post(route, json={"size": size}, headers={"Accept": "image/png"})

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data == PNG
    renderer.assert_called_once_with("neutral", size)
    assert list(export_dir.iterdir()) == []


def test_existing_export_is_atomically_replaced_with_private_permissions(client, route, export_dir, renderer):
    destination = export_dir / "face.png"
    destination.write_bytes(b"previous PNG")
    destination.chmod(0o666)
    old_inode = destination.stat().st_ino

    response = client.post(route, json={"out": "face.png"})

    assert response.status_code == 200
    assert destination.read_bytes() == PNG
    assert destination.stat().st_ino != old_inode
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(export_dir.iterdir()) == [destination]


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_final_link_is_replaced_without_changing_outside_target(client, route, export_dir, renderer, link_kind):
    victim = export_dir.parent / "outside.txt"
    victim.write_bytes(b"outside must survive")
    destination = export_dir / "face.png"
    if link_kind == "symlink":
        destination.symlink_to(victim)
    else:
        os.link(victim, destination)

    response = client.post(route, json={"out": str(destination)})

    assert response.status_code == 200
    assert victim.read_bytes() == b"outside must survive"
    assert not destination.is_symlink()
    assert destination.read_bytes() == PNG
    assert destination.stat().st_ino != victim.stat().st_ino
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(export_dir.iterdir()) == [destination]


def test_symlink_export_directory_is_unavailable(client, route, export_dir, renderer, monkeypatch):
    outside = export_dir.parent / "outside"
    outside.mkdir()
    link = export_dir.parent / "linked-exports"
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("FACE_RENDER_DIR", str(link))

    response = client.post(route, json={"out": "face.png"})

    assert_error(response, 503, "face_export_unavailable")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("mode", [0o702, 0o720, 0o777])
def test_nonsticky_writable_export_directory_is_unavailable(client, route, export_dir, renderer, mode):
    export_dir.chmod(mode)

    response = client.post(route, json={"out": "face.png"})

    assert_error(response, 503, "face_export_unavailable")
    assert list(export_dir.iterdir()) == []


def test_untrusted_directory_owner_is_unavailable(client, route, export_dir, renderer, monkeypatch):
    real_fstat = os.fstat

    def untrusted_owner(descriptor):
        values = list(real_fstat(descriptor))
        values[4] = os.geteuid() + 1
        return os.stat_result(values)

    monkeypatch.setattr(face_exports.os, "fstat", untrusted_owner)

    response = client.post(route, json={"out": "face.png"})

    assert_error(response, 503, "face_export_unavailable")
    assert list(export_dir.iterdir()) == []


def test_failed_replace_preserves_existing_export_and_cleans_temporary_file(
    client, route, export_dir, renderer, monkeypatch
):
    destination = export_dir / "face.png"
    destination.write_bytes(b"previous PNG")

    def fail_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(face_exports.os, "replace", fail_replace)

    response = client.post(route, json={"out": "face.png"})

    assert_error(response, 503, "face_export_unavailable")
    assert destination.read_bytes() == b"previous PNG"
    assert list(export_dir.iterdir()) == [destination]


def test_renderer_failure_preserves_existing_export(client, route, export_dir, renderer):
    destination = export_dir / "face.png"
    destination.write_bytes(b"previous PNG")
    renderer.side_effect = RuntimeError("mock renderer unavailable")

    response = client.post(route, json={"out": "face.png"})

    assert response.status_code == 503
    assert response.get_json()["ok"] is False
    assert destination.read_bytes() == b"previous PNG"
    assert list(export_dir.iterdir()) == [destination]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_supported_rotations_are_accepted(client, route, export_dir, renderer, rotation):
    response = client.post(route, json={"out": "face.png", "rotation": rotation})

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    renderer.assert_called_once_with("neutral", 240)
    assert (export_dir / "face.png").read_bytes() == PNG


def test_directory_swap_during_replace_cannot_redirect_export(client, route, export_dir, renderer, monkeypatch):
    outside = export_dir.parent / "outside"
    outside.mkdir()
    victim = outside / "face.png"
    victim.write_bytes(b"outside must survive")
    pinned_directory = export_dir.parent / "pinned-exports"
    real_replace = os.replace

    def swap_then_replace(*args, **kwargs):
        export_dir.rename(pinned_directory)
        export_dir.symlink_to(outside, target_is_directory=True)
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(face_exports.os, "replace", swap_then_replace)

    response = client.post(route, json={"out": "face.png"})

    assert response.status_code == 200
    assert victim.read_bytes() == b"outside must survive"
    destination = pinned_directory / "face.png"
    assert destination.read_bytes() == PNG
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(pinned_directory.iterdir()) == [destination]
    assert list(outside.iterdir()) == [victim]


@pytest.mark.parametrize("output", ["", None, False, [], {}])
def test_explicit_invalid_output_does_not_become_preview(client, route, export_dir, renderer, output):
    response = client.post(route, json={"out": output}, headers={"Accept": "image/png"})

    assert_error(response, 400, "invalid_face_output")
    renderer.assert_not_called()
    assert list(export_dir.iterdir()) == []


def test_temporary_name_collision_does_not_remove_existing_entry(client, export_dir, renderer, monkeypatch):
    token = "a" * 32
    collision = export_dir / (".rider-face-" + token + ".tmp")
    collision.write_bytes(b"existing entry must survive")
    monkeypatch.setattr(face_exports.secrets, "token_hex", lambda length: token)

    response = client.post("/face/render", json={"out": "face.png"})

    assert_error(response, 503, "face_export_unavailable")
    assert collision.read_bytes() == b"existing entry must survive"
    assert list(export_dir.iterdir()) == [collision]
