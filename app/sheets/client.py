import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.sheets.rows import MESSAGES_COLUMNS
from app.sheets.ticket_rows import TICKET_COLUMNS

_GREEN = {"red": 0.204, "green": 0.659, "blue": 0.325}
_RED   = {"red": 0.918, "green": 0.263, "blue": 0.208}


class GoogleSheetsClient:
    def __init__(
        self,
        credentials_path: Path | None,
        credentials_json: str | None,
        spreadsheet_id: str,
        append_range: str,
        sheet_name: str,
        tickets_sheet_name: str = "Tickets",
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
        self.tickets_sheet_name = tickets_sheet_name
        self.tickets_append_range = f"{tickets_sheet_name}!A:J"
        self._tickets_sheet_id: int | None = None

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
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
        self._ensure_named_sheet_exists(self.sheet_name)

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _ensure_named_sheet_exists(self, name: str) -> None:
        spreadsheet = (
            self.service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        titles = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
        if name in titles:
            return
        (
            self.service.spreadsheets()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": name}}}]},
            )
            .execute()
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def ensure_tickets_header(self) -> None:
        self._ensure_named_sheet_exists(self.tickets_sheet_name)
        range_name = f"{self.tickets_sheet_name}!A1:{_col_letter(len(TICKET_COLUMNS))}1"
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=range_name)
            .execute()
        )
        existing = result.get("values", [])
        if existing and existing[0] == TICKET_COLUMNS:
            return
        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [TICKET_COLUMNS]},
            )
            .execute()
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def append_ticket_row(self, row: list[Any]) -> int | None:
        """Write ticket row to the next empty row. Returns the 1-based row number written."""
        # Find the next empty row by counting filled cells in column F (Время обращения).
        # Column F is always populated for every real row (header + data), so its length
        # reliably tells us how many rows are present.
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{self.tickets_sheet_name}!F:F",
                majorDimension="COLUMNS",
            )
            .execute()
        )
        col_f = result.get("values", [[]])
        filled_rows = len(col_f[0]) if col_f else 0
        next_row = max(filled_rows + 1, 2)  # at minimum row 2 (after header)

        range_name = f"{self.tickets_sheet_name}!A{next_row}"
        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [row]},
            )
            .execute()
        )
        logger.info("ticket row written to sheets", extra={"_range": range_name, "_row": next_row})
        return next_row

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def update_ticket_cell(self, row_number: int, col_letter: str, value: str) -> None:
        range_name = f"{self.tickets_sheet_name}!{col_letter}{row_number}"
        (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [[value]]},
            )
            .execute()
        )

    def color_source_cells(self, row_number: int, source_type: str) -> None:
        """Color Telegram Chat (C), Telegram Direct (D), Discord (E) columns."""
        sheet_id = self._get_tickets_sheet_id()
        row_idx = row_number - 1  # 0-based
        logger.info("coloring cells", extra={"_row": row_number, "_sheet_id": sheet_id, "_source": source_type})

        # col indices: C=2, D=3, E=4
        col_colors = {
            2: _GREEN if source_type == "comment" else _RED,
            3: _GREEN if source_type == "direct"  else _RED,
            4: _RED,
        }
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_idx,
                        "endRowIndex": row_idx + 1,
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
            for col, color in col_colors.items()
        ]
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": requests},
        ).execute()

    def _get_tickets_sheet_id(self) -> int:
        if self._tickets_sheet_id is not None:
            return self._tickets_sheet_id
        spreadsheet = (
            self.service.spreadsheets()
            .get(spreadsheetId=self.spreadsheet_id, fields="sheets.properties")
            .execute()
        )
        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == self.tickets_sheet_name:
                self._tickets_sheet_id = int(props["sheetId"])
                return self._tickets_sheet_id
        raise ValueError(f"Sheet '{self.tickets_sheet_name}' not found")

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


def _col_letter(n: int) -> str:
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result
