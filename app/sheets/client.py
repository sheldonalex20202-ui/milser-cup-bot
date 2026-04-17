import json
from pathlib import Path
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.sheets.rows import MESSAGES_COLUMNS


class GoogleSheetsClient:
    def __init__(
        self,
        credentials_path: Path | None,
        credentials_json: str | None,
        spreadsheet_id: str,
        append_range: str,
        sheet_name: str,
    ) -> None:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        if credentials_json:
            credentials_info = json.loads(credentials_json)
            credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        elif credentials_path:
            credentials = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
        else:
            raise ValueError("Either GOOGLE_CREDENTIALS_JSON or GOOGLE_CREDENTIALS_PATH must be configured")
        self.service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self.spreadsheet_id = spreadsheet_id
        self.append_range = append_range
        self.sheet_name = sheet_name

    def ensure_messages_header(self) -> None:
        self._ensure_sheet_exists()
        range_name = f"{self.sheet_name}!A1:W1"
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=range_name)
            .execute()
        )
        existing = result.get("values", [])
        if existing and existing[0] == MESSAGES_COLUMNS:
            return
        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [MESSAGES_COLUMNS]},
            )
            .execute()
        )

    def _ensure_sheet_exists(self) -> None:
        spreadsheet = (
            self.service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        titles = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
        if self.sheet_name in titles:
            return
        (
            self.service.spreadsheets()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": self.sheet_name}}}]},
            )
            .execute()
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def append_row(self, row: list[Any]) -> None:
        (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=self.append_range,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
            .execute()
        )
