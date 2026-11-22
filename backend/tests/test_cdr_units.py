"""Unit tests for CDR direction, aggregation, and overnight/date filtering."""
import unittest
import sys
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.cdr import CDRRecord
from app.analytics.cdr_analytics import analyze_communication_direction, analyze_interactions, filter_records


def record(hour, caller="17123456", contact="17999999", duration=60):
    return CDRRecord(datetime=datetime(2026, 11, 2, hour), calling_number=caller, called_number=contact,
                     called_party_name="Synthetic contact", called_party_cid="10800000001", service="Voice",
                     duration="00h 01m 00s", duration_seconds=duration, called_number_freq=2)


class CdrAnalyticsTests(unittest.TestCase):
    def test_incoming_and_outgoing_counts_and_durations(self):
        records = [record(10), record(11, caller="17999999", contact="17123456", duration=30)]
        summary = analyze_communication_direction(records, "17123456")
        self.assertEqual(summary["total_interactions"], 2)
        self.assertEqual(summary["incoming"], {"count": 1, "duration_seconds": 30})
        self.assertEqual(summary["outgoing"], {"count": 1, "duration_seconds": 60})

    def test_overnight_filter_includes_both_sides_of_midnight(self):
        records = [record(23), record(1), record(2), record(12)]
        filtered = filter_records(records, "17123456", start_time=time(22), end_time=time(2))
        self.assertEqual([item.datetime.hour for item in filtered], [23, 1])

    def test_date_and_direction_filters_exclude_other_records(self):
        records = [record(10), record(11, caller="17999999", contact="17123456"), record(12, caller="17888888", contact="17777777")]
        filtered = filter_records(records, "17123456", start_date=date(2026, 11, 2), end_date=date(2026, 11, 2), direction="incoming")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].calling_number, "17999999")
        self.assertEqual(filter_records(records, "17123456", start_date=date(2026, 11, 3)), [])

    def test_contacts_aggregate_both_directions(self):
        contacts = analyze_interactions([record(10), record(11, caller="17999999", contact="17123456", duration=30)], "17123456")
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]["contact_number"], "17999999")
        self.assertEqual(contacts[0]["total_interactions"], 2)
        self.assertEqual(contacts[0]["total_duration_seconds"], 90)
        self.assertEqual(contacts[0]["average_duration_seconds"], 45)
