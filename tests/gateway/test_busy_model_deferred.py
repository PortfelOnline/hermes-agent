"""A ``/model <target>`` sent while the agent runs is queued, not rejected, and applied once the turn ends.

Regression for: the user had to ``/stop`` a running task just to switch models. The switch must not
touch the live agent mid-turn; it lands after ``_handle_message`` releases the session.
"""

from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from hermes_cli.commands import COMMAND_REGISTRY


def _model_cmd_def():
    return next(c for c in COMMAND_REGISTRY if c.name == "model")


def _runner():
    runner = object.__new__(GatewayRunner)
    runner._handle_model_command = AsyncMock(return_value="✅ switched")
    runner._send_command_ack = AsyncMock()
    return runner


def _event(text):
    source = SessionSource(platform=Platform.TELEGRAM, user_id="u", user_name="u",
                           chat_id="c", chat_type="dm")
    return MessageEvent(text=text, message_type=MessageType.TEXT, source=source, message_id="m")


def test_busy_route_for_model_is_the_deferred_handler():
    runner = _runner()
    kind, target = runner._busy_slash_route(_model_cmd_def())
    assert kind == "special"
    assert target == "_busy_model_command"


@pytest.mark.asyncio
async def test_busy_model_with_target_is_queued_not_committed():
    runner = _runner()
    event = _event("/model luna")
    reply = await runner._busy_model_command(event, "k", event.source)
    assert "luna" in reply
    assert runner.__dict__["_deferred_busy_model_switches"]["k"] is event
    runner._handle_model_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_busy_model_without_target_keeps_reject_text():
    runner = _runner()
    event = _event("/model")
    reply = await runner._busy_model_command(event, "k", event.source)
    assert "/stop" in reply
    assert "_deferred_busy_model_switches" not in runner.__dict__


@pytest.mark.asyncio
async def test_apply_runs_queued_switch_once_and_acks():
    runner = _runner()
    event = _event("/model luna")
    await runner._busy_model_command(event, "k", event.source)

    await runner._apply_deferred_busy_model_switch("k")
    runner._handle_model_command.assert_awaited_once_with(event)
    runner._send_command_ack.assert_awaited_once()

    # Second apply is a no-op: the queue entry was consumed.
    await runner._apply_deferred_busy_model_switch("k")
    runner._handle_model_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_failure_is_reported_not_raised():
    runner = _runner()
    runner._handle_model_command = AsyncMock(side_effect=RuntimeError("boom"))
    event = _event("/model luna")
    await runner._busy_model_command(event, "k", event.source)
    await runner._apply_deferred_busy_model_switch("k")
    runner._send_command_ack.assert_awaited_once()
