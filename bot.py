import os
import time
import logging
from datetime import datetime
import requests
import pandas as pd
import numpy as np
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(**name**)

TOKEN = os.environ.get(“TELEGRAM_BOT_TOKEN”)
CHAT_ID = os.environ.get(“TELEGRAM_CHAT_ID”)
GOLD_API_KEY = os.environ.get(“GOLD_API_KEY”)

def send_telegram(msg):
url = f”https://api.telegram.org/bot{TOKEN}/sendMessage”
data = {“chat_id”: CHAT_ID, “text”: msg, “parse_mode”: “Markdown”}
try:
r = requests.post(url, data=data, timeout=10)
logger.info(f”Telegram: {r.status_code}”)
return r.ok
except Exception as e:
logger.error(f”Telegram error: {e}”)
return False

def get_live_price():
try:
url = “https://www.goldapi.io/api/XAU/USD”
headers = {“x-access-token”: GOLD_API_KEY}
r = requests.get(url, headers=headers, timeout=10)
data = r.json()
price = float(data.get(“price”))
logger.info(f”Live price: {price}”)
return price
except Exception as e:
logger.error(f”Gold API error: {e}”)
return None

def get_historical_prices():
“”“Bootstrap price history from Yahoo Finance”””
try:
df = yf.Ticker(“GC=F”).history(period=“5d”, interval=“5m”)
if not df.empty:
prices = df[“Close”].dropna().tolist()
logger.info(f”Loaded {len(prices)} historical prices”)
return prices
except Exception as e:
logger.error(f”Historical fetch error: {e}”)
return []

def calculate_rsi(prices, period=14):
if len(prices) < period + 1:
return 50
series = pd.Series(prices)
delta = series.diff()
gain = delta.where(delta > 0, 0).rolling(period).mean()
loss = -delta.where(delta < 0, 0).rolling(period).mean()
rs = gain / loss
rsi = 100 - (100 / (1 + rs))
return float(rsi.iloc[-1])

def calculate_ema(prices, span):
if len(prices) < 2:
return prices[-1]
return float(pd.Series(prices).ewm(span=span, adjust=False).mean().iloc[-1])

def calculate_macd(prices):
if len(prices) < 26:
return 0, 0
series = pd.Series(prices)
macd = series.ewm(span=12, adjust=False).mean() - series.ewm(span=26, adjust=False).mean()
signal = macd.ewm(span=9, adjust=False).mean()
hist = macd - signal
return float(hist.iloc[-1]), float(hist.iloc[-2])

def generate_signal(prices):
if len(prices) < 50:
return None, 50, 0, 1

```
price = prices[-1]
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

buys = sells = 0

# EMA alignment (3 pts)
if ema9 > ema21 > ema50: buys += 3
elif ema9 < ema21 < ema50: sells += 3

# Price vs EMA200 (2 pts)
if price > ema200: buys += 2
else: sells += 2

# RSI (2 pts)
if rsi < 35: buys += 2
elif rsi > 65: sells += 2
elif 35 <= rsi < 45: buys += 1
elif 55 < rsi <= 65: sells += 1

# MACD (2 pts)
if macd_hist > 0 and macd_hist > macd_prev: buys += 2
elif macd_hist < 0 and macd_hist < macd_prev: sells += 2

# Momentum (1 pt)
if price > prices[-5]: buys += 1
else: sells += 1

total = buys + sells
if total == 0:
    return None, rsi, 0, atr

if buys > sells:
    raw = buys / total
    if raw >= 0.80:
        conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)
        return "BUY", rsi, conf, atr
elif sells > buys:
    raw = sells / total
    if raw >= 0.80:
        conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)
        return "SELL", rsi, conf, atr

return None, rsi, 0, atr
```

def build_message(price, direction, rsi, conf, atr):
now = datetime.utcnow().strftime(”%Y-%m-%d %H:%M UTC”)
rsi_str = f”{rsi:.1f}”
rsi_comment = “⚠️ Oversold” if rsi < 35 else “⚠️ Overbought” if rsi > 65 else “✅ Neutral”
filled = int((conf - 85) / 15 * 10) if conf >= 85 else 0
bar = “🟩” * filled + “⬜” * (10 - filled)

```
if direction == "BUY":
    tp = price + (atr * 2.0)
    sl = price - atr
    return f"""
```

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
⚠️ *Trade at your own risk*
━━━━━━━━━━━━━━━━━━━━
“””
elif direction == “SELL”:
tp = price - (atr * 2.0)
sl = price + atr
return f”””
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
⚠️ *Trade at your own risk*
━━━━━━━━━━━━━━━━━━━━
“””
else:
trend = “↑ Bullish” if ema9 > ema21 else “↓ Bearish”
return f”””
📡 *XAUUSD LIVE UPDATE*
━━━━━━━━━━━━━━━━━━━
💰 Price: `${price:,.2f}`
⏰ `{now}`
📊 Trend: `{trend}`
📉 RSI: `{rsi_str}` {rsi_comment}
*Waiting for 85%+ signal…*
━━━━━━━━━━━━━━━━━━━
“””

# Need ema9/ema21 for trend in no-signal message

ema9_global = ema21_global = 0

def main():
global ema9_global, ema21_global
logger.info(“Bot starting…”)
send_telegram(“🤖 *XAUUSD Signal Bot LIVE!*\n\n✅ Real-time gold prices\n💪 Only 85-100% strength signals\n📡 Checking every 5 minutes\n\n_Loading historical data… first signal in ~1 min_ 🚀”)

```
# Bootstrap with historical data
price_history = get_historical_prices()
if not price_history:
    price_history = []

while True:
    try:
        live_price = get_live_price()
        if live_price:
            price_history.append(live_price)
            if len(price_history) > 500:
                price_history.pop(0)

            direction, rsi, conf, atr = generate_signal(price_history)
            ema9_global = calculate_ema(price_history, 9)
            ema21_global = calculate_ema(price_history, 21)
            msg = build_message(live_price, direction, rsi, conf, atr)
            send_telegram(msg)
        else:
            logger.warning("Could not fetch live price")
    except Exception as e:
        logger.error(f"Main loop error: {e}")

    logger.info("Sleeping 5 minutes...")
    time.sleep(300)
```

if **name** == “**main**”:
main()