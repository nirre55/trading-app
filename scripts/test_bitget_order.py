"""Test script — diagnose Bitget USDT-M MARKET order placement."""
import asyncio
import ccxt.pro
import yaml

async def main():
    with open("config/config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    ex_cfg = cfg["exchange"]
    exchange = ccxt.pro.bitget({
        "apiKey": ex_cfg["api_key"],
        "secret": ex_cfg["api_secret"],
        "password": ex_cfg["password"],
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "createMarketBuyOrderRequiresPrice": False,
        },
    })

    try:
        await exchange.load_markets()
        print("Markets loaded OK")

        # Check balance
        bal = await exchange.fetch_balance()
        usdt = bal.get("USDT", {})
        print(f"Balance USDT: free={usdt.get('free')}, total={usdt.get('total')}")

        # First, set leverage
        lev_params = {"productType": "USDT-FUTURES", "marginCoin": "USDT", "marginMode": "isolated"}
        try:
            await exchange.set_leverage(10, "BTC/USDT", lev_params)
            print("Leverage set to 10 OK")
        except Exception as e:
            print(f"set_leverage failed: {e}")

        # Test SELL market order (SHORT entry), very small qty
        # qty=0.001 BTC, notional = ~71 USDT, margin at 10x = ~7 USDT
        symbol = "BTC/USDT"

        # Fetch current price
        ticker = await exchange.fetch_ticker(symbol)
        current_price = ticker["last"]
        print(f"Current BTC price: {current_price}")

        # Test 1: isolated, no price
        params_v1 = {
            "productType": "USDT-FUTURES",
            "marginMode": "isolated",
            "marginCoin": "USDT",
        }
        print(f"\nTest 1 — SELL MARKET (isolated, price=None): {params_v1}")
        try:
            order = await exchange.create_order(symbol, "market", "sell", 0.001, None, params_v1)
            print(f"  SUCCESS: id={order['id']} status={order['status']}")
        except Exception as e:
            print(f"  FAILED: {e}")

        # Test 2: isolated, with current price
        params_v2 = {
            "productType": "USDT-FUTURES",
            "marginMode": "isolated",
            "marginCoin": "USDT",
        }
        print(f"\nTest 2 — SELL MARKET (isolated, price={current_price}): {params_v2}")
        try:
            order = await exchange.create_order(symbol, "market", "sell", 0.001, current_price, params_v2)
            print(f"  SUCCESS: id={order['id']} status={order['status']} avg={order.get('average')}")
            print(f"  Raw: {order}")
        except Exception as e:
            print(f"  FAILED: {e}")

        # Test 3: cross, with price
        params_v3 = {
            "productType": "USDT-FUTURES",
            "marginMode": "cross",
            "marginCoin": "USDT",
        }
        print(f"\nTest 3 — SELL MARKET (cross, price={current_price}): {params_v3}")
        try:
            order = await exchange.create_order(symbol, "market", "sell", 0.001, current_price, params_v3)
            print(f"  SUCCESS: id={order['id']} status={order['status']} avg={order.get('average')}")
            print(f"  Raw: {order}")
        except Exception as e:
            print(f"  FAILED: {e}")

    finally:
        await exchange.close()

asyncio.run(main())
