"""Unit tests for csv_handler.py.

Every test writes into a temporary folder, so the real data/crypto_prices.csv
history and logs/tracker.log are never touched.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import csv_handler
from config import CSV_HEADERS, MISSING_VALUE, TIMESTAMP_FORMAT


def make_record(rank="1", coin="Sample Coin", price="$1,234.56"):
    """Build a record with obviously synthetic values for testing only."""
    return {
        "Timestamp": "2026-10-03 10:00:00",
        "Rank": rank,
        "Coin": coin,
        "Symbol": "SMP",
        "Price": price,
        "24h Change": "-1.20%",
        "Market Cap": "$5.5B",
    }


class CsvHandlerTestCase(unittest.TestCase):
    """Base class that redirects the CSV into a temporary directory."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name) / "data"
        self.csv_path = self.data_dir / "crypto_prices.csv"

        self.patches = [
            mock.patch.object(csv_handler, "DATA_DIR", self.data_dir),
            mock.patch.object(csv_handler, "CSV_FILE_PATH", self.csv_path),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.temp_dir.cleanup()


class TestCreateOrAppendCsv(CsvHandlerTestCase):
    """Tests for creating and appending to the historical CSV."""

    def test_data_directory_is_created_automatically(self):
        self.assertFalse(self.data_dir.exists())
        self.assertTrue(csv_handler.create_or_append_csv([make_record()]))
        self.assertTrue(self.data_dir.is_dir())

    def test_csv_is_created_with_headers(self):
        self.assertTrue(csv_handler.create_or_append_csv([make_record()]))
        self.assertTrue(self.csv_path.exists())

        frame = pd.read_csv(self.csv_path)
        self.assertEqual(list(frame.columns), CSV_HEADERS)
        self.assertEqual(len(frame), 1)

    def test_records_are_appended_and_history_is_kept(self):
        csv_handler.create_or_append_csv([make_record(rank="1", coin="First")])
        csv_handler.create_or_append_csv([make_record(rank="2", coin="Second")])

        frame = pd.read_csv(self.csv_path)
        self.assertEqual(len(frame), 2)
        self.assertEqual(list(frame["Coin"]), ["First", "Second"])

    def test_headers_are_not_repeated_on_append(self):
        csv_handler.create_or_append_csv([make_record(rank="1")])
        csv_handler.create_or_append_csv([make_record(rank="2")])

        content = self.csv_path.read_text(encoding="utf-8")
        self.assertEqual(content.count("Timestamp"), 1)

    def test_empty_existing_file_gets_headers(self):
        self.data_dir.mkdir(parents=True)
        self.csv_path.write_text("", encoding="utf-8")

        self.assertTrue(csv_handler.create_or_append_csv([make_record()]))

        frame = pd.read_csv(self.csv_path)
        self.assertEqual(list(frame.columns), CSV_HEADERS)
        self.assertEqual(len(frame), 1)

    def test_empty_input_is_rejected(self):
        self.assertFalse(csv_handler.create_or_append_csv([]))
        self.assertFalse(self.csv_path.exists())

    def test_missing_columns_are_filled_with_placeholder(self):
        record = make_record()
        del record["Market Cap"]

        self.assertTrue(csv_handler.create_or_append_csv([record]))

        # keep_default_na=False so the literal placeholder stays visible
        frame = pd.read_csv(self.csv_path, keep_default_na=False)
        self.assertEqual(list(frame.columns), CSV_HEADERS)
        self.assertEqual(frame.iloc[0]["Market Cap"], MISSING_VALUE)

    def test_extra_columns_are_dropped(self):
        record = make_record()
        record["Unexpected"] = "value"

        self.assertTrue(csv_handler.create_or_append_csv([record]))

        frame = pd.read_csv(self.csv_path)
        self.assertNotIn("Unexpected", frame.columns)

    def test_timestamp_column_is_preserved(self):
        self.assertTrue(csv_handler.create_or_append_csv([make_record()]))
        frame = pd.read_csv(self.csv_path)
        self.assertIn("Timestamp", frame.columns)
        self.assertTrue(str(frame.iloc[0]["Timestamp"]).startswith("2026-10-03"))

    def test_write_failure_is_reported(self):
        # A directory where the CSV file should be makes writing fail
        self.data_dir.mkdir(parents=True)
        self.csv_path.mkdir()

        self.assertFalse(csv_handler.create_or_append_csv([make_record()]))


class TestReadHistoricalData(CsvHandlerTestCase):
    """Tests for reading the stored history."""

    def test_missing_file_returns_none(self):
        self.assertIsNone(csv_handler.read_historical_data())

    def test_reads_stored_records(self):
        csv_handler.create_or_append_csv([make_record(rank="1", coin="First")])
        csv_handler.create_or_append_csv([make_record(rank="2", coin="Second")])

        frame = csv_handler.read_historical_data()
        self.assertIsNotNone(frame)
        self.assertEqual(len(frame), 2)

    def test_empty_file_returns_none(self):
        self.data_dir.mkdir(parents=True)
        self.csv_path.write_text("", encoding="utf-8")
        self.assertIsNone(csv_handler.read_historical_data())

    def test_unreadable_file_returns_none_and_is_not_deleted(self):
        """A parse failure must be reported without touching the stored file."""
        self.data_dir.mkdir(parents=True)
        self.csv_path.write_text("Timestamp,Rank\n2026-10-03 10:00:00,1\n", encoding="utf-8")

        with mock.patch.object(
            csv_handler.pd, "read_csv", side_effect=pd.errors.ParserError("broken file")
        ):
            self.assertIsNone(csv_handler.read_historical_data())

        self.assertTrue(self.csv_path.exists())
        self.assertIn("Timestamp", self.csv_path.read_text(encoding="utf-8"))


class TestGetCsvInfo(CsvHandlerTestCase):
    """Tests for the CSV info helper."""

    def test_missing_file(self):
        info = csv_handler.get_csv_info()
        self.assertFalse(info["exists"])
        self.assertEqual(info["rows"], 0)
        self.assertEqual(info["columns"], CSV_HEADERS)

    def test_existing_file(self):
        csv_handler.create_or_append_csv([make_record()])

        info = csv_handler.get_csv_info()
        self.assertTrue(info["exists"])
        self.assertEqual(info["rows"], 1)
        self.assertEqual(info["columns"], CSV_HEADERS)
        self.assertGreater(info["size_bytes"], 0)
        # Timestamp format is shared with the rest of the project
        self.assertRegex(info["last_modified"], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


class TestTimestampFormat(unittest.TestCase):
    """The timestamp format must be consistent across the project."""

    def test_format_matches_csv_content(self):
        from datetime import datetime

        stamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        self.assertRegex(stamp, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


if __name__ == "__main__":
    unittest.main()