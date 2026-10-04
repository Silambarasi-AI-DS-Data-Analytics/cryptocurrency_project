"""Unit tests for validation.py.

These tests use clearly synthetic marker values (not real market data) and never
touch the network.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CSV_HEADERS, MISSING_VALUE
from validation import (
    parse_number,
    parse_percentage,
    validate_crypto_data,
    validate_record,
)


def make_record(**overrides):
    """Build a valid record that individual tests can break on purpose."""
    record = {
        "Timestamp": "2026-10-03 10:00:00",
        "Rank": "1",
        "Coin": "Sample Coin",
        "Symbol": "SMP",
        "Price": "$1,234.56",
        "24h Change": "-1.20%",
        "Market Cap": "$5.5B",
    }
    record.update(overrides)
    return record


class TestParseNumber(unittest.TestCase):
    """Tests for the number parser."""

    def test_currency_and_separators(self):
        self.assertAlmostEqual(parse_number("$1,234.56"), 1234.56)
        self.assertAlmostEqual(parse_number("$0.00008123"), 0.00008123)

    def test_large_number_suffixes(self):
        self.assertAlmostEqual(parse_number("$5.5B"), 5.5e9)
        self.assertAlmostEqual(parse_number("$1.7T"), 1.7e12)
        self.assertAlmostEqual(parse_number("35.89K"), 35890.0)

    def test_plain_numbers(self):
        self.assertAlmostEqual(parse_number(42), 42.0)
        self.assertAlmostEqual(parse_number("42"), 42.0)
        self.assertAlmostEqual(parse_number(-7), -7.0)

    def test_unparseable_values_return_none(self):
        self.assertIsNone(parse_number(MISSING_VALUE))
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number(None))
        self.assertIsNone(parse_number("not a number"))
        self.assertIsNone(parse_number(True))


class TestParsePercentage(unittest.TestCase):
    """Tests for the percentage parser."""

    def test_percentages(self):
        self.assertAlmostEqual(parse_percentage("0.04%"), 0.04)
        self.assertAlmostEqual(parse_percentage("-1.20%"), -1.20)
        self.assertAlmostEqual(parse_percentage("+5.5%"), 5.5)

    def test_unparseable_values_return_none(self):
        self.assertIsNone(parse_percentage(MISSING_VALUE))
        self.assertIsNone(parse_percentage(""))
        self.assertIsNone(parse_percentage("n/a"))


class TestValidateRecord(unittest.TestCase):
    """Tests for single record validation."""

    def test_valid_record_passes(self):
        is_valid, problems = validate_record(make_record())
        self.assertTrue(is_valid, f"unexpected problems: {problems}")
        self.assertEqual(problems, [])

    def test_all_expected_columns_are_required(self):
        record = make_record()
        del record["Market Cap"]
        is_valid, problems = validate_record(record)
        self.assertFalse(is_valid)
        self.assertTrue(any("Market Cap" in problem for problem in problems))

    def test_rank_must_be_numeric_and_positive(self):
        for bad_rank in (MISSING_VALUE, "", "abc", "0", "-3"):
            is_valid, problems = validate_record(make_record(Rank=bad_rank))
            self.assertFalse(is_valid, f"rank {bad_rank!r} should be rejected")
            self.assertTrue(any("rank" in problem for problem in problems))

    def test_name_must_not_be_empty(self):
        for bad_name in (MISSING_VALUE, "", "   ", None):
            is_valid, problems = validate_record(make_record(Coin=bad_name))
            self.assertFalse(is_valid)
            self.assertTrue(any("name" in problem for problem in problems))

    def test_symbol_must_not_be_empty(self):
        is_valid, problems = validate_record(make_record(Symbol=MISSING_VALUE))
        self.assertFalse(is_valid)
        self.assertTrue(any("symbol" in problem for problem in problems))

    def test_non_numeric_price_is_rejected(self):
        is_valid, problems = validate_record(make_record(Price="free"))
        self.assertFalse(is_valid)
        self.assertTrue(any("price" in problem for problem in problems))

    def test_non_numeric_market_cap_is_rejected(self):
        is_valid, problems = validate_record(make_record(**{"Market Cap": "unknown"}))
        self.assertFalse(is_valid)
        self.assertTrue(any("market cap" in problem for problem in problems))

    def test_missing_optional_values_are_allowed(self):
        is_valid, problems = validate_record(
            make_record(**{"Market Cap": MISSING_VALUE, "24h Change": MISSING_VALUE})
        )
        self.assertTrue(is_valid, f"unexpected problems: {problems}")

    def test_invalid_percentage_is_rejected(self):
        is_valid, _ = validate_record(make_record(**{"24h Change": "up a bit"}))
        self.assertFalse(is_valid)


class TestValidateCryptoData(unittest.TestCase):
    """Tests for validating a whole scrape."""

    def test_duplicates_within_one_scrape_are_removed(self):
        records = [
            make_record(Rank="1", Coin="Alpha One", Symbol="A1"),
            make_record(Rank="2", Coin="Beta Two", Symbol="B2"),
            make_record(Rank="3", Coin="alpha one", Symbol="A1"),
        ]
        valid, invalid = validate_crypto_data(records, log_invalid=False)
        self.assertEqual([record["Coin"] for record in valid], ["Alpha One", "Beta Two"])
        self.assertEqual(invalid, [])

    def test_invalid_records_are_separated_out(self):
        records = [
            make_record(Rank="1", Coin="Alpha One"),
            make_record(Rank="2", Coin="", Symbol="B2"),
            make_record(Rank="3", Coin="Gamma Three", Price="free"),
        ]
        valid, invalid = validate_crypto_data(records, log_invalid=False)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(invalid), 2)

    def test_empty_input_is_handled(self):
        valid, invalid = validate_crypto_data([], log_invalid=False)
        self.assertEqual(valid, [])
        self.assertEqual(invalid, [])

    def test_none_input_is_handled(self):
        valid, invalid = validate_crypto_data(None, log_invalid=False)
        self.assertEqual(valid, [])
        self.assertEqual(invalid, [])

    def test_original_order_is_preserved(self):
        records = [
            make_record(Rank="3", Coin="Gamma Three"),
            make_record(Rank="1", Coin="Alpha One"),
            make_record(Rank="2", Coin="Beta Two"),
        ]
        valid, _ = validate_crypto_data(records, log_invalid=False)
        self.assertEqual([record["Coin"] for record in valid],
                         ["Gamma Three", "Alpha One", "Beta Two"])

    def test_no_values_are_invented(self):
        """A rejected record must keep its original text, never a made-up number."""
        records = [make_record(Rank="not a rank", Coin="Alpha One")]
        valid, invalid = validate_crypto_data(records, log_invalid=False)
        self.assertEqual(valid, [])
        self.assertEqual(invalid[0]["Rank"], "not a rank")

    def test_all_columns_present_in_output(self):
        valid, _ = validate_crypto_data([make_record()], log_invalid=False)
        for header in CSV_HEADERS:
            self.assertIn(header, valid[0])


if __name__ == "__main__":
    unittest.main()