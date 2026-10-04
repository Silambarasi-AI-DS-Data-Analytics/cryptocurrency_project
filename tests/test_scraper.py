"""Unit tests for scraper.py.

Selenium and the network are replaced by small fake objects, so these tests run
offline and quickly. No real market data is used anywhere in this file.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selenium.common.exceptions import TimeoutException, WebDriverException

from config import DEFAULT_COLUMN_POSITIONS, MISSING_VALUE
from scraper import CryptoScraper


class FakeCell:
    """Stand-in for a Selenium WebElement that only carries text."""

    def __init__(self, text):
        self.text = text


class FakeRow:
    """
    Stand-in for a table row.

    ``cells`` is a list of cell texts in column order, matching how CoinMarketCap
    renders a row: star, rank, name, price, 1h, 24h, 7d, market cap, ...
    """

    def __init__(self, cells, name=None, symbol=None):
        self.cells = cells
        self.name = name
        self.symbol = symbol
        self.text = " ".join(str(cell) for cell in cells if cell)

    def find_elements(self, by, selector):
        """Support only the selectors the scraper actually uses."""
        if selector.startswith("td:nth-child("):
            index = int(selector[len("td:nth-child("):-1])
            if 1 <= index <= len(self.cells):
                value = self.cells[index - 1]
                return [FakeCell(value)] if value else []
            return []
        if selector == "p.coin-item-name":
            return [FakeCell(self.name)] if self.name else []
        if selector == "p.coin-item-symbol":
            return [FakeCell(self.symbol)] if self.symbol else []
        if selector == "p.coin-item-name, a.cmc-link":
            return [FakeCell(self.name)] if self.name else []
        return []


class FakeDriver:
    """Stand-in for the Chrome WebDriver used by the navigation helpers."""

    def __init__(self, failures=None, visible_text="", headers=None, elements=None):
        self.failures = list(failures or [])
        self.visible_text = visible_text
        self.headers = headers or []
        self.elements = elements or {}
        self.calls = 0
        self.quit_called = False

    def get(self, url):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)

    def execute_script(self, script, *args):
        return self.headers

    def find_element(self, by, value):
        return FakeCell(self.visible_text)

    def find_elements(self, by, selector):
        """Return fake elements only for the selectors registered in elements."""
        return self.elements.get(selector, [])

    def quit(self):
        self.quit_called = True


def build_row(rank, name, symbol, price, change_24h, market_cap):
    """Build a FakeRow using the real current CoinMarketCap column layout."""
    return FakeRow(
        cells=[
            "",                 # 1: watchlist star
            rank,               # 2: rank
            f"{name}\n{symbol}\nBuy",  # 3: name + symbol + button
            price,              # 4: price
            "0.10%",            # 5: 1h
            change_24h,         # 6: 24h
            "1.00%",            # 7: 7d
            market_cap,         # 8: market cap
            "$1.00B",           # 9: volume
        ],
        name=name,
        symbol=symbol,
    )


class TestCleanText(unittest.TestCase):
    """Tests for text normalisation."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)

    def test_whitespace_is_collapsed(self):
        self.assertEqual(self.scraper._clean_text("  Bitcoin\n  BTC  "), "Bitcoin BTC")

    def test_empty_values_become_placeholder(self):
        for value in ("", "   ", "-", None):
            self.assertEqual(self.scraper._clean_text(value), MISSING_VALUE)


class TestExtractCoinAndSymbol(unittest.TestCase):
    """Tests for splitting a combined name cell."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)

    def test_symbol_is_split_off(self):
        self.assertEqual(
            self.scraper._extract_coin_and_symbol("Bitcoin BTC"),
            ("Bitcoin", "BTC"),
        )

    def test_button_label_is_removed(self):
        self.assertEqual(
            self.scraper._extract_coin_and_symbol("Bitcoin BTC Buy"),
            ("Bitcoin", "BTC"),
        )

    def test_name_without_symbol_is_kept(self):
        self.assertEqual(
            self.scraper._extract_coin_and_symbol("Bitcoin"),
            ("Bitcoin", MISSING_VALUE),
        )

    def test_missing_name(self):
        self.assertEqual(
            self.scraper._extract_coin_and_symbol(MISSING_VALUE),
            (MISSING_VALUE, MISSING_VALUE),
        )


class TestCleanErrorMessage(unittest.TestCase):
    """The chromedriver stacktrace must not reach the user."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)

    def test_stacktrace_and_session_info_are_removed(self):
        raw = (
            "Message: unknown error: net::ERR_CONNECTION_TIMED_OUT\n"
            "  (Session info: chrome=149.0.0.1)\n"
            "Stacktrace:\n\tchromedriver!GetHandleVerifier [0x7ff7]\n\tntdll!RtlUserThreadStart"
        )
        cleaned = self.scraper._clean_error_message(WebDriverException(raw))

        self.assertNotIn("Stacktrace", cleaned)
        self.assertNotIn("Session info", cleaned)
        self.assertNotIn("chromedriver", cleaned)
        self.assertIn("net::ERR_CONNECTION_TIMED_OUT", cleaned)

    def test_none_error(self):
        self.assertEqual(self.scraper._clean_error_message(None), "unknown error")


class TestNavigationRetry(unittest.TestCase):
    """Tests for the retry logic around driver.get(). No network involved."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)

    def test_successful_navigation_does_not_retry(self):
        driver = FakeDriver()
        self.scraper.driver = driver

        self.scraper._navigate_with_retry("https://example.invalid", retries=3, delay=0)

        self.assertEqual(driver.calls, 1)

    def test_recovers_after_transient_failures(self):
        driver = FakeDriver(failures=[
            WebDriverException("net::ERR_CONNECTION_TIMED_OUT"),
            TimeoutException("page load timed out"),
        ])
        self.scraper.driver = driver

        self.scraper._navigate_with_retry("https://example.invalid", retries=3, delay=0)

        self.assertEqual(driver.calls, 3)

    def test_gives_up_after_the_configured_attempts(self):
        driver = FakeDriver(failures=[TimeoutException("timed out")] * 5)
        self.scraper.driver = driver

        with self.assertRaises(WebDriverException) as context:
            self.scraper._navigate_with_retry("https://example.invalid", retries=3, delay=0)

        message = str(context.exception)
        self.assertEqual(driver.calls, 3)
        self.assertIn("https://example.invalid", message)
        self.assertIn("3 attempts", message)
        self.assertIn("timed out", message)

    def test_driver_is_closed_before_the_error_is_raised(self):
        driver = FakeDriver(failures=[TimeoutException("timed out")] * 3)
        self.scraper.driver = driver

        with self.assertRaises(WebDriverException):
            self.scraper._navigate_with_retry("https://example.invalid", retries=3, delay=0)

        self.assertTrue(driver.quit_called)
        self.assertIsNone(self.scraper.driver)


class TestBlockPageDetection(unittest.TestCase):
    """Protection pages must be reported, never bypassed."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)

    def test_visible_block_message_is_detected(self):
        self.scraper.driver = FakeDriver(
            visible_text="Our systems have detected unusual traffic from your computer network."
        )
        self.assertTrue(self.scraper._check_for_block_page())

    def test_challenge_element_is_detected(self):
        self.scraper.driver = FakeDriver(
            visible_text="normal page",
            elements={"#challenge-form": [FakeCell("")]},
        )
        self.assertTrue(self.scraper._check_for_block_page())

    def test_normal_page_is_not_flagged(self):
        self.scraper.driver = FakeDriver(visible_text="Bitcoin BTC $84,653.63")
        self.assertFalse(self.scraper._check_for_block_page())

    def test_javascript_translation_strings_do_not_trigger_a_false_positive(self):
        """
        CoinMarketCap ships the sentence "Our systems have detected unusual
        traffic" inside its JavaScript bundles. That must not look like a block.
        """
        self.scraper.driver = FakeDriver(
            visible_text="Bitcoin BTC $84,653.63 Ethereum ETH $2,681.04"
        )
        self.assertFalse(self.scraper._check_for_block_page())


class TestColumnDetection(unittest.TestCase):
    """Column positions are read from the real header row when available."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)

    def test_positions_are_detected_from_headers(self):
        self.scraper.driver = FakeDriver(
            headers=["", "#", "Name", "Price", "1h %", "24h %", "7d %", "Market Cap"]
        )

        positions = self.scraper._detect_column_positions()

        self.assertEqual(positions["rank"], 2)
        self.assertEqual(positions["name"], 3)
        self.assertEqual(positions["price"], 4)
        self.assertEqual(positions["change"], 6)
        self.assertEqual(positions["market_cap"], 8)

    def test_extra_columns_are_handled(self):
        """A new leading column must shift every position."""
        self.scraper.driver = FakeDriver(
            headers=["Watchlist", "#", "Name", "Price", "1h %", "24h %", "Market Cap"]
        )

        positions = self.scraper._detect_column_positions()

        self.assertEqual(positions["rank"], 2)
        self.assertEqual(positions["market_cap"], 7)

    def test_defaults_are_used_when_headers_are_missing(self):
        self.scraper.driver = FakeDriver(headers=[])

        positions = self.scraper._detect_column_positions()

        self.assertEqual(positions, DEFAULT_COLUMN_POSITIONS)


class TestExtractCryptoData(unittest.TestCase):
    """Tests for building records out of table rows."""

    def setUp(self):
        self.scraper = CryptoScraper(headless=True)
        self.scraper.column_positions = dict(DEFAULT_COLUMN_POSITIONS)

    def test_fields_are_taken_from_the_right_columns(self):
        row = build_row("1", "Alpha One", "A1", "$1,234.56", "-1.20%", "$5.5B")

        records = self.scraper._extract_crypto_data([row])

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["Rank"], "1")
        self.assertEqual(record["Coin"], "Alpha One")
        self.assertEqual(record["Symbol"], "A1")
        self.assertEqual(record["Price"], "$1,234.56")
        self.assertEqual(record["24h Change"], "-1.20%")
        self.assertEqual(record["Market Cap"], "$5.5B")

    def test_promotional_row_without_rank_is_skipped(self):
        promo = FakeRow(cells=["", "", "Promo Token\nPROMO\nBuy", "$1.00", "0.10%", "0.20%"])
        real = build_row("1", "Alpha One", "A1", "$1.00", "0.10%", "$1.0B")

        records = self.scraper._extract_crypto_data([promo, real])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["Coin"], "Alpha One")

    def test_duplicate_rows_are_removed(self):
        first = build_row("1", "Alpha One", "A1", "$1.00", "0.10%", "$1.0B")
        duplicate = build_row("2", "Alpha One", "A1", "$1.00", "0.10%", "$1.0B")

        records = self.scraper._extract_crypto_data([first, duplicate])

        self.assertEqual(len(records), 1)

    def test_all_records_share_one_timestamp(self):
        rows = [
            build_row("1", "Alpha One", "A1", "$1.00", "0.10%", "$1.0B"),
            build_row("2", "Beta Two", "B2", "$2.00", "0.20%", "$2.0B"),
        ]

        records = self.scraper._extract_crypto_data(rows)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["Timestamp"], records[1]["Timestamp"])

    def test_only_the_configured_number_of_coins_is_returned(self):
        rows = [
            build_row(str(index), f"Coin {index}", f"C{index}", "$1.00", "0.10%", "$1.0B")
            for index in range(1, 30)
        ]

        records = self.scraper._extract_crypto_data(rows)

        self.assertEqual(len(records), 10)
        self.assertEqual(records[0]["Rank"], "1")
        self.assertEqual(records[-1]["Rank"], "10")

    def test_missing_price_is_reported_as_placeholder(self):
        row = FakeRow(
            cells=["", "1", "Alpha One\nA1\nBuy", "", "0.10%", "0.20%", "$1.0B"],
            name="Alpha One",
            symbol="A1",
        )

        records = self.scraper._extract_crypto_data([row])

        self.assertEqual(records[0]["Price"], MISSING_VALUE)

    def test_empty_row_list(self):
        self.assertEqual(self.scraper._extract_crypto_data([]), [])


if __name__ == "__main__":
    unittest.main()