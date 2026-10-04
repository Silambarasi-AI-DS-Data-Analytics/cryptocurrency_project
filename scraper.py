import time
import re
from datetime import datetime
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException
)
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

from config import (
    COINMARKETCAP_URL,
    NUM_COINS_TO_EXTRACT,
    HEADLESS,
    PAGE_LOAD_TIMEOUT,
    WEBDRIVER_WAIT_TIMEOUT,
    NAVIGATION_RETRIES,
    NAVIGATION_RETRY_DELAY,
    CHROME_OPTIONS_ARGS,
    COLUMN_HEADER_NAMES,
    DEFAULT_COLUMN_POSITIONS,
    ACTION_LABELS,
    TIMESTAMP_FORMAT,
    TABLE_SELECTORS,
    ROW_SELECTORS,
    CELL_SELECTORS
)
from csv_handler import setup_logging

logger = setup_logging()

class CryptoScraper:
    """
    Cryptocurrency price scraper using Selenium for CoinMarketCap.
    """
    
    def __init__(self, headless: bool = HEADLESS, timeout: int = WEBDRIVER_WAIT_TIMEOUT):
        """
        Initialize the scraper.
        
        Args:
            headless (bool): Whether to run Chrome in headless mode.
            timeout (int): WebDriver wait timeout in seconds.
        """
        self.headless = headless
        self.timeout = timeout
        self.driver = None
        self.wait = None
        # 1-based cell positions per field, filled in by _detect_column_positions()
        self.column_positions = dict(DEFAULT_COLUMN_POSITIONS)
    
    def _setup_driver(self) -> None:
        """
        Set up Chrome WebDriver with appropriate options.
        
        Raises:
            WebDriverException: If driver setup fails.
        """
        try:
            logger.info("Setting up Chrome WebDriver...")
            chrome_options = Options()
            
            # Apply headless mode
            if self.headless:
                chrome_options.add_argument("--headless=new")
                logger.info("Chrome will run in headless mode")
            else:
                logger.info("Chrome will run in visible mode")
            
            # Apply custom options from config.py
            for arg in CHROME_OPTIONS_ARGS:
                chrome_options.add_argument(arg)
            
            # Wait for the DOM to be ready instead of only the load event,
            # because CoinMarketCap fills the table with JavaScript
            chrome_options.page_load_strategy = "normal"
            
            # Set up service with webdriver-manager
            try:
                service = Service(ChromeDriverManager().install())
            except Exception as e:
                logger.warning(f"webdriver-manager failed, trying alternative: {e}")
                service = Service(ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install())
            
            # Initialize driver
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Sensible timeouts: page load and element waiting
            self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            self.driver.set_script_timeout(PAGE_LOAD_TIMEOUT)
            self.driver.implicitly_wait(5)
            
            self.wait = WebDriverWait(self.driver, self.timeout)
            logger.info("Chrome WebDriver setup completed successfully")
            
        except Exception as e:
            logger.error(f"Failed to setup Chrome WebDriver: {e}")
            raise WebDriverException(f"Chrome WebDriver setup failed: {e}")
    
    def _cleanup_driver(self) -> None:
        """
        Clean up and close the WebDriver.
        """
        if self.driver:
            try:
                logger.info("Closing Chrome WebDriver...")
                self.driver.quit()
                self.driver = None
                self.wait = None
                logger.info("Chrome WebDriver closed successfully")
            except Exception as e:
                logger.error(f"Error closing Chrome WebDriver: {e}")
    
    def _navigate_with_retry(
        self,
        url: str = COINMARKETCAP_URL,
        retries: int = NAVIGATION_RETRIES,
        delay: int = NAVIGATION_RETRY_DELAY
    ) -> None:
        """
        Navigate to a URL, retrying on timeout or WebDriver errors.
        
        Args:
            url (str): URL to open.
            retries (int): Maximum number of navigation attempts.
            delay (int): Seconds to wait between attempts.
            
        Raises:
            WebDriverException: If navigation fails after all attempts.
        """
        last_error = None
        
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Navigation attempt {attempt}/{retries}: loading {url}")
                self.driver.get(url)
                logger.info("Page navigation completed")
                return
                
            except TimeoutException as e:
                last_error = e
                logger.warning(
                    f"Navigation attempt {attempt}/{retries} timed out after "
                    f"{PAGE_LOAD_TIMEOUT}s: {self._clean_error_message(e)}"
                )
            except WebDriverException as e:
                last_error = e
                logger.warning(
                    f"Navigation attempt {attempt}/{retries} failed: "
                    f"{self._clean_error_message(e)}"
                )
                # Restart Chrome if the browser session itself died
                if "invalid session id" in str(e).lower() or "session deleted" in str(e).lower():
                    self._recreate_driver()
            
            if attempt < retries:
                logger.info(f"Waiting {delay}s before retry {attempt + 1}/{retries}...")
                time.sleep(delay)
        
        logger.error(
            f"Navigation to {url} failed after {retries} attempts. "
            f"Last error: {self._clean_error_message(last_error)}"
        )
        self._cleanup_driver()
        raise WebDriverException(
            f"Unable to reach {url} after {retries} attempts "
            f"({delay}s delay between attempts). "
            f"Last error: {self._clean_error_message(last_error)}"
        )
    
    @staticmethod
    def _clean_error_message(error: Optional[Exception]) -> str:
        """
        Strip chromedriver stacktrace noise from an exception message.
        
        Args:
            error (Optional[Exception]): Exception to format.
            
        Returns:
            str: Single-line, human readable error message.
        """
        if error is None:
            return "unknown error"
        
        message = str(error)
        if "Stacktrace:" in message:
            message = message.split("Stacktrace:", 1)[0]
        message = re.sub(r"\(Session info:[^)]*\)", "", message)
        message = ' '.join(message.replace("Message:", "").split())
        return message or "unknown error"
    
    def _recreate_driver(self) -> None:
        """
        Restart the Chrome WebDriver after the browser session became invalid.
        """
        logger.warning("Browser session is no longer valid, restarting Chrome...")
        self._cleanup_driver()
        try:
            self._setup_driver()
        except Exception as e:
            logger.error(f"Failed to restart Chrome WebDriver: {e}")
    
    def _find_crypto_table(self) -> Optional[WebElement]:
        """
        Find the cryptocurrency ranking table on CoinMarketCap.
        
        Explicit waits are used so the table is picked up as soon as the
        JavaScript has rendered it, instead of guessing with time.sleep().
        
        Returns:
            Optional[WebElement]: WebElement of the table, or None if not found.
        """
        logger.info("Searching for cryptocurrency table...")
        
        for selector in TABLE_SELECTORS:
            try:
                element = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if element:
                    logger.info(f"Found table with selector: {selector}")
                    return element
            except TimeoutException:
                logger.debug(f"Table not found with selector: {selector}")
                continue
            except Exception as e:
                logger.debug(f"Error with selector {selector}: {e}")
                continue
        
        # XPath fallback in case the class names change again
        for xpath in ["//table[contains(@class, 'cmc-table')]", "//table"]:
            try:
                element = self.wait.until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
                logger.info(f"Found table with XPath: {xpath}")
                return element
            except TimeoutException:
                continue
            except Exception as e:
                logger.debug(f"XPath fallback error for {xpath}: {e}")
        
        logger.error("Could not find cryptocurrency table")
        return None
    
    def _wait_for_table_rows(self, table_element: WebElement) -> bool:
        """
        Wait until the table body is filled with ranking rows.
        
        CoinMarketCap renders an empty table first and fills it afterwards,
        so the row count is what tells us the data is really there.
        
        Args:
            table_element (WebElement): WebElement of the table.
            
        Returns:
            bool: True when rows appeared, False on timeout.
        """
        try:
            self.wait.until(lambda driver: len(self._find_table_rows(table_element)) > 0)
            logger.info("Table rows are present")
            return True
        except TimeoutException:
            logger.warning("Timed out waiting for table rows to be rendered")
            return False
        except Exception as e:
            logger.warning(f"Error while waiting for table rows: {self._clean_error_message(e)}")
            return False
    
    def _find_table_rows(self, table_element: WebElement) -> List[WebElement]:
        """
        Find all cryptocurrency rows in the table.
        
        Args:
            table_element (WebElement): WebElement of the table.
            
        Returns:
            List[WebElement]: List of row WebElements.
        """
        for selector in ROW_SELECTORS:
            try:
                rows = table_element.find_elements(By.CSS_SELECTOR, selector)
                if rows:
                    logger.info(f"Found {len(rows)} rows with selector: {selector}")
                    return rows
            except StaleElementReferenceException:
                logger.debug(f"Rows went stale for selector {selector}, retrying")
                continue
            except Exception as e:
                logger.debug(f"Error finding rows with {selector}: {e}")
                continue
        
        logger.warning("No table rows found")
        return []
    
    def _detect_column_positions(self) -> Dict[str, int]:
        """
        Read the visible table headers and work out where each column sits.
        
        CoinMarketCap can add or remove columns (for example a "Sentiment"
        column). Reading the real header row means the extraction keeps working
        instead of relying on hard-coded cell numbers.
        
        Returns:
            Dict[str, int]: Field name -> 1-based cell position.
        """
        positions = dict(DEFAULT_COLUMN_POSITIONS)
        
        try:
            headers = self.driver.execute_script(
                """
                var table = document.querySelector('table');
                if (!table) { return []; }
                return Array.from(table.querySelectorAll('thead th'))
                         .map(function(th) { return th.innerText.trim(); });
                """
            )
        except Exception as e:
            logger.warning(f"Could not read table headers: {self._clean_error_message(e)}")
            return positions
        
        if not headers:
            logger.warning("No table headers found, using default column positions")
            return positions
        
        detected = {}
        for field, header_name in COLUMN_HEADER_NAMES.items():
            for index, header in enumerate(headers, start=1):
                # "24h %" should not accidentally match "24h Volume"
                if header.strip().lower() == header_name.strip().lower():
                    detected[field] = index
                    break
        
        if detected:
            positions.update(detected)
            logger.info(f"Detected column positions from headers: {detected}")
        else:
            logger.warning("Could not match any known header, using default column positions")
        
        return positions
    
    def _build_cell_selectors(self, cell_type: str) -> List[str]:
        """
        Build the ordered CSS selectors to try for one field.
        
        The detected column position is tried first so a moved column is handled
        automatically, then the stable selectors from config.py.
        
        Args:
            cell_type (str): Field name, e.g. 'price' or 'market_cap'.
            
        Returns:
            List[str]: CSS selectors to try in order.
        """
        selectors = []
        position = self.column_positions.get(cell_type)
        if position:
            selectors.append(f"td:nth-child({position})")
        selectors.extend(CELL_SELECTORS.get(cell_type, []))
        return selectors
    
    def _extract_cell_text(self, row_element: WebElement, cell_type: str) -> str:
        """
        Extract text from a specific cell in a row.
        
        Args:
            row_element (WebElement): WebElement of the table row.
            cell_type (str): Field name ('rank', 'name', 'symbol', 'price',
                'change', 'market_cap').
            
        Returns:
            str: Extracted text, cleaned, or "N/A" when nothing was found.
        """
        for selector in self._build_cell_selectors(cell_type):
            try:
                cells = row_element.find_elements(By.CSS_SELECTOR, selector)
                for cell in cells:
                    text = cell.text.strip()
                    if text:
                        return self._clean_text(text)
            except StaleElementReferenceException:
                continue
            except Exception as e:
                logger.debug(f"Error extracting {cell_type} with {selector}: {e}")
                continue
        
        return "N/A"
    
    def _clean_text(self, text: str) -> str:
        """
        Clean extracted text.
        
        Args:
            text (str): Raw text to clean.
            
        Returns:
            str: Cleaned text, or "N/A" when nothing usable is left.
        """
        if not text:
            return "N/A"
        # Remove extra whitespace, newlines and tabs
        cleaned = ' '.join(text.split())
        if cleaned in ('', '-'):
            return "N/A"
        return cleaned
    
    def _extract_coin_and_symbol(self, name_text: str) -> tuple:
        """
        Split combined name text into a coin name and a symbol.
        
        CoinMarketCap usually offers a dedicated symbol element, but when only
        the cell text is available it looks like "Bitcoin BTC". Action buttons
        such as "Buy" can also end up in the text and are dropped here.
        
        Args:
            name_text (str): Combined name text.
            
        Returns:
            tuple: (coin_name, symbol)
        """
        if not name_text or name_text == "N/A":
            return "N/A", "N/A"
        
        # Drop button labels that are not part of the name
        parts = [part for part in name_text.split() if part not in ACTION_LABELS]
        if not parts:
            return "N/A", "N/A"
        
        # The symbol is the last word when it is short and written in capitals.
        # Symbols may contain digits (for example "1INCH"), so isalpha() is too
        # strict here - an alphanumeric check is used instead.
        if len(parts) >= 2:
            last_part = parts[-1]
            if len(last_part) <= 6 and last_part.isalnum() and last_part.upper() == last_part:
                return ' '.join(parts[:-1]), last_part
        
        return ' '.join(parts), "N/A"
    
    def _extract_crypto_data(self, rows: List[WebElement]) -> List[Dict[str, str]]:
        """
        Extract cryptocurrency data from the table rows.
        
        Args:
            rows (List[WebElement]): List of row WebElements.
            
        Returns:
            List[Dict[str, str]]: List of cryptocurrency data dictionaries.
        """
        logger.info(f"Extracting data from {len(rows)} rows...")
        crypto_data = []
        seen_names = set()
        timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
        
        for i, row in enumerate(rows):
            if len(crypto_data) >= NUM_COINS_TO_EXTRACT:
                break
            
            try:
                rank_text = self._extract_cell_text(row, 'rank')
                
                # A real ranking row always has a numeric rank. CoinMarketCap
                # also renders promotional rows without one, so those are skipped.
                rank_match = re.search(r'\d+', rank_text)
                if not rank_match:
                    logger.debug(f"Row {i + 1} has no numeric rank, skipping")
                    continue
                rank_clean = rank_match.group(0)
                
                name_text = self._extract_cell_text(row, 'name')
                symbol_text = self._extract_cell_text(row, 'symbol')
                coin_name, name_symbol = self._extract_coin_and_symbol(name_text)
                
                # The dedicated symbol element wins over text guessing
                symbol_final = symbol_text if symbol_text != "N/A" else name_symbol
                
                crypto_entry = {
                    "Timestamp": timestamp,
                    "Rank": rank_clean,
                    "Coin": coin_name,
                    "Symbol": symbol_final,
                    "Price": self._extract_cell_text(row, 'price'),
                    "24h Change": self._extract_cell_text(row, 'change'),
                    "Market Cap": self._extract_cell_text(row, 'market_cap')
                }
                
                # Never store the same coin twice in one scrape
                key = crypto_entry["Coin"].lower()
                if crypto_entry["Coin"] == "N/A" or key in seen_names:
                    logger.debug(f"Row {i + 1} skipped (no name or duplicate)")
                    continue
                seen_names.add(key)
                
                crypto_data.append(crypto_entry)
                logger.debug(
                    f"Extracted: Rank {crypto_entry['Rank']} - "
                    f"{crypto_entry['Coin']} ({crypto_entry['Symbol']})"
                )
                
            except StaleElementReferenceException:
                logger.warning(f"Stale element reference at row {i + 1}, skipping")
                continue
            except Exception as e:
                logger.warning(f"Error extracting row {i+1}: {e}")
                continue
        
        logger.info(f"Successfully extracted {len(crypto_data)} cryptocurrency records")
        return crypto_data
    
    def _wait_for_dynamic_content(self) -> Optional[WebElement]:
        """
        Wait for the JavaScript-rendered ranking table to appear and fill up.
        
        Only explicit waits are used - no blind time.sleep() calls.
        
        Returns:
            Optional[WebElement]: The ready table, or None when it never appeared.
        """
        logger.info("Waiting for the cryptocurrency table to render...")
        
        table = self._find_crypto_table()
        if not table:
            logger.warning("Cryptocurrency table did not appear")
            return None
        
        if not self._wait_for_table_rows(table):
            return None
        
        # Work out the real column positions from the header row
        self.column_positions = self._detect_column_positions()
        logger.info("Dynamic content loaded successfully")
        return table
    
    def _check_for_block_page(self) -> bool:
        """
        Detect whether CoinMarketCap served a CAPTCHA or block page instead of
        the ranking table.
        
        Nothing is bypassed: when a protection page is detected the run stops
        and the condition is reported in the log.
        
        Only the text a user can actually see is checked. The raw page source is
        not used, because CoinMarketCap ships translation strings such as "Our
        systems have detected unusual traffic" inside its JavaScript bundles,
        which would otherwise look like a block on every single page load.
        
        Returns:
            bool: True when a block/CAPTCHA page was detected.
        """
        # Real challenge elements, checked first because they are unambiguous
        challenge_selectors = [
            "#challenge-form",
            "#cf-challenge-running",
            "iframe[src*='challenges.cloudflare.com']",
            "input[name='cf-turnstile-response']",
            "div[data-testid='geo-block']",
        ]
        for selector in challenge_selectors:
            try:
                if self.driver.find_elements(By.CSS_SELECTOR, selector):
                    logger.error(
                        f"CoinMarketCap served a protection page ({selector}). "
                        "Stopping instead of trying to bypass it."
                    )
                    return True
            except WebDriverException as e:
                logger.debug(f"Could not check selector {selector}: {self._clean_error_message(e)}")
        
        # Visible text markers
        block_markers = (
            "unusual traffic",
            "access denied",
            "are you a robot",
            "verify you are human",
            "please enable javascript and cookies",
        )
        try:
            visible_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        except WebDriverException as e:
            logger.warning(f"Could not read the visible page text: {self._clean_error_message(e)}")
            return False
        
        for marker in block_markers:
            if marker in visible_text:
                logger.error(
                    f"CoinMarketCap served a protection page ('{marker}'). "
                    "Stopping instead of trying to bypass it."
                )
                return True
        
        return False
    
    def scrape_top_coins(self, headless: Optional[bool] = None) -> List[Dict[str, str]]:
        """
        Scrape the current top cryptocurrencies from CoinMarketCap.
        
        Args:
            headless (Optional[bool]): Override headless setting.
            
        Returns:
            List[Dict[str, str]]: List of scraped cryptocurrency data. An empty
            list means nothing could be retrieved.
            
        Raises:
            WebDriverException: If the browser or the page could not be reached.
            NoSuchElementException: If the ranking table is not on the page.
        """
        if headless is not None:
            self.headless = headless
        
        logger.info(f"Starting cryptocurrency scraping (headless={self.headless})")
        crypto_data = []
        
        try:
            self._setup_driver()
            
            # Navigate (retries automatically on network/timeout errors)
            logger.info(f"Navigating to {COINMARKETCAP_URL}")
            self._navigate_with_retry(COINMARKETCAP_URL)
            
            # Never try to work around a CAPTCHA or block page
            if self._check_for_block_page():
                return []
            
            # Wait for the rendered table (locates it once)
            table = self._wait_for_dynamic_content()
            if not table:
                raise NoSuchElementException(
                    "Cryptocurrency table not found on page. CoinMarketCap may "
                    "have changed its layout - check the selectors in config.py."
                )
            
            rows = self._find_table_rows(table)
            if not rows:
                raise NoSuchElementException("Ranking table contained no rows")
            
            crypto_data = self._extract_crypto_data(rows)
            
            if not crypto_data:
                logger.error("No cryptocurrency data extracted from the table")
            else:
                logger.info(f"Successfully scraped {len(crypto_data)} cryptocurrencies")
                for coin in crypto_data:
                    logger.info(
                        f"  {coin['Rank']}. {coin['Coin']} ({coin['Symbol']}) - {coin['Price']}"
                    )
            
        except TimeoutException as e:
            logger.error(f"Page load timeout: {self._clean_error_message(e)}")
            raise
        except NoSuchElementException as e:
            logger.error(f"Element not found: {e}")
            raise
        except WebDriverException as e:
            logger.error(f"WebDriver error: {self._clean_error_message(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during scraping: {self._clean_error_message(e)}")
            raise
        finally:
            # The browser is always closed, also when something failed
            self._cleanup_driver()
        
        return crypto_data

def scrape_crypto_prices(headless: bool = HEADLESS) -> List[Dict[str, str]]:
    """
    Convenience function to scrape cryptocurrency prices.
    
    Args:
        headless (bool): Whether to run in headless mode.
        
    Returns:
        List[Dict[str, str]]: List of scraped data.
    """
    scraper = CryptoScraper(headless=headless)
    return scraper.scrape_top_coins()
