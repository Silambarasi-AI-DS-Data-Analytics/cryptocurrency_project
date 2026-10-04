"""CSV history and logging setup for the Cryptocurrency Price Tracker.

Two responsibilities live here:

* ``setup_logging`` - configures Python logging once, writing to
  ``logs/tracker.log`` and to the console.
* ``create_or_append_csv`` / ``read_historical_data`` / ``get_csv_info`` -
  maintain the historical CSV file in ``data/``.

The CSV is append-only: previous records are never rewritten or deleted.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from config import (
    DATA_DIR,
    CSV_FILE_PATH,
    CSV_HEADERS,
    LOGS_DIR,
    LOG_FILE_PATH,
    LOG_FORMAT,
    LOG_LEVEL,
    MISSING_VALUE,
    TIMESTAMP_FORMAT,
)

# Name of the application logger shared by every module
LOGGER_NAME = "crypto_tracker"

# Remembers whether the handlers were already installed, so importing several
# modules does not duplicate every log line
_logging_configured = False


def setup_logging() -> logging.Logger:
    """
    Configure application logging (log file + console) exactly once.

    The ``logs`` folder and the log file are created automatically.

    Returns:
        logging.Logger: The shared application logger.
    """
    global _logging_configured

    if _logging_configured:
        return logging.getLogger(LOGGER_NAME)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    handler_file = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    handler_file.setFormatter(logging.Formatter(LOG_FORMAT))

    handler_console = logging.StreamHandler()
    handler_console.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL))
    root.addHandler(handler_file)
    root.addHandler(handler_console)

    _logging_configured = True
    return logging.getLogger(LOGGER_NAME)


logger = setup_logging()


def ensure_data_directory() -> None:
    """
    Create the data directory if it does not exist yet.

    Raises:
        OSError: If the directory cannot be created.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Data directory ready: {DATA_DIR}")
    except OSError as e:
        logger.error(f"Failed to create data directory {DATA_DIR}: {e}")
        raise


def _to_dataframe(data: List[Dict[str, str]]) -> pd.DataFrame:
    """
    Turn scraped records into a DataFrame with the exact CSV column order.

    Missing columns are filled with the configured placeholder instead of being
    invented, and unexpected extra columns are dropped.

    Args:
        data (List[Dict[str, str]]): Scraped records.

    Returns:
        pd.DataFrame: Frame ready to be written to CSV.
    """
    frame = pd.DataFrame(data)

    for header in CSV_HEADERS:
        if header not in frame.columns:
            logger.debug(f"Column '{header}' missing from scraped data, using {MISSING_VALUE}")
            frame[header] = MISSING_VALUE

    return frame[CSV_HEADERS]


def create_or_append_csv(data: List[Dict[str, str]]) -> bool:
    """
    Create the CSV file with headers, or append the records to the existing one.

    Headers are only written when the file is created (or when an existing file
    turns out to be empty), so historical rows are never overwritten.

    Args:
        data (List[Dict[str, str]]): Validated cryptocurrency records.

    Returns:
        bool: True when the records were stored, False otherwise.
    """
    if not data:
        logger.warning("No data provided to save to CSV")
        return False

    try:
        ensure_data_directory()

        # An existing but empty file would break a header-less append
        needs_header = (not CSV_FILE_PATH.exists()) or CSV_FILE_PATH.stat().st_size == 0

        frame = _to_dataframe(data)

        if needs_header:
            frame.to_csv(CSV_FILE_PATH, index=False, encoding="utf-8", mode="w")
            logger.info(f"Created new CSV file with headers: {CSV_FILE_PATH}")
        else:
            frame.to_csv(
                CSV_FILE_PATH,
                index=False,
                header=False,
                encoding="utf-8",
                mode="a",
            )
            logger.info(f"Appended {len(frame)} records to CSV: {CSV_FILE_PATH}")

        logger.info(f"Successfully saved {len(frame)} cryptocurrency records")
        return True

    except (OSError, ValueError) as e:
        logger.error(f"Error saving data to CSV: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving data to CSV: {e}")
        return False


def read_historical_data() -> Optional[pd.DataFrame]:
    """
    Read the historical CSV file.

    Returns:
        Optional[pd.DataFrame]: All stored records, or None when there is no
        readable history yet.
    """
    try:
        if not CSV_FILE_PATH.exists():
            logger.info("No historical data file found")
            return None

        frame = pd.read_csv(CSV_FILE_PATH, encoding="utf-8")
        logger.info(f"Read {len(frame)} historical records from {CSV_FILE_PATH}")
        return frame

    except pd.errors.EmptyDataError:
        logger.warning(f"CSV file exists but contains no data: {CSV_FILE_PATH}")
        return None
    except (OSError, pd.errors.ParserError) as e:
        # Do not touch the file: history must not be lost because of a parse error
        logger.error(f"Error reading historical data from {CSV_FILE_PATH}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error reading historical data: {e}")
        return None


def get_csv_info() -> Dict[str, Any]:
    """
    Collect information about the CSV file for the --csv-info command.

    Returns:
        Dict[str, Any]: File details, or an error description when unreadable.
    """
    try:
        if not CSV_FILE_PATH.exists():
            return {
                "exists": False,
                "path": str(CSV_FILE_PATH),
                "rows": 0,
                "columns": CSV_HEADERS,
            }

        frame = pd.read_csv(CSV_FILE_PATH, encoding="utf-8")
        last_modified = datetime.fromtimestamp(
            CSV_FILE_PATH.stat().st_mtime
        ).strftime(TIMESTAMP_FORMAT)

        return {
            "exists": True,
            "path": str(CSV_FILE_PATH),
            "rows": len(frame),
            "columns": list(frame.columns),
            "size_bytes": CSV_FILE_PATH.stat().st_size,
            "last_modified": last_modified,
        }

    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as e:
        logger.error(f"Error getting CSV info: {e}")
        return {"exists": CSV_FILE_PATH.exists(), "path": str(CSV_FILE_PATH), "error": str(e)}