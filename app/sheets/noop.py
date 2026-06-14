from typing import Any


class NoopGoogleSheetsClient:
    def ensure_messages_header(self) -> None:
        return None

    def ensure_tickets_header(self) -> None:
        return None

    def append_row(self, row: list[Any]) -> None:
        return None

    def append_ticket_row(self, row: list[Any]) -> int | None:
        return None

    def update_ticket_cell(self, row_number: int, col_letter: str, value: str) -> None:
        return None

    def color_source_cells(self, row_number: int, source_type: str) -> None:
        return None
