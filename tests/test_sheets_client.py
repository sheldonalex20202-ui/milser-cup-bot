from app.sheets.client import GoogleSheetsClient
from app.sheets.rows import MESSAGES_COLUMNS
from app.sheets.ticket_rows import TICKET_COLUMNS


class FakeRequest:
    def __init__(self, action):
        self._action = action

    def execute(self):
        return self._action()


class FakeValuesApi:
    def __init__(self, owner):
        self.owner = owner

    def get(self, spreadsheetId, range, majorDimension=None):
        def action():
            self.owner.values_get_calls += 1
            failures_left = self.owner.failures.get(("values.get", range), 0)
            if failures_left > 0:
                self.owner.failures[("values.get", range)] = failures_left - 1
                raise RuntimeError(f"transient failure for {range}")
            if range.endswith("!A1:W1"):
                return {"values": [MESSAGES_COLUMNS]}
            if range.endswith("!A1:J1"):
                return {"values": [TICKET_COLUMNS]}
            return {"values": []}

        return FakeRequest(action)

    def update(self, spreadsheetId, range, valueInputOption, body):
        def action():
            self.owner.values_update_calls += 1
            return {"updatedRange": range}

        return FakeRequest(action)

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        def action():
            return {"updates": {"updatedRange": range}}

        return FakeRequest(action)


class FakeSpreadsheetsApi:
    def __init__(self, owner):
        self.owner = owner
        self._values = FakeValuesApi(owner)

    def get(self, spreadsheetId, fields):
        def action():
            self.owner.sheet_get_calls += 1
            failures_left = self.owner.failures.get(("spreadsheets.get", fields), 0)
            if failures_left > 0:
                self.owner.failures[("spreadsheets.get", fields)] = failures_left - 1
                raise RuntimeError(f"transient failure for {fields}")
            return {"sheets": [{"properties": {"title": "Messages", "sheetId": 1}}, {"properties": {"title": "Tickets", "sheetId": 2}}]}

        return FakeRequest(action)

    def values(self):
        return self._values

    def batchUpdate(self, spreadsheetId, body):
        def action():
            self.owner.batch_update_calls += 1
            return {"replies": []}

        return FakeRequest(action)


class FakeService:
    def __init__(self):
        self.failures = {}
        self.sheet_get_calls = 0
        self.values_get_calls = 0
        self.values_update_calls = 0
        self.batch_update_calls = 0
        self._spreadsheets = FakeSpreadsheetsApi(self)

    def spreadsheets(self):
        return self._spreadsheets


def make_client(fake_service: FakeService) -> GoogleSheetsClient:
    client = GoogleSheetsClient.__new__(GoogleSheetsClient)
    client.service = fake_service
    client.spreadsheet_id = "sheet-id"
    client.append_range = "Messages!A:W"
    client.sheet_name = "Messages"
    client.tickets_sheet_name = "Tickets"
    client.tickets_append_range = "Tickets!A:J"
    client._tickets_sheet_id = None
    return client


def test_ensure_messages_header_retries_transient_failures():
    service = FakeService()
    service.failures[("spreadsheets.get", "sheets.properties.title")] = 1
    service.failures[("values.get", "Messages!A1:W1")] = 1
    client = make_client(service)

    client.ensure_messages_header()

    assert service.sheet_get_calls == 3
    assert service.values_get_calls == 2
    assert service.values_update_calls == 0


def test_ensure_tickets_header_retries_transient_failures():
    service = FakeService()
    service.failures[("spreadsheets.get", "sheets.properties.title")] = 1
    service.failures[("values.get", "Tickets!A1:J1")] = 1
    client = make_client(service)

    client.ensure_tickets_header()

    assert service.sheet_get_calls == 3
    assert service.values_get_calls == 2
    assert service.values_update_calls == 0
