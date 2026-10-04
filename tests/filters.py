"""Filtering of cryptocurrency data.

The filters work on real scraped data only - no coin name is hard-coded here.
They are used in two ways:

* on the freshly scraped records (``python main.py --min-price 1000``)
* on the stored history through :class:`CryptoFilter`

Every filter returns ``None`` when there is nothing to work with (empty data or
a missing column) so the caller can report the situation instead of crashing.
"""

from typing import Any, Optional

import pandas as pd

from csv_handler import read_historical_data, setup_logging
from validation import parse_number, parse_percentage

logger = setup_logging()


class CryptoFilter:
    """
    Filter cryptocurrency records by price, 24h change, coin name or rank.
    """

    def __init__(self, data: Optional[pd.DataFrame] = None):
        """
        Initialize the filter.

        Args:
            data (Optional[pd.DataFrame]): Frame to filter. When omitted the
                historical CSV data is loaded.
        """
        self.data = data if data is not None else read_historical_data()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require_columns(self, *columns: str) -> bool:
        """
        Check that the data is usable and contains the needed columns.

        Args:
            *columns (str): Column names the filter depends on.

        Returns:
            bool: True when filtering can continue.
        """
        if self.data is None or self.data.empty:
            logger.warning("No data available for filtering")
            return False

        missing = [column for column in columns if column not in self.data.columns]
        if missing:
            logger.error(f"Cannot filter: missing column(s) {', '.join(missing)}")
            return False

        return True

    def _numeric_column(self, column: str, percentage: bool = False) -> pd.Series:
        """
        Convert a text column into numbers.

        Values that cannot be parsed become NaN, so numeric filters simply skip
        them instead of treating them as zero.

        Args:
            column (str): Column to convert.
            percentage (bool): True for percentage columns such as "24h Change".

        Returns:
            pd.Series: Numeric values aligned with the frame.
        """
        parser = parse_percentage if percentage else parse_number
        values = self.data[column].apply(
            lambda value: parser(value) if pd.notna(value) else None
        )
        return values.astype("float64")

    def _extract_numeric_value(self, value: Any) -> float:
        """
        Convert a price string such as "$84,653.63" into a float.

        Kept as a thin wrapper around :func:`validation.parse_number` so the
        number handling exists in exactly one place.

        Args:
            value (Any): Raw price value.

        Returns:
            float: The parsed number, or 0.0 when nothing numeric was found.
        """
        parsed = parse_number(value)
        return 0.0 if parsed is None else parsed

    def _extract_percentage_value(self, value: Any) -> float:
        """
        Convert a percentage string such as "-1.20%" into a float.

        Args:
            value (Any): Raw percentage value.

        Returns:
            float: The parsed percentage, or 0.0 when nothing numeric was found.
        """
        parsed = parse_percentage(value)
        return 0.0 if parsed is None else parsed

    # ------------------------------------------------------------------
    # Price filters
    # ------------------------------------------------------------------
    def filter_by_min_price(self, min_price: float) -> Optional[pd.DataFrame]:
        """
        Keep records priced above ``min_price``.

        Args:
            min_price (float): Minimum price in USD.

        Returns:
            Optional[pd.DataFrame]: Matching records, or None when not possible.
        """
        if not self._require_columns("Price"):
            return None

        try:
            prices = self._numeric_column("Price")
            result = self.data[prices > min_price]
            logger.info(f"Filtered by min price > {min_price}: {len(result)} records found")
            return result
        except Exception as e:
            logger.error(f"Error filtering by min price: {e}")
            return None

    def filter_by_max_price(self, max_price: float) -> Optional[pd.DataFrame]:
        """
        Keep records priced below ``max_price``.

        Args:
            max_price (float): Maximum price in USD.

        Returns:
            Optional[pd.DataFrame]: Matching records, or None when not possible.
        """
        if not self._require_columns("Price"):
            return None

        try:
            prices = self._numeric_column("Price")
            result = self.data[prices < max_price]
            logger.info(f"Filtered by max price < {max_price}: {len(result)} records found")
            return result
        except Exception as e:
            logger.error(f"Error filtering by max price: {e}")
            return None

    # ------------------------------------------------------------------
    # 24h change filters
    # ------------------------------------------------------------------
    def filter_by_min_change(self, min_change: float) -> Optional[pd.DataFrame]:
        """
        Keep records whose 24h change is above ``min_change`` percent.

        Args:
            min_change (float): Minimum percentage change.

        Returns:
            Optional[pd.DataFrame]: Matching records, or None when not possible.
        """
        if not self._require_columns("24h Change"):
            return None

        try:
            changes = self._numeric_column("24h Change", percentage=True)
            result = self.data[changes > min_change]
            logger.info(f"Filtered by min change > {min_change}%: {len(result)} records found")
            return result
        except Exception as e:
            logger.error(f"Error filtering by min change: {e}")
            return None

    def filter_by_max_change(self, max_change: float) -> Optional[pd.DataFrame]:
        """
        Keep records whose 24h change is below ``max_change`` percent.

        Args:
            max_change (float): Maximum percentage change.

        Returns:
            Optional[pd.DataFrame]: Matching records, or None when not possible.
        """
        if not self._require_columns("24h Change"):
            return None

        try:
            changes = self._numeric_column("24h Change", percentage=True)
            result = self.data[changes < max_change]
            logger.info(f"Filtered by max change < {max_change}%: {len(result)} records found")
            return result
        except Exception as e:
            logger.error(f"Error filtering by max change: {e}")
            return None

    # ------------------------------------------------------------------
    # Name and rank filters
    # ------------------------------------------------------------------
    def filter_by_coin(self, coin_name: str) -> Optional[pd.DataFrame]:
        """
        Keep records whose coin name contains ``coin_name`` (case-insensitive).

        Args:
            coin_name (str): Full or partial coin name typed by the user.

        Returns:
            Optional[pd.DataFrame]: Matching records, or None when not possible.
        """
        if not self._require_columns("Coin"):
            return None

        if not coin_name or not str(coin_name).strip():
            logger.error("Cannot filter by coin: no coin name given")
            return None

        try:
            names = self.data["Coin"].fillna("").astype(str)
            result = self.data[names.str.contains(str(coin_name), case=False, na=False, regex=False)]
            logger.info(f"Filtered by coin containing '{coin_name}': {len(result)} records found")
            return result
        except Exception as e:
            logger.error(f"Error filtering by coin: {e}")
            return None

    def filter_by_rank(self, min_rank: float = 1, max_rank: float = float("inf")) -> Optional[pd.DataFrame]:
        """
        Keep records whose rank falls inside the given range.

        Args:
            min_rank (float): Lowest accepted rank.
            max_rank (float): Highest accepted rank.

        Returns:
            Optional[pd.DataFrame]: Matching records, or None when not possible.
        """
        if not self._require_columns("Rank"):
            return None

        try:
            ranks = pd.to_numeric(self.data["Rank"], errors="coerce")
            result = self.data[(ranks >= min_rank) & (ranks <= max_rank)]
            logger.info(f"Filtered by rank {min_rank}-{max_rank}: {len(result)} records found")
            return result
        except Exception as e:
            logger.error(f"Error filtering by rank: {e}")
            return None

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def print_filtered_data(self, filtered_df: Optional[pd.DataFrame], title: str = "Filtered Results") -> None:
        """
        Print filtered records in a readable table.

        Args:
            filtered_df (Optional[pd.DataFrame]): Records to show.
            title (str): Heading printed above the table.
        """
        print("\n" + "=" * 80)
        print(f"  {title}")
        print("=" * 80)

        if filtered_df is None or filtered_df.empty:
            print("  No records match the filter criteria.")
        else:
            display_columns = [
                "Timestamp", "Rank", "Coin", "Symbol", "Price", "24h Change", "Market Cap"
            ]
            available = [column for column in display_columns if column in filtered_df.columns]
            print(filtered_df[available].to_string(index=False))

        print("=" * 80 + "\n")


def apply_filters(data: Optional[pd.DataFrame] = None, **kwargs: Any) -> Optional[pd.DataFrame]:
    """
    Apply several filters one after another.

    Args:
        data (Optional[pd.DataFrame]): Records to filter. When omitted the
            historical CSV data is used.
        **kwargs (Any): Any of ``min_price``, ``max_price``, ``min_change``,
            ``max_change``, ``coin``, ``min_rank``, ``max_rank``.

    Returns:
        Optional[pd.DataFrame]: The filtered records, or None when the data or a
        required column was missing.
    """
    source = data if data is not None else read_historical_data()
    if source is None or source.empty:
        logger.warning("No data available to filter")
        return None

    crypto_filter = CryptoFilter(source)
    result = source

    def apply_one(method: str, *args: Any) -> bool:
        """
        Run one filter and remember the result on the filter instance.

        Args:
            method (str): Name of the filter method to call.
            *args (Any): Arguments for that method.

        Returns:
            bool: True when filtering may continue.
        """
        nonlocal result

        crypto_filter.data = result
        filtered = getattr(crypto_filter, method)(*args)
        if filtered is None:
            # The reason was already logged by the filter itself
            return False

        result = filtered
        return True

    if kwargs.get("min_price") is not None and not apply_one("filter_by_min_price", kwargs["min_price"]):
        return None

    if kwargs.get("max_price") is not None and not apply_one("filter_by_max_price", kwargs["max_price"]):
        return None

    if kwargs.get("min_change") is not None and not apply_one("filter_by_min_change", kwargs["min_change"]):
        return None

    if kwargs.get("max_change") is not None and not apply_one("filter_by_max_change", kwargs["max_change"]):
        return None

    if kwargs.get("coin") is not None and not apply_one("filter_by_coin", kwargs["coin"]):
        return None

    min_rank = kwargs.get("min_rank")
    max_rank = kwargs.get("max_rank")
    if min_rank is not None or max_rank is not None:
        lower = min_rank if min_rank is not None else 1
        upper = max_rank if max_rank is not None else float("inf")
        if not apply_one("filter_by_rank", lower, upper):
            return None

    return result