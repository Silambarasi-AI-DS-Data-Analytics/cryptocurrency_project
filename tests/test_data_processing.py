import unittest
import os
import sys
from datetime import datetime
import pandas as pd

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csv_handler import get_csv_info, ensure_data_directory
from filters import CryptoFilter, apply_filters
from config import CSV_HEADERS

class TestDataProcessing(unittest.TestCase):
    """Test cases for data processing functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.test_data = [
            {
                "Timestamp": "2026-10-02 10:00:00",
                "Rank": "1",
                "Coin": "Bitcoin",
                "Symbol": "BTC",
                "Price": "$85,747.72",
                "24h Change": "0.04%",
                "Market Cap": "$1.72T"
            },
            {
                "Timestamp": "2026-10-02 10:00:00",
                "Rank": "2",
                "Coin": "Ethereum",
                "Symbol": "ETH",
                "Price": "$4,327.85",
                "24h Change": "-1.20%",
                "Market Cap": "$520.5B"
            },
            {
                "Timestamp": "2026-10-02 10:00:00",
                "Rank": "3",
                "Coin": "Tether",
                "Symbol": "USDT",
                "Price": "$1.0001",
                "24h Change": "0.01%",
                "Market Cap": "$83.2B"
            }
        ]
    
    def test_csv_headers(self):
        """Test CSV headers configuration."""
        self.assertEqual(len(CSV_HEADERS), 7)
        self.assertIn("Timestamp", CSV_HEADERS)
        self.assertIn("Rank", CSV_HEADERS)
        self.assertIn("Coin", CSV_HEADERS)
        self.assertIn("Symbol", CSV_HEADERS)
        self.assertIn("Price", CSV_HEADERS)
        self.assertIn("24h Change", CSV_HEADERS)
        self.assertIn("Market Cap", CSV_HEADERS)
    
    def test_ensure_data_directory(self):
        """Test data directory creation."""
        try:
            ensure_data_directory()
            self.assertTrue(os.path.exists("data"))
        except Exception as e:
            self.fail(f"ensure_data_directory failed: {e}")
    
    def test_crypto_filter_numeric_extraction(self):
        """Test numeric value extraction from price strings."""
        crypto_filter = CryptoFilter(pd.DataFrame(self.test_data))
        
        # Test price extraction
        self.assertAlmostEqual(crypto_filter._extract_numeric_value("$85,747.72"), 85747.72)
        self.assertAlmostEqual(crypto_filter._extract_numeric_value("$4,327.85"), 4327.85)
        self.assertAlmostEqual(crypto_filter._extract_numeric_value("$1.0001"), 1.0001)
        self.assertEqual(crypto_filter._extract_numeric_value("N/A"), 0.0)
        self.assertEqual(crypto_filter._extract_numeric_value(""), 0.0)
    
    def test_crypto_filter_percentage_extraction(self):
        """Test percentage value extraction."""
        crypto_filter = CryptoFilter(pd.DataFrame(self.test_data))
        
        # Test percentage extraction
        self.assertAlmostEqual(crypto_filter._extract_percentage_value("0.04%"), 0.04)
        self.assertAlmostEqual(crypto_filter._extract_percentage_value("-1.20%"), -1.20)
        self.assertAlmostEqual(crypto_filter._extract_percentage_value("+5.5%"), 5.5)
        self.assertEqual(crypto_filter._extract_percentage_value("N/A"), 0.0)
    
    def test_filter_by_min_price(self):
        """Test filtering by minimum price."""
        df = pd.DataFrame(self.test_data)
        crypto_filter = CryptoFilter(df)
        result = crypto_filter.filter_by_min_price(1000)
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)  # Bitcoin and Ethereum > 1000
        coin_names = result['Coin'].tolist()
        self.assertIn("Bitcoin", coin_names)
        self.assertIn("Ethereum", coin_names)
        self.assertNotIn("Tether", coin_names)
    
    def test_filter_by_min_change(self):
        """Test filtering by minimum change percentage."""
        df = pd.DataFrame(self.test_data)
        crypto_filter = CryptoFilter(df)
        result = crypto_filter.filter_by_min_change(0)
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)  # Bitcoin (+0.04%) and Tether (+0.01%) > 0
        coin_names = result['Coin'].tolist()
        self.assertIn("Bitcoin", coin_names)
        self.assertIn("Tether", coin_names)
    
    def test_filter_by_coin(self):
        """Test filtering by coin name."""
        df = pd.DataFrame(self.test_data)
        crypto_filter = CryptoFilter(df)
        result = crypto_filter.filter_by_coin("bitcoin")
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]['Coin'], "Bitcoin")
    
    def test_apply_filters(self):
        """Test applying multiple filters."""
        df = pd.DataFrame(self.test_data)
        result = apply_filters(df, min_price=1000, min_change=0)
        
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)  # Only Bitcoin meets both criteria
        self.assertEqual(result.iloc[0]['Coin'], "Bitcoin")
    
    def test_empty_data_handling(self):
        """Test handling of empty data."""
        crypto_filter = CryptoFilter(pd.DataFrame())
        result = crypto_filter.filter_by_min_price(100)
        self.assertIsNone(result)
    
    def test_get_csv_info_nonexistent(self):
        """Test CSV info when file doesn't exist."""
        # Temporarily rename if exists
        test_path = "data/test_csv_info.csv"
        if os.path.exists(test_path):
            os.remove(test_path)
        
        info = get_csv_info()
        self.assertIsInstance(info, dict)
        self.assertIn("exists", info)
    
    def test_data_validation_structure(self):
        """Test that test data has correct structure."""
        for item in self.test_data:
            self.assertIn("Timestamp", item)
            self.assertIn("Rank", item)
            self.assertIn("Coin", item)
            self.assertIn("Symbol", item)
            self.assertIn("Price", item)
            self.assertIn("24h Change", item)
            self.assertIn("Market Cap", item)
            # Ensure no None values causing issues
            self.assertIsNotNone(item["Coin"])

if __name__ == "__main__":
    unittest.main()
