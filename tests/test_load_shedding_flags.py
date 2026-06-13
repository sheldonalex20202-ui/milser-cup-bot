from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import _ensure_direct_broadcast_enabled, sync_pending


def test_direct_broadcast_guard_returns_503_when_disabled() -> None:
    settings = SimpleNamespace(direct_broadcast_enabled=False)

    with pytest.raises(HTTPException) as exc:
        _ensure_direct_broadcast_enabled(settings)  # type: ignore[arg-type]

    assert exc.value.status_code == 503
    assert exc.value.detail == "direct broadcast is temporarily disabled"


def test_sync_pending_skips_ticket_alerts_when_disabled() -> None:
    class Ingest:
        def sync_pending_once(self) -> int:
            return 2

    class Tickets:
        def sync_closed_tickets(self) -> int:
            return 3

        def check_stale_tickets(self) -> int:
            raise AssertionError("ticket alerts must stay disabled")

    settings = SimpleNamespace(
        telegram_webhook_secret_token="secret-token",
        ticket_alerts_enabled=False,
    )

    result = sync_pending(
        x_telegram_bot_api_secret_token="secret-token",
        settings=settings,  # type: ignore[arg-type]
        ingest=Ingest(),  # type: ignore[arg-type]
        ticket_svc=Tickets(),  # type: ignore[arg-type]
    )

    assert result == {
        "ok": True,
        "messages_synced": 2,
        "tickets_synced": 3,
        "alerts_sent": 0,
    }
