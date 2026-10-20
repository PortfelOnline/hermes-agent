from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hermes_state import SessionDB
from hermes_cli.commands import resolve_command
from gateway.config import Platform
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.slash_commands_model import _configured_tier_target
from gateway.session import SessionEntry, SessionSource


def _source(*, thread_id=None, chat_type="dm", profile="main"):
    return SessionSource(
        platform=Platform.TELEGRAM, chat_type=chat_type, chat_id="u1", user_id="u1",
        thread_id=thread_id, profile=profile,
    )


def test_stopall_commands_are_gateway_only_and_available_while_busy():
    for name in ("stopall", "resumeall"):
        command = resolve_command(name)
        assert command is not None
        assert command.gateway_only is True
        assert command.busy_policy == "dispatch"


def test_configured_tier_step_uses_profile_alias_targets_and_bounds():
    aliases = {
        "route-low": "openai-codex/gpt-6-luna",
        "route-standard": "openai-codex/gpt-5.6-terra-900k",
        "route-advanced": "openai-codex/gpt-6-sol",
        "route-expert-astra": "openai-codex/gpt-6-astra",
    }
    assert _configured_tier_target(aliases, "gpt-6-sol", 1) == ("route-expert-astra", None)
    assert _configured_tier_target(aliases, "gpt-6-sol", -1) == ("route-standard", None)
    assert _configured_tier_target(aliases, "gpt-6-luna", -1) == (None, "boundary")
    assert _configured_tier_target(aliases, "unknown-model", 1) == (None, "unknown")
    anthropic_aliases = {
        "haiku": "anthropic/claude-haiku-5.5",
        "sonnet": "anthropic/claude-sonnet-5-5",
        "route-expert-opus": "anthropic/claude-opus-5-5",
    }
    assert _configured_tier_target(anthropic_aliases, "claude-sonnet-5-5", 1) == ("route-expert-opus", None)


def _runner(db, source):
    runner = object.__new__(GatewayRunner)
    runner._session_db = SimpleNamespace(_db=db)
    runner.session_store = object()
    runner._async_session_store = SimpleNamespace(
        _store=runner.session_store,
        get_or_create_session=AsyncMock(return_value=SessionEntry(
            session_key="agent:main:telegram:dm:u1:topic-1", session_id="s1",
            created_at=datetime.now(), updated_at=datetime.now(), platform=Platform.TELEGRAM,
            chat_type="dm", origin=source,
        ))
    )
    runner._is_user_authorized_for_source = lambda _source: True
    runner._running_agents = {
        "agent:main:telegram:dm:u1:topic-1": object(),
        "agent:main:telegram:dm:u1:topic-2": object(),
    }
    runner._same_chat_runs = lambda _source, own_key: [
        ("agent:main:telegram:dm:u1:topic-2", "dm", "topic-2")
    ]
    runner._interrupt_and_clear_session = AsyncMock()
    return runner


@pytest.mark.asyncio
async def test_stopall_stops_every_running_topic_and_resumeall_unpauses(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    source = _source(thread_id="topic-1")
    runner = _runner(db, source)
    try:
        reply = await runner._handle_stopall_command(MessageEvent(
            text="/stopall", source=source, message_type=MessageType.TEXT,
        ))
        assert "all Telegram topics" in reply
        assert db.is_telegram_chat_paused(chat_id="u1", profile_name="main") is True
        assert {call.args[0] for call in runner._interrupt_and_clear_session.await_args_list} == {
            "agent:main:telegram:dm:u1:topic-1", "agent:main:telegram:dm:u1:topic-2",
        }

        resumed = await runner._handle_resumeall_command(MessageEvent(
            text="/resumeall", source=source, message_type=MessageType.TEXT,
        ))
        assert "resumed" in resumed.lower()
        assert db.is_telegram_chat_paused(chat_id="u1", profile_name="main") is False
    finally:
        db.close()


@pytest.mark.asyncio
async def test_chat_stop_gate_blocks_new_turns_but_allows_stop_resume_and_model_controls(tmp_path):
    db = SessionDB(db_path=tmp_path / "state.db")
    source = _source(thread_id="topic-2")
    runner = _runner(db, source)
    db.set_telegram_chat_paused(chat_id="u1", user_id="u1", profile_name="main", paused=True)
    try:
        blocked = runner._hm_telegram_chat_stop_gate(
            MessageEvent(text="hello", source=source, message_type=MessageType.TEXT), source, False,
        )
        assert blocked is not None
        for command in ("/stopall", "/resumeall", "/model", "/model gpt-5.6-terra-900k",
                        "/tier-up", "/tier-down", "/tier_up", "/tier_down"):
            assert runner._hm_telegram_chat_stop_gate(
                MessageEvent(text=command, source=source, message_type=MessageType.TEXT), source, False,
            ) is None
        group = _source(thread_id="topic-2", chat_type="group")
        assert runner._hm_telegram_chat_stop_gate(
            MessageEvent(text="hello", source=group, message_type=MessageType.TEXT), group, False,
        ) is None
    finally:
        db.close()
