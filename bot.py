import os
import time
import logging
from datetime import datetime
import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOLD_API_KEY = os.environ.get("GOLD_API_KEY")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data, timeout=10)
        logger.info(f"Telegram: {r.status_code}")
        return r.ok
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def get_live_price():
    try:
        url = "https://www.goldapi.io/api/XAU/USD"
        headers = {"x-access-token": GOLD_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data.get("price")
        logger.info(f"Live gold price: {price}")
        return float(price)
    except Exception as e:
        logger.error(f"Gold API error: {e}")
        return None

price_history = []

def update_history(price):
    price_history.append(price)
    if len(price_history) > 200:
        price_history.pop(0)

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    series = pd.Series(prices)
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def calculate_ema(prices, span):
    if len(prices) < span:
        return prices[-1]
    return pd.Series(prices).ewm(span=span, adjust=False).mean().iloc[-1]

def calculate_macd(prices):
    if len(prices) < 26:
        return 0, 0
    series = pd.Series(prices)
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return hist.iloc[-1], hist.iloc[-2] if len(hist) > 1 else 0

def generate_signal(price):
    update_history(price)

    if len(price_history) < 50:
        return None, 50, 0, 1

    prices = price_history
    ema9  = calculate_ema(prices, 9)
    ema21 = calculate_ema(prices, 21)
    ema50 = calculate_ema(prices, 50)
    ema200 = calculate_ema(prices, min(200, len(prices)))
    rsi = calculate_rsi(prices)
    macd_hist, macd_prev = calculate_macd(prices)

    recent = prices[-20:]
    atr = max(recent) - min(recent)
    if atr < 1:
        atr = price * 0.003

    # Count signals out of 10 possible points
    buys = sells = 0

    # EMA alignment (3 points)
    if ema9 > ema21 > ema50:
        buys += 3
    elif ema9 < ema21 < ema50:
        sells += 3

    # Price vs EMA200 (2 points)
    if price > ema200:
        buys += 2
    else:
        sells += 2

    # RSI (2 points)
    if rsi < 35:
        buys += 2
    elif rsi > 65:
        sells += 2
    elif 35 <= rsi < 45:
        buys += 1
    elif 55 < rsi <= 65:
        sells += 1

    # MACD histogram (2 points)
    if macd_hist > 0 and macd_hist > macd_prev:
        buys += 2
    elif macd_hist < 0 and macd_hist < macd_prev:
        sells += 2

    # Price momentum (1 point)
    if len(prices) >= 5:
        if prices[-1] > prices[-5]:
            buys += 1
        else:
            sells += 1

    total = buys + sells
    if total == 0:
        return None, rsi, 0, atr

    if buys > sells:
        raw_conf = buys / total  # 0.0 to 1.0
        # Scale to 85–100% range only when strong enough
        if raw_conf >= 0.80:
            conf = int(85 + (raw_conf - 0.80) / 0.20 * 15)
            conf = min(conf, 100)
            return "BUY", rsi, conf, atr
    elif sells > buys:
        raw_conf = sells / total
        if raw_conf >= 0.80:
            conf = int(85 + (raw_conf - 0.80) / 0.20 * 15)
            conf = min(conf, 100)
            return "SELL", rsi, conf, atr

    return None, rsi, 0, atr

def build_message(price, direction, rsi, conf, atr):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    rsi_str = f"{rsi:.1f}" if rsi else "N/A"
    rsi_comment = "⚠️ Oversold" if rsi and rsi < 35 else "⚠️ Overbought" if rsi and rsi > 65 else "✅ Neutral"

    # Strength bar
    filled = int((conf - 85) / 15 * 10) if conf >= 85 else 0
    bar = "🟩" * filled + "⬜" * (10 - filled)

    if direction == "BUY":
        tp = price + (atr * 2.0)
        sl = price - (atr * 1.0)
        return f"""
🟢 *XAUUSD BUY SIGNAL* 📈
━━━━━━━━━━━━━━━━━━━━
💰 *Live Price:* `${price:,.2f}`
⏰ `{now}`

📊 *TRADE DETAILS*
├ 🎯 Entry: `${price:,.2f}`
├ ✅ TP:    `${tp:,.2f}`
└ ❌ SL:    `${sl:,.2f}`

📉 RSI: `{rsi_str}` {rsi_comment}
💪 Strength: `{conf}%`
{bar}
⚠️ _Trade at your own risk_
━━━━━━━━━━━━━━━━━━━━
"""
    elif direction == "SELL":
        tp = price - (atr * 2.0)
        sl = price + (atr * 1.0)
        return f"""
🔴 *XAUUSD SELL SIGNAL* 📉
━━━━━━━━━━━━━━━━━━━━
💰 *Live Price:* `${price:,.2f}`
⏰ `{now}`

📊 *TRADE DETAILS*
├ 🎯 Entry: `${price:,.2f}`
├ ✅ TP:    `${tp:,.2f}`
└ ❌ SL:    `${sl:,.2f}`

📉 RSI: `{rsi_str}` {rsi_comment}
💪 Strength: `{conf}%`
{bar}
⚠️ _Trade at your own risk_
━━━━━━━━━━━━━━━━━━━━
"""
    else:
        trend = "↑ Bullish" if len(price_history) > 1 and price > price_history[0] else "↓ Bearish"
        return f"""
📡 *XAUUSD LIVE UPDATE*
━━━━━━━━━━━━━━━━━━━
💰 Price: `${price:,.2f}`
⏰ `{now}`
📊 Trend: `{trend}`
📉 RSI: `{rsi_str}` {rsi_comment}

_Signal strength below 85%. Monitoring for stronger setup..._
━━━━━━━━━━━━━━━━━━━
"""

def main():
    logger.info("Bot starting - signals only 85-100% strength...")
    send_telegram("🤖 *XAUUSD Signal Bot LIVE!*\n\n✅ Real-time gold prices\n💪 Only 85-100% strength signals\n📡 Checking every 5 minutes\n\n_Collecting price data... first signal in ~10 mins_ 🚀")

    while True:
        try:
            price = get_live_price()
            if price:
                direction, rsi, conf, atr = generate_signal(price)
                msg = build_message(price, direction, rsi, conf, atr)
                send_telegram(msg)
            else:
                logger.warning("Could not fetch price")
        except Exception as e:
            logger.error(f"Error: {e}")

        logger.info("Sleeping 5 minutes...")
        time.sleep(300)

if __name__ == "__main__":
    main()
