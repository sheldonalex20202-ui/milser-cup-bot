import json
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from app.core.config import Settings
from app.services.broadcast import DirectBroadcastRecipient


REQUIRED_COLUMNS = {
    "source_type",
    "telegram_chat_id",
    "telegram_direct_messages_topic_id",
    "user_id",
    "username",
    "first_name",
    "last_name",
    "message_date_utc",
}


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def parse_usernames(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in text.replace(",", "\n").replace(";", "\n").splitlines():
        username = normalize_username(raw)
        if not username or username in seen:
            continue
        seen.add(username)
        result.append(username)
    return result


class GoogleSheetsDirectRecipientLookup:
    def __init__(self, settings: Settings) -> None:
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        if settings.google_credentials_json:
            credentials = Credentials.from_service_account_info(
                json.loads(settings.google_credentials_json),
                scopes=scopes,
            )
        elif settings.google_credentials_path:
            credentials_path = settings.google_credentials_path
            if not credentials_path.is_absolute():
                credentials_path = Path.cwd() / credentials_path
            credentials = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
        else:
            raise ValueError("Google credentials are required for Sheets lookup")
        self.service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self.spreadsheet_id = settings.google_spreadsheet_id

    def lookup(
        self,
        usernames: list[str],
        *,
        direct_chat_id: int | None = None,
    ) -> dict[str, Any]:
        wanted = [normalize_username(item) for item in usernames if normalize_username(item)]
        wanted_set = set(wanted)
        matches: dict[str, dict[tuple[int, int, int | None], dict[str, Any]]] = {
            username: {} for username in wanted
        }

        for sheet_name in self._message_sheet_names():
            values = self._read_sheet(sheet_name)
            if not values:
                continue
            header = values[0]
            if not REQUIRED_COLUMNS.issubset(set(header)):
                continue
            idx = {name: i for i, name in enumerate(header)}
            for row in values[1:]:
                if _cell(row, idx, "source_type") != "direct":
                    continue
                username = normalize_username(_cell(row, idx, "username"))
                if username not in wanted_set:
                    continue
                chat_id = _int_or_none(_cell(row, idx, "telegram_chat_id"))
                topic_id = _int_or_none(_cell(row, idx, "telegram_direct_messages_topic_id"))
                user_id = _int_or_none(_cell(row, idx, "user_id"))
                if chat_id is None or topic_id is None:
                    continue
                if direct_chat_id is not None and chat_id != direct_chat_id:
                    continue
                key = (chat_id, topic_id, user_id)
                item = matches[username].setdefault(
                    key,
                    {
                        "chat_id": chat_id,
                        "direct_messages_topic_id": topic_id,
                        "user_id": user_id,
                        "username": username,
                        "first_name": None,
                        "last_name": None,
                        "first_seen": None,
                        "last_seen": None,
                        "rows": 0,
                        "sheet_names": [],
                    },
                )
                item["rows"] += 1
                if sheet_name not in item["sheet_names"]:
                    item["sheet_names"].append(sheet_name)
                for name in ("first_name", "last_name"):
                    value = _cell(row, idx, name)
                    if value:
                        item[name] = value
                seen_at = _cell(row, idx, "message_date_utc")
                if seen_at and (item["first_seen"] is None or seen_at < item["first_seen"]):
                    item["first_seen"] = seen_at
                if seen_at and (item["last_seen"] is None or seen_at > item["last_seen"]):
                    item["last_seen"] = seen_at

        found: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        missing: list[str] = []
        for username in wanted:
            variants = list(matches[username].values())
            if not variants:
                missing.append(username)
                continue
            variants.sort(key=lambda item: item.get("last_seen") or "", reverse=True)
            if len(variants) > 1:
                ambiguous.append({"username": username, "matches": variants})
            found.append(variants[0])

        return {
            "requested_usernames": wanted,
            "found": found,
            "missing": missing,
            "ambiguous": ambiguous,
        }

    def _message_sheet_names(self) -> list[str]:
        spreadsheet = (
            self.service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        names = [sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])]
        return [name for name in names if "messages" in name.lower()]

    def _read_sheet(self, sheet_name: str) -> list[list[Any]]:
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!A:W")
            .execute()
        )
        return result.get("values", [])


def recipients_from_found(found: list[dict[str, Any]]) -> list[DirectBroadcastRecipient]:
    return [
        DirectBroadcastRecipient(
            chat_id=int(item["chat_id"]),
            direct_messages_topic_id=int(item["direct_messages_topic_id"]),
            user_id=_int_or_none(item.get("user_id")),
            username=item.get("username"),
        )
        for item in found
    ]


def _cell(row: list[Any], idx: dict[str, int], name: str) -> str:
    i = idx[name]
    if i >= len(row):
        return ""
    return str(row[i])


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
