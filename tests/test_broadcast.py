from app.services.broadcast import DirectBroadcastRecipient, DirectBroadcastService
from app.services.broadcast_lookup import parse_usernames, recipients_from_found
from app.telegram.sender import TelegramSender


class FakeSender:
    def __init__(self) -> None:
        self.calls = []

    def send_message(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        return {"ok": True, "result": {"message_id": 1234}}


def test_parse_usernames_normalizes_and_deduplicates() -> None:
    assert parse_usernames("@Alice\n bob,alice; @BOB\n") == ["alice", "bob"]


def test_direct_broadcast_sends_to_direct_topic() -> None:
    sender = FakeSender()
    service = DirectBroadcastService(sender)  # type: ignore[arg-type]

    result = service.send(
        "hello",
        [DirectBroadcastRecipient(chat_id=-1001, direct_messages_topic_id=42, user_id=7)],
        dry_run=False,
    )

    assert result["sent"] == 1
    assert result["failed"] == 0
    assert sender.calls == [
        {
            "chat_id": -1001,
            "direct_messages_topic_id": 42,
            "text": "hello",
        }
    ]


def test_recipients_from_found_builds_direct_recipients() -> None:
    recipients = recipients_from_found(
        [
            {
                "chat_id": "-2073084610401",
                "direct_messages_topic_id": "7058684259",
                "user_id": "7058684259",
                "username": "rashpil_a",
            }
        ]
    )

    assert len(recipients) == 1
    assert recipients[0].chat_id == -2073084610401
    assert recipients[0].direct_messages_topic_id == 7058684259
    assert recipients[0].user_id == 7058684259
    assert recipients[0].username == "rashpil_a"


def test_telegram_sender_includes_direct_messages_topic_id() -> None:
    sender = TelegramSender("123456:test-token")
    calls = []

    def fake_call(method, payload):  # noqa: ANN001, ANN202
        calls.append((method, payload))
        return {"ok": True}

    sender._call = fake_call  # type: ignore[method-assign]

    sender.send_message(chat_id=-1001, direct_messages_topic_id=42, text="hello")

    assert calls == [
        (
            "sendMessage",
            {
                "chat_id": -1001,
                "text": "hello",
                "parse_mode": "HTML",
                "direct_messages_topic_id": 42,
            },
        )
    ]
