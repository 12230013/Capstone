"""Unit tests for history cleanup, input validation, passwords, and UTC serialization."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from pydantic import ValidationError
from app.services.message_history import successful_exchanges
from app.schemas.user import UserCreate
from app.utils.security import hash_password, verify_password
from app.api.routes.validators import validate_target_number
from app.api.routes.conversations import serialize_datetime


class MessageHistoryTests(unittest.TestCase):
    def message(self, role, content, **extra):
        return {"role": role, "content": content, **extra}

    def test_legacy_failed_attempts_are_hidden(self):
        messages = [self.message("user", "Failed"), self.message("user", "Succeeded"),
                    self.message("assistant", "Answer"), self.message("user", "Another failure")]
        self.assertEqual([m["content"] for m in successful_exchanges(messages)], ["Succeeded", "Answer"])

    def test_interleaved_exchanges_keep_their_own_question(self):
        messages = [self.message("user", "A", exchange_id="a"), self.message("user", "B", exchange_id="b"),
                    self.message("assistant", "Answer B", exchange_id="b"), self.message("assistant", "Answer A", exchange_id="a")]
        self.assertEqual([m["content"] for m in successful_exchanges(messages)], ["B", "Answer B", "A", "Answer A"])

    def test_failed_and_pending_records_are_not_displayed(self):
        messages = [self.message("user", "Failed", status="failed"), self.message("user", "Pending", status="pending")]
        self.assertEqual(successful_exchanges(messages), [])

    def test_empty_or_orphan_assistant_messages_are_ignored(self):
        self.assertEqual(successful_exchanges([]), [])
        self.assertEqual(successful_exchanges([self.message("assistant", "Orphan")]), [])

    def test_distinct_successful_repeated_questions_are_preserved(self):
        messages = [self.message("user", "Same"), self.message("assistant", "First"),
                    self.message("user", "Same"), self.message("assistant", "Second")]
        self.assertEqual(len(successful_exchanges(messages)), 4)


class InputAndPasswordTests(unittest.TestCase):
    def valid_signup(self, **changes):
        data = dict(name="Test User", employee_id="acc-001", email="staff@example.com", role="Investigator",
                    department="Investigations", password="Password1!")
        data.update(changes)
        return data

    def test_employee_id_is_normalized(self):
        self.assertEqual(UserCreate(**self.valid_signup()).employee_id, "ACC-001")

    def test_invalid_signup_values_are_rejected(self):
        for changes in ({"password": "short"}, {"password": "password1!"}, {"password": "Password!"},
                        {"password": "Password1"}, {"email": "not-an-email"}, {"role": "Unknown"}, {"name": "User123"}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(ValidationError):
                    UserCreate(**self.valid_signup(**changes))

    def test_password_hash_is_salted_and_rejects_wrong_password(self):
        first = hash_password("Password1!")
        second = hash_password("Password1!")
        self.assertNotEqual(first, "Password1!")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("Password1!", first))
        self.assertFalse(verify_password("WrongPassword1!", first))

    def test_target_numbers_require_exactly_eight_ascii_digits(self):
        self.assertEqual(validate_target_number("17123456"), "17123456")
        non_ascii_digits = "".join(chr(0xFF10 + digit) for digit in range(1, 9))
        for number in ("123", "10808000040", "17abcdef", "1712 3456", non_ascii_digits):
            with self.subTest(number=number):
                with self.assertRaises(HTTPException) as error:
                    validate_target_number(number)
                self.assertEqual(error.exception.status_code, 400)

    def test_database_timestamps_are_serialized_as_utc(self):
        self.assertEqual(serialize_datetime(datetime(2026, 11, 2, 10, 30)), "2026-11-02T10:30:00Z")
        self.assertEqual(serialize_datetime(datetime(2026, 11, 2, tzinfo=timezone.utc)), "2026-11-02T00:00:00Z")
        self.assertIsNone(serialize_datetime(None))
