"""Turn-error notices, including expected admission refusals during gateway restart."""

from __future__ import annotations

import logging

from agent.i18n import t

logger = logging.getLogger("gateway.platforms.base")


async def notify_turn_error(adapter, event, error):
    from gateway.platforms.base import _thread_metadata_for_event
    from gateway.warning_notifications import diagnostic_wake_muted

    thread_metadata = None
    try:
        thread_metadata = _thread_metadata_for_event(event)
        restarting = getattr(error, "reason", None) == "runtime_draining"
        detail = (
            "The gateway is restarting. Please resend your message shortly."
            if restarting else str(error)[:300] if str(error) else t("gateway.notify.turn_error_no_details"))
        with adapter._media_delivery_scope(event.source):
            if diagnostic_wake_muted(event):
                content = None
            elif restarting:
                content = adapter.warning_text(
                    detail, detail, logical_platform=event.source.platform,
                    chat_id=event.source.chat_id, metadata=thread_metadata)
            else:
                content = adapter.warning_text(
                    t("gateway.notify.turn_error_detailed", error_type=type(error).__name__, error_detail=detail),
                    t("gateway.notify.turn_error"), logical_platform=event.source.platform,
                    chat_id=event.source.chat_id, metadata=thread_metadata)
        if content is not None:
            await adapter.send(chat_id=event.source.chat_id, content=content, metadata=thread_metadata)
    except Exception as notify_error:
        logger.error("[%s] Failed to send error notification to user: %s",
                     adapter.name, notify_error, exc_info=True)
    return thread_metadata
