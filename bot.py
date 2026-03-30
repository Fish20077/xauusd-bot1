import os
import asyncio
import logging
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def get_xauusd_data():
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period="5d", interval="5m")
    return df


def calculate_indicators(df):
    close = df["Close"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal_line

    return {
        "ema9": ema9.iloc[-1],
        "ema21": ema21.iloc[-1],
        "ema50": ema50.iloc[-1],
        "rsi": rsi.iloc[-1],
        "macd_hist": histogram.iloc[-1],
        "macd_hist_prev": histogram.iloc[-2],
        "close": close.iloc[-1],
        "high": df["High"].iloc[-1],
        "low": df["Low"].iloc[-1],
    }


def generate_signal(indicators):
    price = indicators["close"]
    rsi = indicators["rsi"]
    ema9 = indicators["ema9"]
    ema21 = indicators["ema21"]
    ema50 = indicators["ema50"]
    macd_hist = indicators["macd_hist"]
    macd_hist_prev = indicators["macd_hist_prev"]

    buy_signals = 0
    sell_signals = 0

    if ema9 > ema21 > ema50:
        buy_signals += 2
    elif ema9 < ema21 < ema50:
        sell_signals += 2

    if rsi < 40:
        buy_signals += 2
    elif rsi > 60:
        sell_signals += 2
    elif 40 <= rsi <= 50:
        buy_signals += 1
    elif 50 < rsi <= 60:
        sell_signals += 1

    if macd_hist > 0 and macd_hist > macd_hist_prev:
        buy_signals += 2
    elif macd_hist < 0 and macd_hist < macd_hist_prev:
        sell_signals += 2

    if price > ema21:
        buy_signals += 1
    else:
        sell_signals += 1

    total = buy_signals + sell_signals
    if total == 0:
        return None

    atr = abs(indicators["high"] - indicators["low"])

    if buy_signals > sell_signals:
        confidence = int((buy_signals / total) * 100)
        if confidence < 55:
            return None
        return {
            "direction": "BUY",
            "confidence": confidence,
            "entry": round(price, 2),
            "tp": round(price + (atr * 1.8), 2),
            "sl": round(price - (atr * 1.0), 2),
            "rsi": round(rsi, 1),
        }
    elif sell_signals > buy_signals:
        confidence = int((sell_signals / total) * 100)
        if confidence < 55:
            return None
        return {
            "direction": "SELL",
            "confidence": confidence,
            "entry": round(price, 2),
            "tp": round(price - (atr * 1.8), 2),
            "sl": round(price + (atr * 1.0), 2),
            "rsi": round(rsi, 1),
        }
    return None


def format_signal_message(signal, price):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    direction = signal["direction"]
    emoji = "🟢" if direction == "BUY" else "🔴"
    arrow = "📈" if direction == "BUY" else "📉"
    rsi = signal["rsi"]
    rsi_comment = "⚠️ Oversold" if rsi < 35 else "⚠️ Overbought" if rsi > 65 else "✅ Neutral"

    return f"""
{emoji} *XAUUSD {direction} SIGNAL* {arrow}
━━━━━━━━━━━━━━━━━━━━
💰 *Live Price:* `${price:,.2f}`
⏰ *Time:* `{now}`

📊 *TRADE DETAILS*
├ 🎯 Entry:  `${signal['entry']:,.2f}`
├ ✅ TP:     `${signal['tp']:,.2f}`
└ ❌ SL:     `${signal['sl']:,.2f}`

📉 *INDICATORS*
├ RSI: `{signal['rsi']}` {rsi_comment}
└ Signal Strength: `{signal['confidence']}%`

⚠️ _Trade at your own risk._
━━━━━━━━━━━━━━━━━━━━
"""


def format_price_message(price, indicators):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    trend = "↑ Bullish" if indicators["ema9"] > indicators["ema21"] else "↓ Bearish"
    return f"""
📡 *XAUUSD LIVE UPDATE*
━━━━━━━━━━━━━━━━━━━
💰 Price: `${price:,.2f}`
⏰ Time:  `{now}`
📊 Trend: `{trend}`
📉 RSI:   `{round(indicators['rsi'], 1)}`

_No strong signal. Monitoring..._
"""


async def send_signal(bot: Bot):
    try:
        df = get_xauusd_data()
        if df.empty or len(df) < 30:
            logger.warning("Not enough data")
            return
        indicators = calculate_indicators(df)
        price = indicators["close"]
        signal = generate_signal(indicators)
        msg = format_signal_message(signal, price) if signal else format_price_message(price, indicators)
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        logger.info(f"Sent. Price: {price}, Signal: {signal['direction'] if signal else 'None'}")
    except Exception as e:
        logger.error(f"Error in send_signal: {e}")


async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *XAUUSD Signal Bot Active!*\n\nSending BUY/SELL signals every 5 minutes with Entry, TP and SL!\n\nUse /price for instant signal 🚀",
        parse_mode="Markdown"
    )
    bot = context.bot
    await send_signal(bot)


async def price_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching live price...")
    await send_signal(context.bot)


async def run_scheduler(bot: Bot):
    while True:
        await asyncio.sleep(300)  # 5 minutes
        await send_signal(bot)


async def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set!")
    if not CHAT_ID:
        raise ValueError("TELEGRAM_CHAT_ID not set!")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("price", price_command))

    bot = Bot(token=TOKEN)

    # Send first signal on startup
    await send_signal(bot)

    # Run scheduler in background
    asyncio.create_task(run_scheduler(bot))

    logger.info("Bot started!")
    await app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
