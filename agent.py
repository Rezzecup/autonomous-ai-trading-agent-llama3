#!/usr/bin/env python3
"""
Autonomous AI Trading Agent — Main agentic loop.
Perceive → Reason → Act. Runs one cycle or continuous loop.
"""

import argparse
import logging
import os
import sys

if sys.version_info < (3, 10):
    print("Error: Python 3.10 or newer is required. Current:", sys.version.split()[0])
    sys.exit(1)

from pathlib import Path

import yaml
from dotenv import load_dotenv

from perceive import perceive
from reason import reason
from act import act

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Load .env
load_dotenv()


def load_config(config_path: str = "config.yaml") -> dict:
    """Load config.yaml. Searches cwd first, then script directory."""
    path = Path(config_path)
    if not path.is_absolute() and not path.exists():
        # Fall back to config next to agent.py
        script_dir = Path(__file__).resolve().parent
        alt = script_dir / config_path
        if alt.exists():
            path = alt
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def get_api_keys(exchange_id: str) -> tuple[str | None, str | None]:
    """Get exchange API keys from env."""
    mapping = {
        "binance": ("BINANCE_API_KEY", "BINANCE_SECRET"),
        "bybit": ("BYBIT_API_KEY", "BYBIT_SECRET"),
        "okx": ("OKX_API_KEY", "OKX_SECRET"),
        "kraken": ("KRAKEN_API_KEY", "KRAKEN_SECRET"),
        "kucoin": ("KUCOIN_API_KEY", "KUCOIN_SECRET"),
        "coinbase": ("COINBASE_API_KEY", "COINBASE_SECRET"),
    }
    key_name, secret_name = mapping.get(exchange_id, ("API_KEY", "SECRET"))
    return os.getenv(key_name), os.getenv(secret_name)


def run_cycle(config: dict) -> int:
    """Run one Perceive → Reason → Act cycle. Returns next_check_minutes."""
    trading = config.get("trading", {})
    llm = config.get("llm", {})
    indicators = config.get("indicators", {})
    news = config.get("news", {})

    symbol = trading.get("symbol", "BTC/USDT")
    exchange_id = trading.get("exchange", "binance")
    timeframe = trading.get("timeframe", "15m")
    mode = trading.get("mode", "paper")
    position_size_pct = trading.get("position_size_pct", 5)

    api_key, secret = get_api_keys(exchange_id)

    # 1. PERCEIVE
    logger.info("PERCEIVE: Fetching market data and news for %s...", symbol)
    perception = perceive(
        symbol=symbol,
        exchange_id=exchange_id,
        timeframe=timeframe,
        api_key=api_key,
        secret=secret,
        rsi_period=indicators.get("rsi_period", 14),
        ema_fast=indicators.get("ema_fast", 9),
        ema_slow=indicators.get("ema_slow", 21),
        macd_fast=indicators.get("macd_fast", 12),
        macd_slow=indicators.get("macd_slow", 26),
        macd_signal=indicators.get("macd_signal", 9),
        news_provider=news.get("provider", "cryptopanic"),
        news_lookback_hours=news.get("lookback_hours", 2),
        news_max_headlines=news.get("max_headlines", 5),
    )

    tech = perception.get("technical_signals", {})
    if tech:
        logger.info(
            "  RSI=%.1f | EMA=%s | MACD=%.2f | BB=%s | Sentiment=%.2f",
            tech.get("rsi") or 0,
            tech.get("ema_cross", "N/A"),
            tech.get("macd_histogram") or 0,
            tech.get("bollinger_position", "N/A"),
            perception.get("news_sentiment", 0),
        )
    else:
        logger.warning("  No technical data — check exchange/symbol")

    # 2. REASON
    logger.info("REASON: Querying Chutes AI...")
    reasoning = reason(
        perception,
        model=llm.get("model", "meta-llama/Llama-3.1-8B-Instruct"),
        temperature=llm.get("temperature", 0.2),
        max_tokens=llm.get("max_tokens", 512),
    )

    decision = reasoning.get("decision", "HOLD")
    confidence = reasoning.get("confidence", 0)
    next_check = reasoning.get("next_check_minutes", 15)

    # Log reasoning block (as in README)
    print()
    print("═" * 63)
    print(f" AGENT REASONING LOG — {symbol} — {perception.get('technical_signals', {}).get('timestamp', 'N/A')}")
    print("═" * 63)
    if tech:
        rsi = tech.get("rsi")
        rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"
        rsi_note = "→ OVERSOLD" if rsi and rsi < 30 else ("→ OVERBOUGHT" if rsi and rsi > 70 else "")
        print(f" TECHNICAL SIGNALS:")
        print(f"   RSI(14)           = {rsi_str} {rsi_note}")
        print(f"   EMA(9) vs EMA(21) = {tech.get('ema_cross', 'N/A')}")
        macd = tech.get("macd_histogram")
        macd_str = f"{macd:.2f}" if macd is not None else "N/A"
        print(f"   MACD Histogram    = {macd_str}")
        print(f"   Bollinger Band    = {tech.get('bollinger_position', 'N/A')}")
    print(f" NEWS SENTIMENT:")
    print(f"   Headlines scanned : {perception.get('headlines_count', 0)}")
    print(f"   Sentiment score   : {perception.get('news_sentiment', 0):.2f}")
    if perception.get("news_headlines"):
        print(f"   Top: \"{perception['news_headlines'][0][:50]}...\"" if len(perception["news_headlines"][0]) > 50 else f"   Top: \"{perception['news_headlines'][0]}\"")
    print(" LLM REASONING:")
    for line in (reasoning.get("raw_reasoning", "") or "").split("\n")[:8]:
        print(f"   {line}")
    print(f" DECISION:   {decision}")
    print(f" CONFIDENCE: {confidence}%")
    print(f" NEXT CHECK: {next_check} minutes")
    print("═" * 63)
    print()

    # 3. ACT
    logger.info("ACT: %s (confidence %d%%)", decision, confidence)
    current_price = tech.get("price") if tech else 0.0
    if not current_price and mode == "live":
        logger.warning("No price data — skipping ACT")
    else:
        current_price = current_price or 0.0
        action_result = act(
            decision=decision,
            symbol=symbol,
            exchange_id=exchange_id,
            mode=mode,
            position_size_pct=position_size_pct,
            current_price=current_price,
            api_key=api_key,
            secret=secret,
        )
        logger.info("  %s", action_result.get("message", ""))

    return next_check


def main():
    parser = argparse.ArgumentParser(description="Autonomous AI Trading Agent — Llama 3")
    parser.add_argument("--symbol", default=None, help="Trading pair, e.g. BTC/USDT")
    parser.add_argument("--exchange", default=None, help="Exchange: binance, bybit, okx, kraken, kucoin")
    parser.add_argument("--mode", choices=["paper", "live"], default=None, help="paper or live")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--loop", action="store_true", help="Run continuously with next_check interval")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config:
        logger.error("Config not found. Create config.yaml from the README.")
        sys.exit(1)

    trading = config.setdefault("trading", {})
    if args.symbol:
        trading["symbol"] = args.symbol
    if args.exchange:
        trading["exchange"] = args.exchange
    if args.mode:
        trading["mode"] = args.mode

    try:
        if args.loop:
            import time
            while True:
                next_check = run_cycle(config)
                logger.info("Sleeping %d minutes...", next_check)
                time.sleep(next_check * 60)
        else:
            run_cycle(config)
            logger.info("Cycle complete.")
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)
    except Exception as e:
        err = str(e)
        if "Connection" in err or "fetch" in err.lower() or "network" in err.lower() or "timeout" in err.lower():
            logger.error("Network error: cannot reach exchange. Check your internet and try again.")
        else:
            logger.error("Error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
