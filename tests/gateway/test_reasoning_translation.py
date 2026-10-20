"""Reasoning block shown in Telegram is translated to display.language; the stored text is not."""
from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway import reasoning_translation as rt


@pytest.mark.parametrize(("text", "lang", "expected"), [
    ("**Reviewing source filter changes**", "ru", True),
    ("**Reviewing source filter changes**", "en", False),
    ("Проверяю фильтр источников", "ru", False),
    ("", "ru", False),
    ("123 ... !!!", "ru", False),
])
def test_needs_translation(text, lang, expected):
    assert rt.needs_translation(text, lang) is expected


def _stub_gateway_run(monkeypatch, show_reasoning):
    """gateway.run pulls in the process bootstrap, which reads the real hermes home; stub only the
    display-config boundary the mixin late-imports."""
    import sys
    from types import ModuleType
    fake = ModuleType("gateway.run")
    fake._load_gateway_config = lambda: {"display": {"show_reasoning": show_reasoning}}
    fake._platform_config_key = lambda platform: str(platform)
    fake._resolve_gateway_display_bool = lambda cfg, key, name, default, platform, require_platform_override_for: (
        cfg["display"][name])
    monkeypatch.setitem(sys.modules, "gateway.run", fake)


def _reply(monkeypatch, translated=None, boom=False):
    import agent.auxiliary_client as aux
    monkeypatch.setattr(rt, "get_language", lambda: "ru")
    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        if boom:
            raise RuntimeError("provider down")
        return translated

    monkeypatch.setattr(aux, "call_llm", fake_call_llm)
    monkeypatch.setattr(aux, "extract_content_or_reasoning", lambda response: response)
    return calls


def test_translate_uses_dedicated_task_and_target_language(monkeypatch):
    calls = _reply(monkeypatch, translated="**Проверяю изменения фильтра**")
    assert rt.translate_reasoning("**Reviewing source filter changes**") == "**Проверяю изменения фильтра**"
    assert calls[0]["task"] == "reasoning_translation"
    assert "Русский" in calls[0]["messages"][0]["content"]


def test_translation_failure_keeps_original(monkeypatch):
    _reply(monkeypatch, boom=True)
    assert rt.translate_reasoning("**Reviewing source filter changes**") == "**Reviewing source filter changes**"


@pytest.mark.asyncio
async def test_display_copy_is_rendered_and_stored_reasoning_is_kept(monkeypatch):
    from gateway.run_turn_persistence import GatewayTurnPersistenceMixin
    _stub_gateway_run(monkeypatch, True)
    _reply(monkeypatch, translated="**Проверяю изменения фильтра**")
    runner = GatewayTurnPersistenceMixin()
    source = SimpleNamespace(platform=Platform.TELEGRAM)
    result = {"last_reasoning": "**Reviewing source filter changes**"}

    await runner._hmwa_localize_reasoning(result, source)
    reply = runner._hmwa_prepend_reasoning(result, "ответ", source, False)

    assert "Проверяю изменения фильтра" in reply
    assert "Reviewing" not in reply
    assert result["last_reasoning"] == "**Reviewing source filter changes**"


@pytest.mark.asyncio
async def test_hidden_reasoning_is_not_translated(monkeypatch):
    from gateway.run_turn_persistence import GatewayTurnPersistenceMixin
    _stub_gateway_run(monkeypatch, False)
    calls = _reply(monkeypatch, translated="x")
    result = {"last_reasoning": "**Reviewing source filter changes**"}

    await GatewayTurnPersistenceMixin()._hmwa_localize_reasoning(result, SimpleNamespace(platform=Platform.TELEGRAM))

    assert calls == [] and "last_reasoning_display" not in result
