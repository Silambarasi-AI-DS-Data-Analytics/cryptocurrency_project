"""Unit tests for config.py, focused on paths and CSV structure."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


class TestPaths(unittest.TestCase):
    """Paths must be project-relative and usable from any working directory."""

    def test_base_dir_is_the_project_folder(self):
        self.assertTrue(config.BASE_DIR.is_dir())
        self.assertEqual(config.BASE_DIR, Path(__file__).resolve().parent.parent)
        self.assertTrue((config.BASE_DIR / "config.py").is_file())

    def test_data_and_log_paths_are_inside_the_project(self):
        self.assertEqual(config.DATA_DIR.parent, config.BASE_DIR)
        self.assertEqual(config.LOGS_DIR.parent, config.BASE_DIR)

    def test_csv_and_log_paths_are_files_inside_their_folders(self):
        self.assertEqual(config.CSV_FILE_PATH.parent, config.DATA_DIR)
        self.assertEqual(config.CSV_FILE_PATH.name, "crypto_prices.csv")
        self.assertEqual(config.LOG_FILE_PATH.parent, config.LOGS_DIR)
        self.assertEqual(config.LOG_FILE_PATH.name, "tracker.log")

    def test_no_absolute_windows_path_is_hard_coded(self):
        """The module must not contain a literal drive path."""
        source = (config.BASE_DIR / "config.py").read_text(encoding="utf-8")
        self.assertNotIn(":\\", source.replace('Path("\\\\', ""))

    def test_paths_do_not_depend_on_the_current_directory(self):
        """Changing the working directory must not change the resolved paths."""
        original = config.CSV_FILE_PATH
        try:
            os.chdir(config.BASE_DIR.parent)
            import importlib

            reloaded = importlib.reload(config)
            self.assertEqual(reloaded.CSV_FILE_PATH, original)
        finally:
            os.chdir(config.BASE_DIR)
            import importlib

            importlib.reload(config)


class TestCsvStructure(unittest.TestCase):
    """The CSV layout must stay consistent across the project."""

    def test_headers(self):
        self.assertEqual(len(config.CSV_HEADERS), 7)
        for header in ("Timestamp", "Rank", "Coin", "Symbol", "Price", "24h Change", "Market Cap"):
            self.assertIn(header, config.CSV_HEADERS)

    def test_headers_have_no_duplicates(self):
        self.assertEqual(len(config.CSV_HEADERS), len(set(config.CSV_HEADERS)))

    def test_missing_value_placeholder_is_not_a_number(self):
        self.assertFalse(config.MISSING_VALUE.replace(".", "").isdigit())


class TestScrapingSettings(unittest.TestCase):
    """Core scraping settings."""

    def test_coinmarketcap_url(self):
        self.assertTrue(config.COINMARKETCAP_URL.startswith("https://"))
        self.assertIn("coinmarketcap.com", config.COINMARKETCAP_URL)

    def test_number_of_coins(self):
        self.assertEqual(config.NUM_COINS_TO_EXTRACT, 10)

    def test_timeouts_are_positive(self):
        self.assertGreater(config.PAGE_LOAD_TIMEOUT, 0)
        self.assertGreater(config.WEBDRIVER_WAIT_TIMEOUT, 0)

    def test_retry_settings(self):
        self.assertEqual(config.NAVIGATION_RETRIES, 3)
        self.assertGreaterEqual(config.NAVIGATION_RETRY_DELAY, 0)


class TestSelectors(unittest.TestCase):
    """Selectors must avoid the generated CSS class names CoinMarketCap changes."""

    def test_generated_class_names_are_not_used(self):
        generated = [".sc-", "sc-c3aa330e", "sc-97d6d2ca"]
        selectors = list(config.TABLE_SELECTORS) + list(config.ROW_SELECTORS)
        for values in config.CELL_SELECTORS.values():
            selectors.extend(values)

        for selector in selectors:
            for marker in generated:
                self.assertNotIn(marker, selector, f"{selector} uses a generated class")

    def test_every_field_has_a_selector(self):
        for field in ("rank", "name", "symbol", "price", "change", "market_cap"):
            self.assertIn(field, config.CELL_SELECTORS)
            self.assertTrue(config.CELL_SELECTORS[field])

    def test_column_positions_cover_every_mapped_field(self):
        self.assertEqual(
            sorted(config.DEFAULT_COLUMN_POSITIONS),
            sorted(config.COLUMN_HEADER_NAMES),
        )


if __name__ == "__main__":
    unittest.main()