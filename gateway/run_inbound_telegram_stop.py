"""Emergency stop gate for Telegram DM turns."""

from __future__ import annotations

import logging
from typing import Optional

from gateway.config import Platform
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource

logger = logging.getLogger("gateway.run")


class GatewayTelegramChatStopMixin:
    def _hm_telegram_chat_stop_gate(
        self, event: MessageEvent, source: SessionSource, is_internal: bool,
    ) -> Optional[str]:
        if is_internal or getattr(source, "platform", None) != Platform.TELEGRAM:
            return None
        if getattr(source, "chat_type", None) != "dm":
            return None
        db = getattr(getattr(self, "_session_db", None), "_db", getattr(self, "_session_db", None))
        if db is None:
            return None
        try:
            profile = str(getattr(source, "profile", None) or getattr(self, "_active_profile_name", lambda: "default")() or "default")
            if not db.is_telegram_chat_paused(chat_id=source.chat_id, profile_name=profile):
                return None
        except Exception:
            logger.debug("Telegram chat stop state read failed", exc_info=True)
            return None
        command = (event.get_command() or "").lower()
        if command in {"stop", "stopall", "resumeall", "model", "tier-up", "tier-down", "tier_up", "tier_down"}:
            return None
        return "Telegram topics are paused. Use /resumeall to continue."
