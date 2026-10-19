"""O1 parser and wait contracts compile definitions without running device scripts."""

from __future__ import annotations

import ast
import builtins
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def definitions(filename, names, namespace=None):
    tree = ast.parse((ROOT / "scripts" / filename).read_text())
    selected = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(selected) == len(names)
    future = ast.parse("from __future__ import annotations").body
    namespace = {} if namespace is None else namespace
    exec(compile(ast.Module(body=future + selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "text,expected",
    [
        ("alpha (one) beta", "alpha beta"),
        ("alpha ((one) beta)", "alpha beta)"),
        ("alpha (unfinished", "alpha (unfinished"),
        ("alpha (one) (unfinished", "alpha (unfinished"),
        ("(one)(two)", ""),
        ("a\t(b)\tc", "a\tc"),
        ("a\u00a0(b)  c", "a c"),
        ("a) b (c)", "a) b"),
        ("a\n(b)\nc", "a\nc"),
    ],
)
def test_splash_parentheses_keep_first_closing_delimiter_and_whitespace(text, expected):
    module = definitions("sys_splash-info.py", {"_strip_parens"}, {"re": re})
    assert module["_strip_parens"](text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("alpha   (beta)", ["alpha", "(beta)"]),
        ("(beta)", ["", "(beta)"]),
        ("alpha\n(beta)", ["alpha", "(beta)"]),
        ("alpha\t(beta) tail", ["alpha", "(beta) tail"]),
    ],
)
def test_splash_wrap_splits_only_first_opening_when_no_newline(text, expected):
    module = definitions(
        "sys_splash-info.py", {"wrap_lines"}, {"text_size": lambda _draw, value, _font: (len(value), 1)}
    )
    assert module["wrap_lines"](None, text, None, 100) == expected


def test_splash_long_unclosed_parentheses_and_whitespace_are_bounded():
    module = definitions(
        "sys_splash-info.py",
        {"_strip_parens", "wrap_lines"},
        {"re": re, "text_size": lambda _draw, value, _font: (len(value), 1)},
    )
    text = "(" * 100_000
    assert module["_strip_parens"](text) == text
    assert module["wrap_lines"](None, " " * 100_000 + "(tail)", None, 100) == ["", "(tail)"]


def test_docs_table_parser_keeps_cells_boundaries_and_normalized_captures(tmp_path):
    summary = tmp_path / "docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        "| Old Path | New Path |\n| ops/a.py | scripts/new-a.py |\n"
        "|| tools/b.sh | scripts/new-b.sh |\n|   | scripts/ignored.py |\n"
        "| ops/multi.py\nmore | scripts/multi.py |\n"
    )
    module = definitions(
        "dev_update-docs-references.py", {"extract_migrations_from_summary"}, {"REPO_ROOT": tmp_path, "re": re}
    )
    assert module["extract_migrations_from_summary"]() == {
        "ops/a.py": "scripts/new-a.py",
        "tools/b.sh": "scripts/new-b.sh",
        "ops/multi.py\nmore": "scripts/multi.py",
    }
    summary.write_text("|" + " " * 100_000 + "not_a_complete_row")
    assert module["extract_migrations_from_summary"]() == {}


def test_docs_references_return_both_lists_and_keep_underscore_hyphen_unicode():
    module = definitions("dev_validate-docs-links.py", {"extract_file_references"}, {"re": re})
    result = module["extract_file_references"](
        "scripts/a_b-c.py ops/zażółć_x.sh tools/t-1.py [local](../README.md) [skip](#x)"
    )
    assert result == (["scripts/a_b-c.py", "../README.md"], ["ops/zażółć_x.sh", "tools/t-1.py"])


@pytest.mark.parametrize("playing,finished", [([False], []), ([True, False], [False]), ([True], [True])])
def test_direct_face_wait_restores_signal_and_stops_after_completion(playing, finished):
    calls = []
    previous = object()
    event = SimpleNamespace(wait=lambda seconds: calls.append(("wait", seconds)) or finished.pop(0), set=lambda: None)
    fake_signal = SimpleNamespace(
        SIGTERM=15,
        getsignal=lambda _signum: previous,
        signal=lambda signum, handler: calls.append(("signal", signum, handler)),
    )
    fake_face = SimpleNamespace(get_state=lambda: {"state": {"playing": playing.pop(0)}})
    original_import = builtins.__import__

    def import_fake(name, *args, **kwargs):
        modules = {
            "signal": fake_signal,
            "threading": SimpleNamespace(Event=lambda: event),
            "services.api_core": SimpleNamespace(face_anim=fake_face),
        }
        return modules[name] if name in modules else original_import(name, *args, **kwargs)

    module = definitions(
        "resource_ctl.py",
        {"_wait_direct_face"},
        {"json": json, "__builtins__": {**vars(builtins), "__import__": import_fake}},
    )
    client = SimpleNamespace(request=lambda *args: calls.append(("request", *args)) or {"ok": True})
    assert module["_wait_direct_face"](client, {"initial": True}) == {"ok": True}
    assert calls[-2] == ("signal", 15, previous)
    assert calls[-1] == ("request", "/api/face-studio/runtime/stop", "POST", {})
    assert all(row[1] == 0.25 for row in calls if row[0] == "wait")


@pytest.mark.parametrize(
    "bound,forced,scan,expected",
    [(True, False, None, []), (False, True, None, ["force"]), (False, False, "found", ["force", "scan"])],
)
def test_direct_push_keeps_force_scan_short_circuit(bound, forced, scan, expected):
    calls = []
    binding = (SimpleNamespace(push=lambda _image: None), "push", "pil")
    sink = SimpleNamespace(
        _push=binding if bound else None,
        _prep=lambda image: image,
        _auto_prefer_pil=lambda _image, _target, name, tag: (name, tag),
    )

    def force():
        calls.append("force")
        if forced:
            sink._push = binding
        return forced

    def scan_bind(_image):
        calls.append("scan")
        sink._push = binding
        return scan

    sink._force_bind = force
    sink._scan_bind = scan_bind
    module = definitions("dev_face-lcd-direct.py", {"push"}, {"_dispatch_direct_frame": Mock()})
    assert module["push"](sink, object()) == "SimpleNamespace.push[pil]"
    assert calls == expected
    module["_dispatch_direct_frame"].assert_called_once()
