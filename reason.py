"""
Reason Module — LLM Chain-of-Thought prompt engine.
Uses Chutes AI API for trading decisions.
Takes perception data, builds a structured prompt, and parses LLM output
for DECISION (BUY/SELL/HOLD) and CONFIDENCE.
"""

import logging
import os
import re
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a professional crypto trading analyst. Your task is to analyze
technical indicators and news sentiment, then output a single trading decision.

You MUST respond in this exact format at the end of your reasoning:

DECISION: <BUY|SELL|HOLD>
CONFIDENCE: <0-100>%
NEXT_CHECK: <minutes>minutes

Rules:
- BUY: Strong bullish signals, oversold bounce, positive sentiment
- SELL: Strong bearish signals, overbought, negative sentiment
- HOLD: Conflicting signals, uncertainty, or insufficient conviction
- CONFIDENCE must be 0-100
- NEXT_CHECK: suggested minutes until next analysis (e.g., 15minutes)
- Always show your chain-of-thought reasoning before the final block."""


def build_prompt(perception: dict[str, Any]) -> str:
    """Build the user prompt from perception data."""
    tech = perception.get("technical_signals", {})
    sentiment = perception.get("news_sentiment", 0.0)
    headlines = perception.get("news_headlines", [])
    symbol = perception.get("symbol", "BTC/USDT")
    count = perception.get("headlines_count", 0)

    sent_label = "Bullish" if sentiment > 0.2 else ("Bearish" if sentiment < -0.2 else "Neutral")

    lines = [
        f"Analyze {symbol} for a trading decision.",
        "",
        "TECHNICAL SIGNALS:",
    ]

    if tech:
        rsi = tech.get("rsi")
        if rsi is not None:
            rsi_note = "OVERSOLD" if rsi < 30 else ("OVERBOUGHT" if rsi > 70 else "Neutral")
            lines.append(f"  RSI(14) = {rsi:.1f} → {rsi_note}")
        ema = tech.get("ema_cross", "")
        lines.append(f"  EMA(9) vs EMA(21) = {ema}")
        macd = tech.get("macd_histogram")
        if macd is not None:
            macd_note = "Bullish" if macd > 0 else "Bearish"
            lines.append(f"  MACD Histogram = {macd:.2f} → {macd_note}")
        bb = tech.get("bollinger_position", "")
        lines.append(f"  Bollinger Band = {bb}")
        price = tech.get("price")
        if price is not None:
            lines.append(f"  Current Price = {price:.2f}")
    else:
        lines.append("  (No data)")

    lines.extend([
        "",
        "NEWS SENTIMENT:",
        f"  Headlines scanned: {count}",
        f"  Sentiment score: {sentiment:.2f} ({sent_label})",
    ])
    if headlines:
        lines.append("  Top headlines:")
        for h in headlines[:3]:
            lines.append(f"    - {h}")

    lines.extend([
        "",
        "Provide your chain-of-thought analysis, then end with:",
        "DECISION: BUY|SELL|HOLD",
        "CONFIDENCE: 0-100%",
        "NEXT_CHECK: Xminutes",
    ])

    return "\n".join(lines)


def _parse_decision(text: str) -> tuple[str, int, int]:
    """
    Parse DECISION, CONFIDENCE, NEXT_CHECK from LLM output.
    Returns (decision, confidence_pct, next_check_minutes).
    """
    decision = "HOLD"
    confidence = 50
    next_check = 15

    dec_match = re.search(r"DECISION:\s*(BUY|SELL|HOLD)", text, re.I)
    if dec_match:
        decision = dec_match.group(1).upper()

    conf_match = re.search(r"CONFIDENCE:\s*(\d+)", text)
    if conf_match:
        confidence = min(100, max(0, int(conf_match.group(1))))

    next_match = re.search(r"NEXT_CHECK:\s*(\d+)\s*minutes?", text, re.I)
    if next_match:
        next_check = min(120, max(1, int(next_match.group(1))))

    return decision, confidence, next_check


def _call_chutes_api(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Call Chutes AI API (OpenAI-compatible). Returns response content or raises."""
    api_key = os.getenv("CHUTES_API_KEY", "").strip()
    api_url = os.getenv("CHUTES_API_URL", "https://llm.chutes.ai/v1/chat/completions").strip()

    if not api_key:
        raise ValueError("CHUTES_API_KEY is not set. Add it to your .env file.")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(3):
        resp = requests.post(api_url, headers=headers, json=payload, timeout=90)
        if resp.status_code == 429:
            wait = (attempt + 1) * 5
            if attempt < 2:
                logger.info("Rate limited (429), retrying in %ds...", wait)
                import time
                time.sleep(wait)
                continue
            raise requests.HTTPError("Rate limit (429). Try again in a few minutes.", response=resp)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("Chutes API returned empty choices")
        msg = choices[0].get("message", {})
        content = msg.get("content") or ""
        return content

    raise ValueError("Request failed after retries")


def reason(
    perception: dict[str, Any],
    model: str = "meta-llama/Llama-3.1-8B-Instruct",
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> dict[str, Any]:
    """
    Run LLM CoT reasoning via Chutes AI API. Returns dict with:
    - raw_reasoning: full LLM text
    - decision: BUY | SELL | HOLD
    - confidence: 0-100
    - next_check_minutes: suggested minutes
    """
    prompt = build_prompt(perception)

    try:
        content = _call_chutes_api(prompt, model, temperature, max_tokens)
    except requests.RequestException as e:
        err_msg = str(e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                err_body = resp.json()
                err_msg = err_body.get("detail", err_body.get("error", err_msg))
            except Exception:
                raw = getattr(resp, "text", None) or ""
                if resp.status_code == 429:
                    err_msg = "Rate limit (429). Try again later."
                elif "429" in raw or "Too Many" in raw:
                    err_msg = "Rate limit (429). Try again later."
                elif raw.startswith("<"):
                    err_msg = f"HTTP {resp.status_code}"
                else:
                    err_msg = raw[:200] if raw else err_msg
        logger.error("Chutes API error: %s", err_msg)
        return {
            "raw_reasoning": f"Error: {err_msg}",
            "decision": "HOLD",
            "confidence": 0,
            "next_check_minutes": 15,
        }
    except ValueError as e:
        logger.error("%s", e)
        return {
            "raw_reasoning": f"Error: {e}",
            "decision": "HOLD",
            "confidence": 0,
            "next_check_minutes": 15,
        }

    decision, confidence, next_check = _parse_decision(content)
    return {
        "raw_reasoning": content,
        "decision": decision,
        "confidence": confidence,
        "next_check_minutes": next_check,
    }
