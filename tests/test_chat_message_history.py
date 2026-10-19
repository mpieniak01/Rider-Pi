"""REST chat payloads preserve provider history semantics without network access."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from apps.voice.chat import ChatConfig, ChatSession, Message


@pytest.mark.parametrize("builder_name", ["_build_messages_openai", "_build_messages_local"])
@pytest.mark.parametrize("max_history", [2, 0, -1], ids=["last-two-pairs", "disabled", "negative"])
def test_rest_payload_preserves_order_and_respects_history_limit(builder_name, max_history):
    session = ChatSession(
        ChatConfig(backend="local", model="fixture", system_prompt="Jesteś pomocny.", max_history=max_history)
    )
    history = [
        Message("user", "old question"),
        Message("assistant", "old answer"),
        Message("user", "recent question"),
        Message("assistant", "recent answer"),
        Message("user", "newest question"),
        Message("assistant", "newest answer"),
    ]
    session._history = list(history)
    expected_history = (
        [
            {"role": "user", "content": "recent question"},
            {"role": "assistant", "content": "recent answer"},
            {"role": "user", "content": "newest question"},
            {"role": "assistant", "content": "newest answer"},
        ]
        if max_history == 2
        else []
    )

    messages = getattr(session, builder_name)("current question")

    assert messages == [
        {"role": "system", "content": "Jesteś pomocny."},
        *expected_history,
        {"role": "user", "content": "current question"},
    ]
    assert session._history == history


@pytest.mark.parametrize("builder_name", ["_build_messages_openai", "_build_messages_local"])
def test_rest_payload_is_fresh_and_cannot_mutate_session_state(builder_name):
    session = ChatSession(ChatConfig(backend="local", model="fixture", system_prompt="Original prompt", max_history=1))
    session._history = [Message("user", "previous question"), Message("assistant", "previous answer")]
    builder = getattr(session, builder_name)
    expected = [
        {"role": "system", "content": "Original prompt"},
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "current question"},
    ]
    messages = builder("current question")
    messages[0]["content"] = "modified prompt"
    messages[1]["content"] = "modified history"
    messages.append({"role": "assistant", "content": "unrelated answer"})

    assert builder("current question") == expected
    assert session.config.system_prompt == "Original prompt"
    assert session._history == [Message("user", "previous question"), Message("assistant", "previous answer")]


def test_local_ask_sends_clipped_history_then_records_cleaned_exchange(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"message": {"content": " **new answer** "}}
    post = Mock(return_value=response)
    monkeypatch.setattr("requests.post", post)
    session = ChatSession(
        ChatConfig(
            backend="local",
            model="fixture",
            system_prompt="System prompt",
            max_history=1,
            base_url="http://fixture.invalid:8000/",
            endpoint="/api/chat",
            timeout=3.5,
        )
    )
    session._history = [
        Message("user", "old question"),
        Message("assistant", "old answer"),
        Message("user", "previous question"),
        Message("assistant", "previous answer"),
    ]

    reply, history = session.ask("**new question**")

    post.assert_called_once_with(
        "http://fixture.invalid:8000/api/chat",
        json={
            "messages": [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "previous question"},
                {"role": "assistant", "content": "previous answer"},
                {"role": "user", "content": "new question"},
            ]
        },
        timeout=3.5,
    )
    assert reply == "new answer"
    assert history == [Message("user", "new question"), Message("assistant", "new answer")]
