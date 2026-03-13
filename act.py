"""
Act Module — CCXT order execution for paper and live trading.
Executes BUY/SELL/HOLD based on agent decisions. Paper mode simulates orders.
"""

import logging
from datetime import datetime
from typing import Any, Optional

import ccxt

logger = logging.getLogger(__name__)

# Paper trading state (in-memory for simplicity)
_paper_balance: dict[str, float] = {}
_paper_positions: dict[str, dict] = {}
_paper_orders: list[dict] = []


def _get_exchange(
    exchange_id: str,
    api_key: Optional[str] = None,
    secret: Optional[str] = None,
    sandbox: bool = False,
):
    """Create CCXT exchange instance."""
    ex_class = getattr(ccxt, exchange_id, None)
    if ex_class is None:
        raise ValueError(f"Unknown exchange: {exchange_id}")
    opts = {"enableRateLimit": True}
    config = {"options": opts}
    if api_key and secret:
        config["apiKey"] = api_key
        config["secret"] = secret
    if sandbox:
        config["sandbox"] = True
    return ex_class(config)


def _paper_init_balance(symbol: str, price: float, position_size_pct: float):
    """Initialize paper balance with mock quote (USDT) and base asset."""
    base = symbol.split("/")[0]
    quote = symbol.split("/")[1] if "/" in symbol else "USDT"
    if quote not in _paper_balance:
        _paper_balance[quote] = 10000.0
    if base not in _paper_balance:
        _paper_balance[base] = 0.0


def _paper_get_balance(symbol: str) -> tuple[float, float]:
    """Get paper USDT and base asset balance."""
    base = symbol.split("/")[0]
    quote = symbol.split("/")[1] if "/" in symbol else "USDT"
    usdt = _paper_balance.get(quote, 10000.0)
    base_amt = _paper_balance.get(base, 0.0)
    return usdt, base_amt


def _paper_execute_buy(
    symbol: str,
    price: float,
    position_size_pct: float,
) -> dict[str, Any]:
    """Simulate MARKET BUY in paper mode."""
    base = symbol.split("/")[0]
    quote = symbol.split("/")[1] if "/" in symbol else "USDT"

    usdt, _ = _paper_get_balance(symbol)
    spend = usdt * (position_size_pct / 100.0)
    spend = min(spend, usdt * 0.95)
    amount = spend / price if price > 0 else 0

    _paper_balance[quote] = usdt - spend
    _paper_balance[base] = _paper_balance.get(base, 0) + amount

    order = {
        "id": f"paper_buy_{datetime.utcnow().timestamp()}",
        "symbol": symbol,
        "side": "buy",
        "type": "market",
        "amount": amount,
        "price": price,
        "cost": spend,
        "timestamp": datetime.utcnow().isoformat(),
    }
    _paper_orders.append(order)
    return order


def _paper_execute_sell(
    symbol: str,
    price: float,
    position_size_pct: float,
) -> dict[str, Any]:
    """Simulate MARKET SELL in paper mode."""
    base = symbol.split("/")[0]
    quote = symbol.split("/")[1] if "/" in symbol else "USDT"

    _, base_amt = _paper_get_balance(symbol)
    sell_pct = min(position_size_pct / 100.0, 1.0)
    amount = base_amt * sell_pct
    amount = min(amount, base_amt)

    proceeds = amount * price
    _paper_balance[base] = base_amt - amount
    _paper_balance[quote] = _paper_balance.get(quote, 0) + proceeds

    order = {
        "id": f"paper_sell_{datetime.utcnow().timestamp()}",
        "symbol": symbol,
        "side": "sell",
        "type": "market",
        "amount": amount,
        "price": price,
        "cost": proceeds,
        "timestamp": datetime.utcnow().isoformat(),
    }
    _paper_orders.append(order)
    return order


def _live_execute_buy(
    exchange_id: str,
    symbol: str,
    position_size_pct: float,
    api_key: str,
    secret: str,
) -> Optional[dict]:
    """Execute live MARKET BUY via CCXT."""
    exchange = _get_exchange(exchange_id, api_key, secret)
    try:
        balance = exchange.fetch_balance()
        quote = symbol.split("/")[1] if "/" in symbol else "USDT"
        usdt = balance.get(quote, {}).get("free", 0) or balance.get("USDT", {}).get("free", 0)
        spend = usdt * (position_size_pct / 100.0)
        spend = min(spend, usdt * 0.95)

        ticker = exchange.fetch_ticker(symbol)
        price = ticker.get("last") or ticker.get("close", 0)
        amount = spend / price if price > 0 else 0

        if amount <= 0:
            return None
        order = exchange.create_market_buy_order(symbol, amount)
        return order
    except Exception as e:
        logger.error("Live BUY failed: %s", e)
        return None


def _live_execute_sell(
    exchange_id: str,
    symbol: str,
    position_size_pct: float,
    api_key: str,
    secret: str,
) -> Optional[dict]:
    """Execute live MARKET SELL via CCXT."""
    exchange = _get_exchange(exchange_id, api_key, secret)
    try:
        balance = exchange.fetch_balance()
        base = symbol.split("/")[0]
        base_amt = balance.get(base, {}).get("free", 0)
        sell_pct = min(position_size_pct / 100.0, 1.0)
        amount = base_amt * sell_pct
        amount = max(amount, 0)

        if amount <= 0:
            return None
        order = exchange.create_market_sell_order(symbol, amount)
        return order
    except Exception as e:
        logger.error("Live SELL failed: %s", e)
        return None


def act(
    decision: str,
    symbol: str,
    exchange_id: str,
    mode: str,
    position_size_pct: float,
    current_price: float,
    api_key: Optional[str] = None,
    secret: Optional[str] = None,
) -> dict[str, Any]:
    """
    Execute trading action based on decision.
    Returns dict with action_taken, order (if any), message.
    """
    result = {"action_taken": "NONE", "order": None, "message": ""}

    if decision == "HOLD":
        result["message"] = "HOLD — No action"
        return result

    if decision not in ("BUY", "SELL"):
        result["message"] = f"Unknown decision: {decision}"
        return result

    if mode == "paper":
        _paper_init_balance(symbol, current_price, position_size_pct)
        if decision == "BUY":
            order = _paper_execute_buy(symbol, current_price, position_size_pct)
            result["action_taken"] = "PAPER_BUY"
            result["order"] = order
            result["message"] = f"Paper BUY {order['amount']:.6f} @ {current_price:.2f}"
        else:
            order = _paper_execute_sell(symbol, current_price, position_size_pct)
            result["action_taken"] = "PAPER_SELL"
            result["order"] = order
            result["message"] = f"Paper SELL {order['amount']:.6f} @ {current_price:.2f}"
    else:
        if not api_key or not secret:
            result["message"] = "Live mode requires API keys"
            return result
        if decision == "BUY":
            order = _live_execute_buy(exchange_id, symbol, position_size_pct, api_key, secret)
            if order:
                result["action_taken"] = "LIVE_BUY"
                result["order"] = order
                result["message"] = f"Live BUY executed: {order.get('id', 'N/A')}"
            else:
                result["message"] = "Live BUY failed or insufficient balance"
        else:
            order = _live_execute_sell(exchange_id, symbol, position_size_pct, api_key, secret)
            if order:
                result["action_taken"] = "LIVE_SELL"
                result["order"] = order
                result["message"] = f"Live SELL executed: {order.get('id', 'N/A')}"
            else:
                result["message"] = "Live SELL failed or no position"

    return result
