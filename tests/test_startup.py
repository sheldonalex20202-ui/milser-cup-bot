from contextlib import asynccontextmanager

from app import main


class DummyIngestService:
    def __init__(self, fail_on_ready: bool = False) -> None:
        self.fail_on_ready = fail_on_ready
        self.synced = False

    def ensure_sheets_ready(self) -> None:
        if self.fail_on_ready:
            raise RuntimeError("messages sheets unavailable")

    def sync_pending_once(self) -> int:
        self.synced = True
        return 0


class DummyTicketService:
    def __init__(self, fail_on_ready: bool = False) -> None:
        self.fail_on_ready = fail_on_ready
        self.synced = False

    def ensure_sheets_ready(self) -> None:
        if self.fail_on_ready:
            raise RuntimeError("tickets sheets unavailable")

    def sync_closed_tickets(self) -> int:
        self.synced = True
        return 0


class DummyDatabase:
    def __init__(self) -> None:
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True


class DummySettings:
    def __init__(self, support_group_chat_id: int | None) -> None:
        self.log_level = "INFO"
        self.telegram_support_group_chat_id = support_group_chat_id


async def _enter_lifespan() -> None:
    @asynccontextmanager
    async def _app_context():
        yield

    async with main.lifespan(None):
        pass


def test_lifespan_continues_when_messages_sheets_startup_fails(monkeypatch):
    db = DummyDatabase()
    ingest = DummyIngestService(fail_on_ready=True)
    ticket = DummyTicketService()

    monkeypatch.setattr(main, "get_settings", lambda: DummySettings(123))
    monkeypatch.setattr(main, "configure_logging", lambda level: None)
    monkeypatch.setattr(main, "get_database", lambda: db)
    monkeypatch.setattr(main, "get_ingest_service", lambda: ingest)
    monkeypatch.setattr(main, "get_ticket_service", lambda: ticket)

    import asyncio

    asyncio.run(_enter_lifespan())

    assert db.initialized is True
    assert ingest.synced is False
    assert ticket.synced is True


def test_lifespan_continues_when_ingest_service_creation_fails(monkeypatch):
    db = DummyDatabase()
    ticket = DummyTicketService()

    monkeypatch.setattr(main, "get_settings", lambda: DummySettings(123))
    monkeypatch.setattr(main, "configure_logging", lambda level: None)
    monkeypatch.setattr(main, "get_database", lambda: db)
    monkeypatch.setattr(main, "get_ingest_service", lambda: (_ for _ in ()).throw(RuntimeError("ingest init failed")))
    monkeypatch.setattr(main, "get_ticket_service", lambda: ticket)

    import asyncio

    asyncio.run(_enter_lifespan())

    assert db.initialized is True
    assert ticket.synced is True


def test_lifespan_continues_when_tickets_sheets_startup_fails(monkeypatch):
    db = DummyDatabase()
    ingest = DummyIngestService()
    ticket = DummyTicketService(fail_on_ready=True)

    monkeypatch.setattr(main, "get_settings", lambda: DummySettings(123))
    monkeypatch.setattr(main, "configure_logging", lambda level: None)
    monkeypatch.setattr(main, "get_database", lambda: db)
    monkeypatch.setattr(main, "get_ingest_service", lambda: ingest)
    monkeypatch.setattr(main, "get_ticket_service", lambda: ticket)

    import asyncio

    asyncio.run(_enter_lifespan())

    assert db.initialized is True
    assert ingest.synced is True
    assert ticket.synced is False
