#!/usr/bin/env python3
"""Smoke test for Alpaca connection.

This script tests:
1. Trading client connection
2. Account balance retrieval
3. Historical data fetching

Run this before starting the trading bot to verify Alpaca connectivity.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def test_alpaca_connection():
    """Test Alpaca API connection."""
    print("=" * 60)
    print("ALPACA CONNECTION SMOKE TEST")
    print("=" * 60)

    # Check environment variables
    print("\n1. Checking environment variables...")
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        print("❌ FAILED: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        print("\nSet them in your .env file:")
        print("  ALPACA_API_KEY=your_key_here")
        print("  ALPACA_SECRET_KEY=your_secret_here")
        print("\nGet your keys at: https://app.alpaca.markets/paper/dashboard/overview")
        return False

    print(f"✅ ALPACA_API_KEY: {api_key[:8]}...{api_key[-4:]}")
    print(f"✅ ALPACA_SECRET_KEY: {secret_key[:8]}...{secret_key[-4:]}")

    # Test trading client
    print("\n2. Testing trading client connection...")
    try:
        from alpaca.trading.client import TradingClient

        trading = TradingClient(api_key, secret_key, paper=True)
        account = trading.get_account()

        print(f"✅ Connected to Alpaca")
        print(f"   Account status: {account.status}")
        print(f"   Cash: ${float(account.cash):,.2f}")
        print(f"   Buying power: ${float(account.buying_power):,.2f}")
        print(f"   Portfolio value: ${float(account.equity):,.2f}")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        print("\nMake sure you're using PAPER TRADING keys from:")
        print("https://app.alpaca.markets/paper/dashboard/overview")
        return False

    # Test data client
    print("\n3. Testing historical data fetching...")
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        data = CryptoHistoricalDataClient()

        # Fetch last 10 BTC/USD 15-minute candles
        request = CryptoBarsRequest(
            symbol_or_symbols="BTC/USD",
            timeframe=TimeFrame(15, TimeFrameUnit.Minute),
            start=datetime.now(timezone.utc) - timedelta(hours=3),
            limit=10
        )

        bars = data.get_crypto_bars(request)

        if "BTC/USD" not in bars.data or len(bars.data["BTC/USD"]) == 0:
            print("❌ FAILED: No data returned for BTC/USD")
            return False

        print(f"✅ Fetched {len(bars.data['BTC/USD'])} candles for BTC/USD")
        print("\n   Last 3 candles:")

        for bar in list(bars.data["BTC/USD"])[-3:]:
            print(f"   {bar.timestamp.strftime('%Y-%m-%d %H:%M')} | "
                  f"O: ${bar.open:,.2f} H: ${bar.high:,.2f} "
                  f"L: ${bar.low:,.2f} C: ${bar.close:,.2f} "
                  f"V: {bar.volume:.2f}")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

    # Test ETH/USD
    print("\n4. Testing ETH/USD data fetching...")
    try:
        request = CryptoBarsRequest(
            symbol_or_symbols="ETH/USD",
            timeframe=TimeFrame(15, TimeFrameUnit.Minute),
            start=datetime.now(timezone.utc) - timedelta(hours=3),
            limit=5
        )

        bars = data.get_crypto_bars(request)

        if "ETH/USD" not in bars.data or len(bars.data["ETH/USD"]) == 0:
            print("❌ FAILED: No data returned for ETH/USD")
            return False

        latest_bar = list(bars.data["ETH/USD"])[-1]
        print(f"✅ Fetched ETH/USD data")
        print(f"   Latest: ${latest_bar.close:,.2f} @ {latest_bar.timestamp.strftime('%Y-%m-%d %H:%M')}")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False

    # Success
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED")
    print("=" * 60)
    print("\nYour Alpaca connection is working correctly!")
    print("You can now run the trading bot:")
    print("  python3 -m src.main")
    print()

    return True


if __name__ == "__main__":
    try:
        success = test_alpaca_connection()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
