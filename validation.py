"""Validation helpers for scraped cryptocurrency records.

This module sits between the Selenium scraper and the CSV file. Its job is to
make sure that only sensible, real records are stored:

* rank must be a positive whole number
* name and symbol must not be empty
* price and market cap must contain a number when a value is present
* duplicated coins inside a single scrape are removed

Nothing here ever invents a value. If a field cannot be parsed it is reported
and the raw text (or the configured "N/A" placeholder) is kept, so a bad value
is visible in the log instead of being silently turned into a fake number.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from config import CSV_HEADERS, MISSING_VALUE

logger = logging.getLogger(__name__)


def pd_isna(value: Any) -> bool:
    """
    Check for missing values without importing pandas in this module.

    Args:
        value (Any): Value to check.

    Returns:
        bool: True when the value is a missing-value marker (None or NaN).
    """
    if value is None:
        return True
    return isinstance(value, float) and value != value  # NaN != NaN


def parse_number(value: Any) -> Optional[float]:
    """
    Convert a formatted value such as "$84,653.63" or "$1.7T" into a float.

    Handles currency symbols, thousands separators and the K/M/B/T suffixes that
    CoinMarketCap uses for large numbers.

    Args:
        value (Any): Raw value from the page or the CSV.

    Returns:
        Optional[float]: The parsed number, or None when nothing numeric exists.
    """
    if value is None or (isinstance(value, float) and pd_isna(value)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text or text.upper() == MISSING_VALUE:
        return None

    # Match an optional sign, digits with separators/decimals and a K/M/B/T suffix
    match = re.search(r"(-?\d[\d,]*(?:\.\d+)?)\s*([KMBT])?", text, re.IGNORECASE)
    if not match:
        return None

    number = float(match.group(1).replace(",", ""))
    suffix = match.group(2)
    if suffix:
        number *= {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[suffix.upper()]

    return number


def parse_percentage(value: Any) -> Optional[float]:
    """
    Convert a percentage such as "-1.20%" or "+5.5%" into a float.

    Args:
        value (Any): Raw percentage value.

    Returns:
        Optional[float]: The parsed percentage, or None when nothing numeric exists.
    """
    if value is None or (isinstance(value, float) and pd_isna(value)):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace("%", "").replace("+", "")
    if not text or text.upper() == MISSING_VALUE:
        return None

    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _is_missing(value: Any) -> bool:
    """
    Check whether a scraped field should be treated as missing.

    Args:
        value (Any): Raw field value.

    Returns:
        bool: True when the value is None, NaN, empty or the "N/A" placeholder.
    """
    if pd_isna(value):
        return True
    return str(value).strip().upper() in {"", MISSING_VALUE, "NONE", "NULL", "NAN"}


def validate_record(record: Dict[str, str]) -> Tuple[bool, List[str]]:
    """
    Validate a single scraped record.

    Args:
        record (Dict[str, str]): One scraped cryptocurrency record.

    Returns:
        Tuple[bool, List[str]]: Whether the record is usable and the list of
        problems found (empty when the record is valid).
    """
    problems: List[str] = []

    for header in CSV_HEADERS:
        if header not in record:
            problems.append(f"missing column '{header}'")

    # Rank must be a positive whole number
    rank = parse_number(record.get("Rank"))
    if rank is None or rank < 1 or rank != int(rank):
        problems.append(f"rank '{record.get('Rank')}' is not a positive whole number")

    # Name and symbol must not be empty
    if _is_missing(record.get("Coin")):
        problems.append("coin name is empty")
    if _is_missing(record.get("Symbol")):
        problems.append("coin symbol is empty")

    # Price and market cap must contain a number when a value is present
    for field in ("Price", "Market Cap"):
        raw_value = record.get(field)
        if not _is_missing(raw_value) and parse_number(raw_value) is None:
            problems.append(f"{field.lower()} '{raw_value}' is not numeric")

    # 24h change is optional but must be numeric when present
    change = record.get("24h Change")
    if not _is_missing(change) and parse_percentage(change) is None:
        problems.append(f"24h change '{change}' is not numeric")

    return (not problems), problems


def validate_crypto_data(
    records: List[Dict[str, str]],
    log_invalid: bool = True
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Validate a whole scrape and remove duplicates.

    Args:
        records (List[Dict[str, str]]): Records returned by the scraper.
        log_invalid (bool): Whether invalid records are written to the log.

    Returns:
        Tuple[List[Dict[str, str]], List[Dict[str, str]]]: The valid records
        (duplicates removed, original order kept) and the rejected records.
    """
    valid: List[Dict[str, str]] = []
    invalid: List[Dict[str, str]] = []
    seen_names = set()

    for record in records or []:
        is_valid, problems = validate_record(record)

        if not is_valid:
            invalid.append(record)
            if log_invalid:
                logger.warning(
                    "Rejected record '%s': %s",
                    record.get("Coin", "<no name>"),
                    "; ".join(problems),
                )
            continue

        # Avoid the same coin twice inside one scrape
        key = record["Coin"].strip().lower()
        if key in seen_names:
            logger.warning("Skipped duplicate coin in this scrape: %s", record["Coin"])
            continue

        seen_names.add(key)
        valid.append(record)

    logger.info(
        "Validation finished: %d valid, %d rejected out of %d scraped records",
        len(valid), len(invalid), len(records or []),
    )
    return valid, invalid