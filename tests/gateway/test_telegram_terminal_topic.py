"""Tests for the Telegram terminal-topic status card (reverse-handoff button)."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

_repo = str(Path(__file__).resolve().parents[2])
if _repo not in sys.path:
    sys.path.insert(0, _repo)

from gateway.config import PlatformConfig
from plugins.platforms.telegram.adapter import TelegramAdapter


def _make_adapter():
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token="test-token", extra={}))
    adapter._bot = AsyncMock()
    adapter._app = SimpleNamespace()
    return adapter


def test_send_terminal_topic_status_attaches_terminal_button(monkeypatch):
    from gateway.terminal_topics import TerminalTask

    adapter = _make_adapter()
    adapter._bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=7))
    buttons = []

    class _Button:
        def __init__(self, text, callback_data):
            self.text, self.callback_data = text, callback_data
            buttons.append(self)

    monkeypatch.setattr("plugins.platforms.telegram.adapter.InlineKeyboardButton", _Button)
    monkeypatch.setattr(
        "plugins.platforms.telegram.adapter.InlineKeyboardMarkup", lambda rows: rows)

    task = TerminalTask(tty="ttys000", session_id="session-a", cwd="/Users/eve/project-a")
    result = __import__("asyncio").run(
        adapter.send_terminal_topic_status("109733868", task, "42"))

    assert result.success is True
    call = adapter._bot.send_message.call_args.kwargs
    assert call["chat_id"] == 109733868
    assert "session-a" in call["text"]
    assert buttons and buttons[0].callback_data == "term:ttys000"
    assert call["reply_markup"] is not None
