import json
from pathlib import Path
from typing import Any

from app.sheets.rows import MESSAGES_COLUMNS
from app.sheets.ticket_rows import TICKET_COLUMNS


class FakeGoogleSheetsClient:
    """Local test replacement for Google Sheets.

    It records writes to JSONL files under the test data directory so webhook
    flows can be exercised without Google credentials.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.messages_path = self.data_dir / "fake_messages_sheet.jsonl"
        self.tickets_path = self.data_dir / "fake_tickets_sheet.jsonl"
        self.ticket_updates_path = self.data_dir / "fake_ticket_updates.jsonl"

    def ensure_messages_header(self) -> None:
        self._write_once(self.messages_path, {"type": "header", "row": MESSAGES_COLUMNS})

    def ensure_tickets_header(self) -> None:
        self._write_once(self.tickets_path, {"type": "header", "row": TICKET_COLUMNS})

    def append_row(self, row: list[Any]) -> None:
        self._append_jsonl(self.messages_path, {"type": "row", "row": row})

    def append_ticket_row(self, row: list[Any]) -> int:
        row_number = self._next_ticket_row_number()
        self._append_jsonl(self.tickets_path, {"type": "row", "row_number": row_number, "row": row})
        return row_number

    def update_ticket_cell(self, row_number: int, col_letter: str, value: str) -> None:
        self._append_jsonl(
            self.ticket_updates_path,
            {"type": "cell", "row_number": row_number, "col": col_letter, "value": value},
        )

    def color_source_cells(self, row_number: int, source_type: str) -> None:
        self._append_jsonl(
            self.ticket_updates_path,
            {"type": "color", "row_number": row_number, "source_type": source_type},
        )

    def _next_ticket_row_number(self) -> int:
        if not self.tickets_path.exists():
            return 2
        rows = [
            json.loads(line)
            for line in self.tickets_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        data_rows = [row for row in rows if row.get("type") == "row"]
        return len(data_rows) + 2

    def _write_once(self, path: Path, payload: dict[str, Any]) -> None:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return
        self._append_jsonl(path, payload)

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
