"""Safety tests for deletion of disposable integration databases."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration_tests.cleanup import remove_owned_database


class IntegrationCleanupSafetyTests(unittest.TestCase):
    run_id = "a" * 32

    def test_application_database_name_is_rejected(self):
        client = MagicMock()
        with self.assertRaises(RuntimeError):
            remove_owned_database(client, "acc_database", self.run_id)
        client.drop_database.assert_not_called()
        client.__getitem__.assert_not_called()

    def test_nonempty_database_without_matching_ownership_is_not_deleted(self):
        client = MagicMock()
        database = client.__getitem__.return_value
        database.list_collection_names.return_value = ["users"]
        database.integration_test_runs.find_one.return_value = None
        with self.assertRaises(RuntimeError):
            remove_owned_database(client, "acc_test_browser_example", self.run_id)
        client.drop_database.assert_not_called()

    def test_owned_database_is_deleted(self):
        client = MagicMock()
        database = client.__getitem__.return_value
        database.list_collection_names.return_value = ["integration_test_runs", "users"]
        database.integration_test_runs.find_one.return_value = {"_id": self.run_id}
        remove_owned_database(client, "acc_test_browser_example", self.run_id)
        client.drop_database.assert_called_once_with("acc_test_browser_example")

    def test_already_removed_database_is_a_safe_noop(self):
        client = MagicMock()
        client.__getitem__.return_value.list_collection_names.return_value = []
        remove_owned_database(client, "acc_test_browser_example", self.run_id)
        client.drop_database.assert_not_called()
