"""Command line entry point of the Cryptocurrency Price Tracker.

Flow:
    parse CLI arguments -> configure logging -> scrape live data -> validate
    -> optional filters -> display -> append to CSV -> close Selenium

Run it with::

    python main.py
    python main.py --headless
    python main.py --headless --min-change 3
"""

import argparse
import sys
from typing import Any, Dict, List, Optional

import pandas as pd

from config import CSV_HEADERS, HEADLESS, LOG_FILE_PATH
from csv_handler import (
    create_or_append_csv,
    get_csv_info,
    read_historical_data,
    setup_logging,
)
from filters import CryptoFilter, apply_filters
from scraper import scrape_crypto_prices
from validation import validate_crypto_data

logger = setup_logging()


def _readable_error(error: Exception) -> str:
    """
    Turn an exception into a short single-line message for the console.

    Selenium adds a "Message:" prefix and a long chromedriver stacktrace, which
    are not useful in the summary.

    Args:
        error (Exception): The exception that ended the run.

    Returns:
        str: A cleaned, single-line description.
    """
    message = str(error).split("Stacktrace:")[0]
    message = message.replace("Message:", "").replace("(Session info:", "(")
    return " ".join(message.split()) or "Unknown error"


class CryptoPriceTracker:
    """
    Runs one complete tracking cycle: scrape, validate, filter, save.
    """

    def __init__(self, headless: bool = HEADLESS):
        """
        Initialize the tracker.

        Args:
            headless (bool): Whether Chrome runs without a visible window.
        """
        self.headless = headless
        self.scraped_data: List[Dict[str, str]] = []

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def display_banner(self) -> None:
        """Print the application title."""
        print("\n" + "=" * 60)
        print("      CRYPTOCURRENCY PRICE TRACKER")
        print("=" * 60)
        print(f"  Source: CoinMarketCap   Mode: {'headless' if self.headless else 'visible'}")
        print()

    def display_results(self, data: List[Dict[str, str]]) -> None:
        """
        Print the scraped records as a table.

        Args:
            data (List[Dict[str, str]]): Scraped records.
        """
        if not data:
            print("  No data to display.")
            return

        print("-" * 78)
        print(f"{'Rank':<6}{'Coin':<22}{'Symbol':<9}{'Price':<16}{'24h Change':<13}{'Market Cap':<12}")
        print("-" * 78)

        for coin in data:
            rank = coin.get("Rank", "N/A")
            coin_name = coin.get("Coin", "N/A")
            if len(coin_name) > 21:
                coin_name = coin_name[:18] + "..."
            print(
                f"{rank:<6}{coin_name:<22}{coin.get('Symbol', 'N/A'):<9}"
                f"{coin.get('Price', 'N/A'):<16}{coin.get('24h Change', 'N/A'):<13}"
                f"{coin.get('Market Cap', 'N/A'):<12}"
            )

        print("-" * 78)
        print()

    def display_completion(self, success: bool, record_count: int, message: str = "") -> None:
        """
        Print the closing summary.

        Args:
            success (bool): Whether the run finished successfully.
            record_count (int): Number of records that were processed.
            message (str): Extra information, for example the failure reason.
        """
        print("=" * 78)
        if success:
            print("             TRACKING COMPLETE")
            print()
            print(f"  [SUCCESS] {record_count} records scraped and appended to the CSV history.")
        else:
            print("             TRACKING FAILED")
            print()
            print(f"  [ERROR] {message or 'The tracking run could not be completed.'}")
        print(f"  [INFO] Log file: {LOG_FILE_PATH}")
        print("=" * 78)
        print()

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------
    def run(
        self,
        apply_filters_flag: bool = False,
        filter_kwargs: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Run one full tracking cycle.

        Args:
            apply_filters_flag (bool): Whether filters should be applied.
            filter_kwargs (Optional[Dict[str, Any]]): Filter parameters.

        Returns:
            bool: True on success, False when the run failed.
        """
        self.display_banner()
        filter_kwargs = filter_kwargs or {}

        try:
            logger.info("Starting cryptocurrency price tracker...")
            print("[INFO] Starting scraper...")

            # 1. Scrape live data
            scraped = scrape_crypto_prices(headless=self.headless)

            if not scraped:
                logger.error("No data was extracted from CoinMarketCap")
                self.display_completion(
                    False, 0, "No data could be extracted from CoinMarketCap."
                )
                return False

            print(f"[INFO] Scraped {len(scraped)} records. Validating...")
            logger.info(f"Scraped {len(scraped)} raw records from CoinMarketCap")

            # 2. Validate before anything is stored
            valid_records, rejected = validate_crypto_data(scraped)
            if rejected:
                print(f"[WARNING] {len(rejected)} malformed record(s) were rejected.")
            if not valid_records:
                logger.error("Every scraped record failed validation")
                self.display_completion(
                    False, 0, "All scraped records failed validation, nothing was saved."
                )
                return False

            self.scraped_data = valid_records

            # 3. Show the live results
            self.display_results(self.scraped_data)

            # 4. Optional filtering of the freshly scraped data
            if apply_filters_flag:
                print("[INFO] Applying filters...")
                logger.info(f"Applying filters: {filter_kwargs}")
                filtered = apply_filters(pd.DataFrame(self.scraped_data), **filter_kwargs)
                CryptoFilter().print_filtered_data(filtered, "Filtered Scraped Data")

            # 5. Append to the historical CSV
            print("[INFO] Saving data to CSV history...")
            if not create_or_append_csv(self.scraped_data):
                logger.error("Saving the scraped records to CSV failed")
                self.display_completion(False, 0, "The CSV file could not be written.")
                return False

            csv_info = get_csv_info()
            print(f"[SUCCESS] CSV updated: {csv_info.get('rows', '?')} total rows stored.")
            logger.info(f"CSV now holds {csv_info.get('rows', '?')} rows in total")

            self.display_completion(True, len(self.scraped_data))
            logger.info(f"Tracking completed successfully with {len(self.scraped_data)} records")
            return True

        except KeyboardInterrupt:
            logger.warning("Tracking interrupted by the user")
            self.display_completion(False, 0, "Interrupted by the user.")
            return False
        except Exception as e:
            # main.py already logged the details; show a readable reason here
            logger.error(f"Tracking failed: {e}", exc_info=True)
            self.display_completion(False, 0, _readable_error(e))
            return False


def parse_arguments() -> argparse.Namespace:
    """
    Build the command line parser.

    Returns:
        argparse.Namespace: The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Cryptocurrency Price Tracker - scrape the current top "
            "cryptocurrencies from CoinMarketCap into a CSV history."
        )
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome in headless mode (no visible browser window)",
    )
    mode.add_argument(
        "--no-headless",
        action="store_true",
        help="Run Chrome with a visible browser window (for debugging)",
    )

    parser.add_argument("--min-price", type=float, help="Only show coins priced above this USD value")
    parser.add_argument("--max-price", type=float, help="Only show coins priced below this USD value")
    parser.add_argument("--min-change", type=float, help="Only show coins with 24h change above this percentage")
    parser.add_argument("--max-change", type=float, help="Only show coins with 24h change below this percentage")
    parser.add_argument("--coin", type=str, help="Only show coins whose name contains this text")
    parser.add_argument("--min-rank", type=int, help="Only show ranks from this number upwards")
    parser.add_argument("--max-rank", type=int, help="Only show ranks up to this number")

    parser.add_argument("--show-history", action="store_true", help="Print the stored CSV history and exit")
    parser.add_argument("--csv-info", action="store_true", help="Print CSV file details and exit")

    return parser.parse_args()


def _build_filter_kwargs(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Collect the filter arguments that were actually provided.

    Args:
        args (argparse.Namespace): Parsed command line arguments.

    Returns:
        Dict[str, Any]: Filter parameters for filters.apply_filters.
    """
    mapping = {
        "min_price": args.min_price,
        "max_price": args.max_price,
        "min_change": args.min_change,
        "max_change": args.max_change,
        "coin": args.coin,
        "min_rank": args.min_rank,
        "max_rank": args.max_rank,
    }
    return {key: value for key, value in mapping.items() if value is not None}


def _show_history() -> None:
    """Print every stored historical record."""
    history = read_historical_data()

    if history is None or history.empty:
        print("\n[INFO] No historical data found yet.\n")
        return

    columns = [column for column in CSV_HEADERS if column in history.columns]
    print("\n" + "=" * 100)
    print(f"  HISTORICAL DATA ({len(history)} records)")
    print("=" * 100)
    print(history[columns].to_string(index=False))
    print("=" * 100 + "\n")


def _show_csv_info() -> None:
    """Print details about the CSV file."""
    info = get_csv_info()

    print("\n" + "=" * 60)
    print("  CSV FILE INFORMATION")
    print("=" * 60)
    for key, value in info.items():
        print(f"  {key.replace('_', ' ').title()}: {value}")
    print("=" * 60 + "\n")


def main() -> None:
    """
    Program entry point. Exits with 0 on success and 1 on failure.
    """
    # Coin names may contain characters the Windows console cannot encode
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    try:
        args = parse_arguments()

        # Browser mode: flags win, otherwise fall back to config.HEADLESS
        if args.headless:
            headless_mode = True
        elif args.no_headless:
            headless_mode = False
        else:
            headless_mode = HEADLESS

        if args.csv_info:
            _show_csv_info()
            return

        if args.show_history:
            _show_history()
            return

        filter_kwargs = _build_filter_kwargs(args)
        tracker = CryptoPriceTracker(headless=headless_mode)
        success = tracker.run(
            apply_filters_flag=bool(filter_kwargs),
            filter_kwargs=filter_kwargs,
        )

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n[INFO] Operation cancelled by user.")
        logger.info("Application terminated by the user")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n[ERROR] Fatal error: {e}")
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()