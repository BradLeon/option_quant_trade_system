"""Tests for SymbolFormatter utility."""

import pytest

from src.data.utils import IBKRContract, Market, SymbolFormatter


class TestDetectMarket:
    """Test market detection."""

    def test_detect_hk_from_suffix(self):
        assert SymbolFormatter.detect_market("0700.HK") == Market.HK
        assert SymbolFormatter.detect_market("9988.HK") == Market.HK

    def test_detect_hk_from_prefix(self):
        assert SymbolFormatter.detect_market("HK.00700") == Market.HK
        assert SymbolFormatter.detect_market("HK.09988") == Market.HK

    def test_detect_hk_from_digits(self):
        assert SymbolFormatter.detect_market("700") == Market.HK
        assert SymbolFormatter.detect_market("9988") == Market.HK

    def test_detect_us_from_letters(self):
        assert SymbolFormatter.detect_market("AAPL") == Market.US
        assert SymbolFormatter.detect_market("GOOG") == Market.US
        assert SymbolFormatter.detect_market("TSLA") == Market.US

    def test_detect_us_from_prefix(self):
        assert SymbolFormatter.detect_market("US.AAPL") == Market.US


class TestToStandard:
    """Test standardization."""

    def test_hk_from_yahoo_format(self):
        assert SymbolFormatter.to_standard("0700.HK") == "0700.HK"
        assert SymbolFormatter.to_standard("9988.HK") == "9988.HK"

    def test_hk_from_futu_format(self):
        assert SymbolFormatter.to_standard("HK.00700") == "0700.HK"
        assert SymbolFormatter.to_standard("HK.09988") == "9988.HK"

    def test_hk_from_digits(self):
        assert SymbolFormatter.to_standard("700") == "0700.HK"
        assert SymbolFormatter.to_standard("9988") == "9988.HK"
        assert SymbolFormatter.to_standard("00700") == "0700.HK"

    def test_hk_edge_case_zero(self):
        # Edge case: "0" should become "0000.HK"
        assert SymbolFormatter.to_standard("0") == "0000.HK"

    def test_us_stocks(self):
        assert SymbolFormatter.to_standard("AAPL") == "AAPL"
        assert SymbolFormatter.to_standard("aapl") == "AAPL"
        assert SymbolFormatter.to_standard("GOOG") == "GOOG"

    def test_us_with_prefix(self):
        assert SymbolFormatter.to_standard("US.AAPL") == "AAPL"


class TestToIBKRContract:
    """Test IBKR contract conversion."""

    def test_hk_stock_contract(self):
        contract = SymbolFormatter.to_ibkr_contract("0700.HK")
        assert contract.symbol == "700"
        assert contract.exchange == "SEHK"
        assert contract.currency == "HKD"
        assert contract.market == Market.HK

    def test_hk_from_digits(self):
        contract = SymbolFormatter.to_ibkr_contract("700")
        assert contract.symbol == "700"
        assert contract.exchange == "SEHK"
        assert contract.currency == "HKD"

    def test_us_stock_contract(self):
        contract = SymbolFormatter.to_ibkr_contract("AAPL")
        assert contract.symbol == "AAPL"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"
        assert contract.market == Market.US


class TestToIBKRSymbol:
    """Test IBKR symbol conversion."""

    def test_hk_to_ibkr_symbol(self):
        assert SymbolFormatter.to_ibkr_symbol("0700.HK") == "700"
        assert SymbolFormatter.to_ibkr_symbol("9988.HK") == "9988"
        assert SymbolFormatter.to_ibkr_symbol("00005.HK") == "5"

    def test_us_to_ibkr_symbol(self):
        assert SymbolFormatter.to_ibkr_symbol("AAPL") == "AAPL"
        assert SymbolFormatter.to_ibkr_symbol("GOOG") == "GOOG"


class TestNormalizeForMatching:
    """Test normalization for matching."""

    def test_hk_normalize(self):
        # All HK formats should normalize to same value
        assert SymbolFormatter.normalize_for_matching("0700.HK") == "700"
        assert SymbolFormatter.normalize_for_matching("HK.00700") == "700"
        assert SymbolFormatter.normalize_for_matching("700") == "700"
        assert SymbolFormatter.normalize_for_matching("00700") == "700"

    def test_us_normalize(self):
        assert SymbolFormatter.normalize_for_matching("AAPL") == "AAPL"
        assert SymbolFormatter.normalize_for_matching("aapl") == "AAPL"
        assert SymbolFormatter.normalize_for_matching("US.AAPL") == "AAPL"


class TestFromIBKRContract:
    """Test reverse conversion from IBKR contract."""

    def test_hk_from_contract(self):
        assert SymbolFormatter.from_ibkr_contract("700", "SEHK") == "0700.HK"
        assert SymbolFormatter.from_ibkr_contract("9988", "SEHK") == "9988.HK"
        assert SymbolFormatter.from_ibkr_contract("5", "SEHK") == "0005.HK"

    def test_us_from_contract(self):
        assert SymbolFormatter.from_ibkr_contract("AAPL", "SMART") == "AAPL"
        assert SymbolFormatter.from_ibkr_contract("GOOG", "SMART") == "GOOG"

    def test_auto_detect_without_exchange(self):
        # Digits without exchange = HK
        assert SymbolFormatter.from_ibkr_contract("700") == "0700.HK"
        # Letters without exchange = US
        assert SymbolFormatter.from_ibkr_contract("AAPL") == "AAPL"


class TestRoundTrip:
    """Test round-trip conversions."""

    def test_hk_round_trip(self):
        original = "0700.HK"
        # Standard -> IBKR -> Standard
        ibkr = SymbolFormatter.to_ibkr_contract(original)
        back = SymbolFormatter.from_ibkr_contract(ibkr.symbol, ibkr.exchange)
        assert back == original

    def test_us_round_trip(self):
        original = "AAPL"
        ibkr = SymbolFormatter.to_ibkr_contract(original)
        back = SymbolFormatter.from_ibkr_contract(ibkr.symbol, ibkr.exchange)
        assert back == original

    def test_various_inputs_to_standard(self):
        # All these should convert to same standard format
        inputs = ["700", "0700", "00700", "0700.HK", "HK.00700", "HK.700"]
        expected = "0700.HK"
        for inp in inputs:
            assert SymbolFormatter.to_standard(inp) == expected
