# Cryptocurrency Price Tracker

A Python application that scrapes the **current top 10 cryptocurrencies** from
[CoinMarketCap](https://coinmarketcap.com/) with **Selenium + Chrome** and stores
every scrape as timestamped history in a CSV file.

Coin names and prices are never hard-coded. Whatever CoinMarketCap shows at the
moment of the run is what gets stored.

## Features

- **Live Selenium scraping** - Chrome and ChromeDriver read the real ranking table
- **Dynamic top 10** - the current leaders are discovered at runtime
- **Resilient navigation** - page-load timeout plus automatic retries
- **Automatic column detection** - reads the table header row, so a moved column does not break extraction
- **CAPTCHA aware** - detects a protection page and stops instead of bypassing it
- **Data validation** - bad or duplicate records are rejected and logged, never faked
- **CSV history** - append-only, headers written once, timestamp per scrape
- **Headless mode** - run with or without a visible browser window
- **Filters** - by price, 24h change, coin name or rank
- **Logging** - everything is written to `logs/tracker.log`
- **Offline unit tests** - the test suite needs no website access

## Requirements

| Item | Version |
|---|---|
| Python | 3.11 (3.8+ should work) |
| Google Chrome | Installed on your machine |
| ChromeDriver | Installed automatically by webdriver-manager |
| Internet | Required **only** for the actual scraping |

## Project structure

```text
E:\price
│
├── main.py              # CLI entry point and application flow
├── scraper.py           # Selenium scraping logic
├── config.py            # All settings: URL, limits, timeouts, paths, selectors
├── validation.py        # Record validation and number parsing
├── csv_handler.py       # CSV history + logging setup
├── filters.py           # Filtering of scraped/stored data
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── .gitignore
│
├── data\                # Historical CSV (created automatically)
│   └── crypto_prices.csv
│
├── logs\                # Log files (created automatically)
│   └── tracker.log
│
└── tests\               # Unit tests (no network required)
    ├── test_config.py
    ├── test_csv_handler.py
    ├── test_data_processing.py
    ├── test_scraper.py
    └── test_validation.py
```

## Installation

```powershell
cd E:\price
```

Optional but recommended - use a virtual environment:

```powershell
python -m venv venv
venv\Scripts\activate
```

Install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

The only runtime dependencies are `selenium`, `webdriver-manager` and `pandas`.

## Running

Normal run, with a visible Chrome window:

```powershell
python main.py
```

Headless run, no browser window:

```powershell
python main.py --headless
```

Force a visible window (useful when debugging a scraping problem):

```powershell
python main.py --no-headless
```

The program exits with `0` on success and `1` on failure, so it can be used in
scripts and scheduled tasks.

## Filtering

Filters are applied to the freshly scraped data and shown as an extra table.
They never modify the CSV history and never change what gets stored.

```powershell
python main.py --min-price 1000          # price above 1000 USD
python main.py --max-price 10             # price below 10 USD
python main.py --min-change 5             # 24h change above +5 %
python main.py --max-change -2            # 24h change below -2 %
python main.py --coin bitcoin             # coin name contains "bitcoin"
python main.py --min-rank 1 --max-rank 5  # only ranks 1-5
```

Combine with other options:

```powershell
python main.py --headless --min-change 3
```

## Inspecting the stored data

```powershell
python main.py --show-history
python main.py --csv-info
python main.py --help
```

## CSV output

`data\crypto_prices.csv` is created automatically. Each successful scrape is
**appended**; historical rows are never overwritten.

| Column | Description |
|---|---|
| Timestamp | When the record was scraped (`YYYY-MM-DD HH:MM:SS`) |
| Rank | Rank on CoinMarketCap at scrape time |
| Coin | Cryptocurrency name |
| Symbol | Ticker symbol |
| Price | Price in USD, exactly as displayed |
| 24h Change | 24-hour change percentage |
| Market Cap | Market capitalisation, exactly as displayed |

Example:

```text
Timestamp,Rank,Coin,Symbol,Price,24h Change,Market Cap
2026-10-03 09:30:06,1,Bitcoin,BTC,"$84,656.77",1.00%,$1.7T
2026-10-03 09:30:06,2,Ethereum,ETH,"$2,680.91",1.33%,$327.35B
```

Prices and market caps are stored in the readable format CoinMarketCap uses, so
the history stays true to the source.

## Logging

`logs\tracker.log` is created automatically and records the application start,
browser setup, every navigation attempt, the number of records retrieved,
validation results, filtering, CSV writes and all errors.

```text
2026-10-03 09:30:06 - crypto_tracker - INFO - Navigation attempt 1/3: loading https://coinmarketcap.com/
2026-10-03 09:30:06 - crypto_tracker - INFO - Detected column positions from headers: {'rank': 2, ...}
2026-10-03 09:30:06 - crypto_tracker - INFO - Successfully scraped 10 cryptocurrencies
```

## Testing

The test suite is offline. Selenium, the filesystem and pandas are replaced with
fakes or temporary folders, so **no CoinMarketCap access is needed** and no real
market data is stored.

```powershell
python -m compileall .
python -m unittest discover -s tests
```

Verbose output for a single file:

```powershell
python -m unittest tests.test_validation -v
```

Live verification is a separate step and does need the website:

```powershell
python main.py --headless
```

## Configuration

Everything is set in `config.py`:

| Setting | Purpose |
|---|---|
| `COINMARKETCAP_URL` | Target page |
| `NUM_COINS_TO_EXTRACT` | How many coins to collect (default 10) |
| `HEADLESS` | Default browser mode |
| `PAGE_LOAD_TIMEOUT` | Page load timeout in seconds |
| `WEBDRIVER_WAIT_TIMEOUT` | Element wait timeout in seconds |
| `NAVIGATION_RETRIES` | Navigation attempts before giving up |
| `NAVIGATION_RETRY_DELAY` | Seconds between attempts |
| `DATA_DIR`, `LOGS_DIR` | Output folders, derived from the project folder |
| `TABLE_SELECTORS`, `ROW_SELECTORS`, `CELL_SELECTORS` | CSS selectors |
| `COLUMN_HEADER_NAMES`, `DEFAULT_COLUMN_POSITIONS` | Column mapping |

Paths are built with `pathlib` from the folder containing `config.py`, so the
project can be started from any working directory and no absolute path such as
`E:\price\data\crypto_prices.csv` is ever hard-coded.

## How it works

1. Parse the CLI arguments and configure logging
2. Start Chrome through Selenium (headless or visible)
3. Navigate to CoinMarketCap, retrying up to `NAVIGATION_RETRIES` times with a
   delay, after a `PAGE_LOAD_TIMEOUT` second page-load timeout
4. Stop and report if a CAPTCHA or block page is detected - it is never bypassed
5. Wait explicitly (`WebDriverWait` + `expected_conditions`) for the table and
   its rows; no blind `time.sleep()`
6. Read the table header row to work out the real column positions
7. Extract rank, name, symbol, price, 24h change and market cap per row, skipping
   promotional rows that have no rank and duplicates
8. Validate every record and reject malformed ones with a logged reason
9. Apply the optional filters
10. Display the results and append them to the CSV history
11. Close the browser in a `finally` block, also on failure

## Troubleshooting

**`net::ERR_CONNECTION_TIMED_OUT`, `ERR_CONNECTION_RESET` or `ERR_EMPTY_RESPONSE`**

The website could not be reached. This is a network problem, not a code problem.
Other sites usually still work, and CoinMarketCap resolves to different CDN
addresses depending on the connection. Try another network (for example a phone
hotspot) or a different time of day. The retry logic in `scraper.py` handles
transient failures, and a persistent failure ends with a clear message and exit
code `1` instead of a raw traceback.

**"Could not find cryptocurrency table"**

CoinMarketCap changed its layout. Check `logs\tracker.log`, then update
`TABLE_SELECTORS` / `ROW_SELECTORS` in `config.py`. The column positions are
detected from the header row, so a moved column is handled automatically.

**"CoinMarketCap served a protection page"**

The site asked for a CAPTCHA or rate limiting. The application stops on purpose
and does not attempt to bypass it. Wait a while before running again.

**`Table not found` in headless mode but fine in visible mode**

Run `python main.py --no-headless` to watch what Chrome is doing.

**ChromeDriver errors on the first run**

webdriver-manager downloads a matching driver on first use, which needs internet
access. Later runs reuse the cached driver.

## Important limitation

Actual data can only be collected **while CoinMarketCap is reachable from your
machine**. If the site is blocked by the network, the program validates and
reports the failure and exits with code `1` - it never fills the CSV with
placeholder or invented prices.

## Responsible use

This project uses normal browser automation only. It does not bypass CAPTCHAs,
anti-bot protection, authentication or rate limits, it does not access
authenticated areas, and it performs a single page load per run. Please follow
the CoinMarketCap terms of service and use this for educational purposes.

## License

Provided for educational purposes.