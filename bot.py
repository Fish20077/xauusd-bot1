import os
import time
import logging
from datetime import datetime
import yfinance as yf
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data, timeout=10)
        logger.info(f"Telegram response: {r.status_code} {r.text}")
        return r.ok
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

def get_price():
    try:
        ticker = yf.Ticker("GC=F")
        df = ticker.history(period="5d", interval="5m")
        if df.empty or len(df) < 50:
            return None
        return df
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        return None

def analyze(df):
    close = df["Close"]
    ema9 = close.ewm(span=9).mean().iloc[-1]
    ema21 = close.ewm(span=21).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    hist = (ema12 - ema26).ewm(span=9).mean()
    macd_now = hist.iloc[-1]
    macd_prev = hist.iloc[-2]

    price = close.iloc[-1]
    atr = abs(df["High"].iloc[-1] - df["Low"].iloc[-1])

    buys = sells = 0
    if ema9 > ema21 > ema50: buys += 2
    elif ema9 < ema21 < ema50: sells += 2
    if rsi < 40: buys += 2
    elif rsi > 60: sells += 2
    if macd_now > 0 and macd_now > macd_prev: buys += 2
    elif macd_now < 0 and macd_now < macd_prev: sells += 2
    if price > ema21: buys += 1
    else: sells += 1

    total = buys + sells
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    if buys > sells and total > 0:
        conf = int(buys / total * 100)
        if conf >= 55:
            return f"""
🟢 *XAUUSD BUY SIGNAL* 📈
━━━━━━━━━━━━━━━━━━━━
💰 *Price:* `${price:,.2f}`
⏰ `{now}`

📊 *TRADE DETAILS*
├ 🎯 Entry: `${price:,.2f}`
├ ✅ TP:    `${price + atr*1.8:,.2f}`
└ ❌ SL:    `${price - atr:,.2f}`

📉 RSI: `{rsi:.1f}` | Strength: `{conf}%`
⚠️ _Trade at your own risk_
"""
    elif sells > buys and total > 0:
        conf = int(sells / total * 100)
        if conf >= 55:
            return f"""
🔴 *XAUUSD SELL SIGNAL* 📉
━━━━━━━━━━━━━━━━━━━━
💰 *Price:* `${price:,.2f}`
⏰ `{now}`

📊 *TRADE DETAILS*
├ 🎯 Entry: `${price:,.2f}`
├ ✅ TP:    `${price - atr*1.8:,.2f}`
└ ❌ SL:    `${price + atr:,.2f}`

📉 RSI: `{rsi:.1f}` | Strength: `{conf}%`
⚠️ _Trade at your own risk_
"""

    trend = "↑ Bullish" if ema9 > ema21 else "↓ Bearish"
    return f"""
📡 *XAUUSD UPDATE*
━━━━━━━━━━━━━━━━━━━
💰 Price: `${price:,.2f}`
⏰ `{now}`
📊 Trend: `{trend}`
📉 RSI: `{rsi:.1f}`
_No strong signal. Monitoring..._
"""

def main():
    logger.info("Bot starting...")
    send_telegram("🤖 *XAUUSD Signal Bot is now LIVE!*\n\nSending signals every 5 minutes 🚀")
    
    while True:
        try:
            df = get_price()
            if df is not None:
                msg = analyze(df)
                if msg:
                    send_telegram(msg)
                else:
                    logger.info("No message generated")
            else:
                logger.warning("Could not get price data")
        except Exception as e:
            logger.error(f"Main loop error: {e}")
        
        logger.info("Sleeping 5 minutes...")
        time.sleep(300)

if __name__ == "__main__":
    main()
