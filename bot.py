import os
import asyncio
import logging
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def get_xauusd_data():
    """Fetch live XAUUSD data from Yahoo Finance"""
    ticker = yf.Ticker("GC=F")  # Gold Futures (XAUUSD proxy)
    df = ticker.history(period="2d", interval="5m")
    return df


def calculate_indicators(df):
    """Calculate RSI, MACD, and EMA indicators"""
    close = df["Close"]

    # EMA
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    # MACD
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
        "macd": macd.iloc[-1],
        "macd_signal": signal_line.iloc[-1],
        "macd_hist": histogram.iloc[-1],
        "macd_hist_prev": histogram.iloc[-2],
        "close": close.iloc[-1],
        "high": df["High"].iloc[-1],
        "low": df["Low"].iloc[-1],
    }


def generate_signal(indicators):
    """Generate BUY/SELL signal with Entry, TP, SL"""
    price = indicators["close"]
    rsi = indicators["rsi"]
    ema9 = indicators["ema9"]
    ema21 = indicators["ema21"]
    ema50 = indicators["ema50"]
    macd_hist = indicators["macd_hist"]
    macd_hist_prev = indicators["macd_hist_prev"]

    buy_signals = 0
    sell_signals = 0

    # EMA crossover
    if ema9 > ema21 > ema50:
        buy_signals += 2
    elif ema9 < ema21 < ema50:
        sell_signals += 2

    # RSI
    if rsi < 40:
        buy_signals += 2
    elif rsi > 60:
        sell_signals += 2
    elif 40 <= rsi <= 50:
        buy_signals += 1
    elif 50 < rsi <= 60:
        sell_signals += 1

    # MACD histogram momentum
    if macd_hist > 0 and macd_hist > macd_hist_prev:
        buy_signals += 2
    elif macd_hist < 0 and macd_hist < macd_hist_prev:
        sell_signals += 2

    # Price vs EMA
    if price > ema21:
        buy_signals += 1
    else:
        sell_signals += 1

    total = buy_signals + sell_signals
    if total == 0:
        return None

    if buy_signals > sell_signals:
        confidence = int((buy_signals / total) * 100)
        if confidence < 55:
            return None
        atr = abs(indicators["high"] - indicators["low"])
        entry = round(price, 2)
        tp = round(price + (atr * 1.8), 2)
        sl = round(price - (atr * 1.0), 2)
        return {
            "direction": "BUY",
            "confidence": confidence,
            "entry": entry,
            "tp": tp,
            "sl": sl,
            "rsi": round(rsi, 1),
        }
    elif sell_signals > buy_signals:
        confidence = int((sell_signals / total) * 100)
        if confidence < 55:
            return None
        atr = abs(indicators["high"] - indicators["low"])
        entry = round(price, 2)
        tp = round(price - (atr * 1.8), 2)
        sl = round(price + (atr * 1.0), 2)
        return {
            "direction": "SELL",
            "confidence": confidence,
            "entry": entry,
            "tp": tp,
            "sl": sl,
            "rsi": round(rsi, 1),
        }

    return None


def format_signal_message(signal, price):
    """Format the Telegram message"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    direction = signal["direction"]
    emoji = "🟢" if direction == "BUY" else "🔴"
    arrow = "📈" if direction == "BUY" else "📉"

    rsi_comment = ""
    rsi = signal["rsi"]
    if rsi < 35:
        rsi_comment = "⚠️ Oversold"
    elif rsi > 65:
        rsi_comment = "⚠️ Overbought"
    else:
        rsi_comment = "✅ Neutral"

    msg = f"""
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

⚠️ _Trade at your own risk. Always use proper risk management._
━━━━━━━━━━━━━━━━━━━━
"""
    return msg


def format_price_message(price, indicators):
    """Format a no-signal price update"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    trend = "↑ Bullish" if indicators["ema9"] > indicators["ema21"] else "↓ Bearish"
    msg = f"""
📡 *XAUUSD LIVE UPDATE*
━━━━━━━━━━━━━━━━━━━
💰 Price: `${price:,.2f}`
⏰ Time:  `{now}`
📊 Trend: `{trend}`
📉 RSI:   `{round(indicators['rsi'], 1)}`

_No strong signal at this time. Monitoring..._
"""
    return msg


async def send_signal(bot: Bot):
    """Main function to fetch data and send signal"""
    try:
        df = get_xauusd_data()
        if df.empty or len(df) < 30:
            logger.warning("Not enough data")
            return

        indicators = calculate_indicators(df)
        price = indicators["close"]
        signal = generate_signal(indicators)

        if signal:
            msg = format_signal_message(signal, price)
        else:
            msg = format_price_message(price, indicators)

        await bot.send_message(
            chat_id=CHAT_ID, text=msg, parse_mode="Markdown"
        )
        logger.info(f"Message sent. Price: {price}, Signal: {signal['direction'] if signal else 'None'}")

    except Exception as e:
        logger.error(f"Error: {e}")
        try:
            await bot.send_message(chat_id=CHAT_ID, text=f"⚠️ Bot error: {str(e)}")
        except:
            pass


async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *XAUUSD Signal Bot Active!*\n\nI send BUY/SELL signals every 5 minutes with:\n✅ Entry Price\n✅ Take Profit (TP)\n✅ Stop Loss (SL)\n\nSit back and let me do the analysis! 🚀",
        parse_mode="Markdown"
    )


async def price_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching live price...")
    try:
        df = get_xauusd_data()
        indicators = calculate_indicators(df)
        price = indicators["close"]
        signal = generate_signal(indicators)
        if signal:
            msg = format_signal_message(signal, price)
        else:
            msg = format_price_message(price, indicators)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("price", price_command))

    bot = Bot(token=TOKEN)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_signal, "interval", minutes=5, args=[bot])
    scheduler.start()

    logger.info("Bot started. Sending signals every 5 minutes.")
    await send_signal(bot)  # Send immediately on start

    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
