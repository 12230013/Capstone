"""Authenticated API tests for CDR and relationship services with mocked upstream APIs."""
from unittest.mock import AsyncMock, patch
import httpx
import test_security_and_grounding as fixtures
from test_cdr_units import record
from app.api.routes import cdr, relationship
from app.models.cdr import CDRSummaryResponse


class InvestigationApiTests(fixtures.ApiTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_cdr_summary_returns_derived_counts(self):
        records = [record(10), record(11, caller="17999999", contact="17123456", duration=30)]
        with patch.object(cdr.cdr_service, "get_summary", AsyncMock(return_value=CDRSummaryResponse(success=True, records=records))):
            response = self.client.get("/api/cdr/summary/17123456")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total_records"], 2)
        self.assertEqual(data["total_contacts"], 1)
        self.assertEqual(data["communication_direction"]["incoming"]["count"], 1)
        self.assertEqual(data["contact_frequency"][0]["total_duration_seconds"], 90)

    def test_invalid_cdr_number_is_rejected_before_upstream_request(self):
        with patch.object(cdr.cdr_service, "get_summary", AsyncMock()) as upstream:
            self.assertEqual(self.client.get("/api/cdr/summary/notdigits").status_code, 400)
        upstream.assert_not_called()

    def test_cdr_no_records_returns_not_found(self):
        with patch.object(cdr.cdr_service, "get_summary", AsyncMock(return_value=CDRSummaryResponse(success=True, records=[]))):
            self.assertEqual(self.client.get("/api/cdr/summary/17123456").status_code, 404)

    def test_cdr_upstream_timeout_and_connection_failure_are_normalized(self):
        for error, status in ((httpx.ReadTimeout("Stalled"), 504), (httpx.ConnectError("Offline"), 502)):
            with self.subTest(status=status), patch.object(cdr.cdr_service, "get_summary", AsyncMock(side_effect=error)):
                self.assertEqual(self.client.get("/api/cdr/summary/17123456").status_code, status)

    def test_cdr_incomplete_date_filter_is_rejected(self):
        with patch.object(cdr.cdr_service, "get_summary", AsyncMock()) as upstream:
            response = self.client.get("/api/cdr/records/17123456", params={"start_date": "2026-11-02"})
        self.assertEqual(response.status_code, 400)
        upstream.assert_not_called()

    def test_invalid_relationship_degree_is_rejected_before_upstream_request(self):
        with patch.object(relationship, "fetch_citizen", AsyncMock()) as upstream:
            self.assertEqual(self.client.get("/api/relationship/10808000040/4").status_code, 400)
        upstream.assert_not_called()

    def test_missing_citizen_returns_not_found(self):
        with patch.object(relationship, "fetch_citizen", AsyncMock(return_value=None)):
            self.assertEqual(self.client.get("/api/relationship/10808000040/1").status_code, 404)
