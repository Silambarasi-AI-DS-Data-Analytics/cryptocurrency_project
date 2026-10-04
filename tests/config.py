"""Central configuration for the Cryptocurrency Price Tracker.

Every setting the application needs lives in this file: the target URL, how many
coins to collect, timeouts, file locations and the Selenium selectors.

File locations are built from the folder that contains this file (the project
root), so the project works no matter which directory you start it from.
No absolute machine-specific path is ever hard-coded.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# The folder that holds config.py, i.e. the project root
BASE_DIR = Path(__file__).resolve().parent

# Folder for the historical CSV file (created automatically)
DATA_DIR = BASE_DIR / "data"

# Folder for the log file (created automatically)
LOGS_DIR = BASE_DIR / "logs"

# Full path of the historical CSV file
CSV_FILE_PATH = DATA_DIR / "crypto_prices.csv"

# Full path of the log file
LOG_FILE_PATH = LOGS_DIR / "tracker.log"

# ---------------------------------------------------------------------------
# Scraping target
# ---------------------------------------------------------------------------

# CoinMarketCap URL - change this to scrape a different page
COINMARKETCAP_URL = "https://coinmarketcap.com/"

# Number of cryptocurrencies to extract
NUM_COINS_TO_EXTRACT = 10

# ---------------------------------------------------------------------------
# Browser settings
# ---------------------------------------------------------------------------

# Default headless mode. The --headless / --no-headless CLI flags override this.
HEADLESS = False

# Chrome options that keep the browser stable and consistent
CHROME_OPTIONS_ARGS = [
    "--disable-gpu",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-popup-blocking",
    "--window-size=1920,1080",
    "--disable-blink-features=AutomationControlled",
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ---------------------------------------------------------------------------
# Timeout and retry settings (in seconds)
# ---------------------------------------------------------------------------

# How long Chrome may take to fully load a page
PAGE_LOAD_TIMEOUT = 60

# How long WebDriverWait waits for a single element to appear
WEBDRIVER_WAIT_TIMEOUT = 30

# Total number of navigation attempts before giving up
NAVIGATION_RETRIES = 3

# Delay between navigation attempts
NAVIGATION_RETRY_DELAY = 5

# ---------------------------------------------------------------------------
# CSV structure
# ---------------------------------------------------------------------------

# Column order of the historical CSV file. Every record is written in this order.
CSV_HEADERS = [
    "Timestamp",
    "Rank",
    "Coin",
    "Symbol",
    "Price",
    "24h Change",
    "Market Cap",
]

# Value stored when a field is missing or cannot be parsed.
# Never a made-up number - see validation.py
MISSING_VALUE = "N/A"

# Format used for the Timestamp column
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "INFO"

# ---------------------------------------------------------------------------
# Selenium selectors
# ---------------------------------------------------------------------------
# CoinMarketCap renders its table with JavaScript and regularly changes the
# generated CSS class names (for example "sc-f41c7826-3"). Those generated names
# are therefore avoided here: only stable, hand-written classes are used
# ("cmc-table", "cmc-link", "coin-item-name", "coin-item-symbol").

# The ranking table itself
TABLE_SELECTORS = [
    "table.cmc-table",
    "table",
]

# Rows inside the table body
ROW_SELECTORS = [
    "table tbody tr",
    "tbody tr",
]

# Per-field selectors, tried in order. These are relative to a single row.
# "td:nth-child(n)" entries are also generated at runtime from the detected
# column positions, so a moved column does not break the extraction.
CELL_SELECTORS = {
    "rank": ["td:nth-child(2)"],
    "name": ["p.coin-item-name", "a.cmc-link"],
    "symbol": ["p.coin-item-symbol"],
    "price": ["td:nth-child(4)"],
    "change": ["td:nth-child(6)"],
    "market_cap": ["td:nth-child(8)"],
}

# Maps a logical field to the visible column header text used by CoinMarketCap.
# The scraper reads the real header row and turns this into column positions,
# which keeps working if CoinMarketCap adds or removes a column.
COLUMN_HEADER_NAMES = {
    "rank": "#",
    "name": "Name",
    "price": "Price",
    "change": "24h %",
    "market_cap": "Market Cap",
}

# Words CoinMarketCap renders as buttons inside the name cell. They are not part
# of a coin name and are removed when the name and symbol are separated.
ACTION_LABELS = ("Buy", "Sell", "Trade", "Convert")

# 1-based cell positions used only as a fallback when the header row cannot be
# read. These match the current CoinMarketCap layout.
DEFAULT_COLUMN_POSITIONS = {
    "rank": 2,
    "name": 3,
    "price": 4,
    "change": 6,
    "market_cap": 8,
}