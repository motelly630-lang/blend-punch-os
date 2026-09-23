"""Campaign import dates: real XLSX upload/preview/confirm and row validation."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, uid

from datetime import date, datetime
from html.parser import HTMLParser
from io import BytesIO
import json
import unittest
from urllib.parse import unquote

from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904

from app.models.campaign import Campaign
from app.routers.import_campaigns import _convert, _parse_file
from app.services.campaign_service import CampaignValidationError


class ImportFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") in ("payload_json", "mapping_json"):
            self.fields[attrs["name"]] = attrs.get("value", "")


class CampaignImportDates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = client_for(make_user("admin", 1))

    def _get(self, name):
        db = SessionLocal()
        try:
            obj = db.query(Campaign).filter(Campaign.company_id == 1, Campaign.name == name).one_or_none()
            if obj is not None:
                db.expunge(obj)
            return obj
        finally:
            db.close()

    def test_xlsx_date_cells_survive_upload_preview_and_confirm(self):
        name = f"날짜서식{uid()}"
        book = Workbook()
        sheet = book.active
        sheet.append(["캠페인명", "시작일", "종료일", "셀러커미션"])
        sheet.append([name, datetime(2026, 11, 1), date(2026, 11, 7), 0.125])
        sheet["B2"].number_format = "yyyy-mm-dd"
        sheet["C2"].number_format = "yyyy-mm-dd"
        sheet["D2"].number_format = "0.0%"
        content = BytesIO()
        book.save(content)
        book.close()
        response = self.client.post("/campaigns/import/upload", files={
            "file": ("dates.xlsx", content.getvalue(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        self.assertEqual(response.status_code, 200)
        parser = ImportFields()
        parser.feed(response.text)
        preview = json.loads(parser.fields["payload_json"])
        self.assertEqual(preview["rows"][0][1:3], ["2026-11-01", "2026-11-07"])
        response = self.client.post("/campaigns/import/confirm", data=parser.fields)
        self.assertEqual(response.status_code, 302)
        saved = self._get(name)
        self.assertIsNotNone(saved)
        self.assertEqual((saved.start_date, saved.end_date), (date(2026, 11, 1), date(2026, 11, 7)))
        self.assertEqual(saved.seller_commission_rate, 0.125)
        self.assertEqual(saved.status, "planning")

    def test_1904_epoch_uses_decoded_dates_not_guessed_serials(self):
        book = Workbook()
        book.epoch = CALENDAR_MAC_1904
        book.active.append(["캠페인명", "시작일"])
        book.active.append(["가상공구", datetime(2026, 11, 1, 13, 30)])
        book.active["B2"].number_format = "yyyy-mm-dd hh:mm"
        content = BytesIO()
        book.save(content)
        book.close()
        _, rows = _parse_file(content.getvalue(), "dates.xlsx")
        self.assertEqual(rows[0][1], "2026-11-01")

    def test_invalid_and_reversed_dates_reject_only_affected_rows(self):
        names = [f"날짜검증{uid()}" for _ in range(5)]
        payload = {"headers": ["캠페인명", "시작일", "종료일"], "rows": [
            [names[0], "2026-02-30", "2026-03-05"],
            [names[1], "2026-11-07", "2026-11-01"],
            [names[2], "", ""],
            [names[3], "2026/11/01", "2026.11.07"],
            [names[4], "2026-11-01", "일정 오타"],
        ]}
        response = self.client.post("/campaigns/import/confirm", data={
            "payload_json": json.dumps(payload),
            "mapping_json": json.dumps({"0": "name", "1": "start_date", "2": "end_date"})})
        self.assertEqual(response.status_code, 302)
        message = unquote(response.headers["location"])
        self.assertIn("2개 캠페인 등록", message)
        self.assertIn("3개 건너뜀", message)
        self.assertIn("오류 3행", message)
        for index in (0, 1, 4):
            self.assertIsNone(self._get(names[index]))
        undated = self._get(names[2])
        self.assertIsNotNone(undated)
        self.assertIsNone(undated.start_date)
        self.assertIsNone(undated.end_date)
        dated = self._get(names[3])
        self.assertEqual((dated.start_date, dated.end_date), (date(2026, 11, 1), date(2026, 11, 7)))

    def test_supported_date_text_and_explicit_missing_markers(self):
        for raw in ("2026-11-01", "2026/11/01", "2026.11.01", "11/01/2026"):
            self.assertEqual(_convert("start_date", raw), date(2026, 11, 1))
        self.assertEqual(_convert("start_date", "2028-02-29"), date(2028, 2, 29))
        for raw in ("", " ", "-", "None", "null", "n/a"):
            self.assertIsNone(_convert("start_date", raw))
        for raw in ("2026-02-29", "46200", "2026-13-01", "2026-11-01 garbage"):
            with self.subTest(raw=raw), self.assertRaises(CampaignValidationError):
                _convert("start_date", raw)
