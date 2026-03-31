import os
import time
import logging
from datetime import datetime
import requests
import pandas as pd
import numpy as np
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GOLD_API_KEY = os.environ.get('GOLD_API_KEY')

TP_PIPS = 40
SL_PIPS = 20
PIP = 0.10

def send_telegram(msg):
    url = 'https://api.telegram.org/bot' + TOKEN + '/sendMessage'
    data = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, data=data, timeout=10)
        logger.info('Telegram: ' + str(r.status_code))
        return r.ok
    except Exception as e:
        logger.error('Telegram error: ' + str(e))
        return False

def get_live_price():
    # Try GoldAPI first
    try:
        url = 'https://www.goldapi.io/api/XAU/USD'
        headers = {'x-access-token': GOLD_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data.get('price')
        if price is not None:
            logger.info('GoldAPI price: ' + str(price))
            return float(price), 'GoldAPI'
    except Exception as e:
        logger.error('GoldAPI error: ' + str(e))

    # Fallback to Yahoo Finance
    try:
        ticker = yf.Ticker('GC=F')
        df = ticker.history(period='1d', interval='1m')
        if not df.empty:
            price = float(df['Close'].iloc[-1])
            logger.info('Yahoo price: ' + str(price))
            return price, 'Yahoo'
    except Exception as e:
        logger.error('Yahoo price error: ' + str(e))

    return None, None

def get_historical_data():
    try:
        df = yf.Ticker('GC=F').history(period='5d', interval='5m')
        if not df.empty and len(df) >= 50:
            logger.info('Got ' + str(len(df)) + ' candles')
            return df
    except Exception as e:
        logger.error('Historical data error: ' + str(e))
    return None

def calculate_indicators(df, live_price):
    # Replace last close with live price
    df = df.copy()
    df.iloc[-1, df.columns.get_loc('Close')] = live_price

    close = df['Close']
    high  = df['High']
    low   = df['Low']

    ema9  = close.ewm(span=9,  adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_hist = (ema12 - ema26).ewm(span=9, adjust=False).mean()

    swing_high = high.rolling(10).max()
    swing_low  = low.rolling(10).min()

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    return {
        'ema9':       float(ema9.iloc[-1]),
        'ema21':      float(ema21.iloc[-1]),
        'ema50':      float(ema50.iloc[-1]),
        'rsi':        float(rsi.iloc[-1]),
        'macd_hist':  float(macd_hist.iloc[-1]),
        'macd_prev':  float(macd_hist.iloc[-2]),
        'swing_high': float(swing_high.iloc[-1]),
        'swing_low':  float(swing_low.iloc[-1]),
        'atr':        float(atr.iloc[-1]),
        'prev_close': float(close.iloc[-2]),
    }

def generate_signal(ind, live_price):
    buys = sells = 0

    if ind['ema9'] > ind['ema21'] > ind['ema50']: buys += 3
    elif ind['ema9'] < ind['ema21'] < ind['ema50']: sells += 3

    rsi = ind['rsi']
    if rsi < 40: buys += 2
    elif rsi > 60: sells += 2
    else: buys += 1; sells += 1

    if ind['macd_hist'] > 0 and ind['macd_hist'] > ind['macd_prev']: buys += 3
    elif ind['macd_hist'] < 0 and ind['macd_hist'] < ind['macd_prev']: sells += 3

    if live_price > ind['prev_close']: buys += 2
    else: sells += 2

    total = buys + sells
    if total == 0:
        return None

    if buys > sells:
        raw = buys / total
        if raw < 0.80: return None
        conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)
        entry = round(ind['swing_high'] + PIP * 2, 2)
        if entry - live_price > SL_PIPS * PIP * 3: return None
        return {'type': 'BUY STOP', 'entry': entry,
                'tp': round(entry + TP_PIPS * PIP, 2),
                'sl': round(entry - SL_PIPS * PIP, 2),
                'rsi': round(rsi, 1), 'conf': conf}

    elif sells > buys:
        raw = sells / total
        if raw < 0.80: return None
        conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)
        entry = round(ind['swing_low'] - PIP * 2, 2)
        if live_price - entry > SL_PIPS * PIP * 3: return None
        return {'type': 'SELL STOP', 'entry': entry,
                'tp': round(entry - TP_PIPS * PIP, 2),
                'sl': round(entry + SL_PIPS * PIP, 2),
                'rsi': round(rsi, 1), 'conf': conf}

    return None

def build_signal_msg(signal, live_price, source):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    conf = signal['conf']
    filled = int((conf - 85) / 15 * 10)
    bar = '\U0001F7E9' * filled + '\u2B1C' * (10 - filled)
    t = signal['type']

    if t == 'BUY STOP':
        header = '\U0001F7E2 *XAUUSD BUY STOP* \U0001F4C8'
        note = '_Set BUY STOP at entry price. Trade opens & profits when price breaks up!_'
    else:
        header = '\U0001F534 *XAUUSD SELL STOP* \U0001F4C9'
        note = '_Set SELL STOP at entry price. Trade opens & profits when price breaks down!_'

    msg  = header + '\n'
    msg += '\u2501' * 20 + '\n'
    msg += '\U0001F4B0 *Current Price:* `$' + '{:,.2f}'.format(live_price) + '`\n'
    msg += '\u23F0 `' + now + '`\n\n'
    msg += '\U0001F4CB *ORDER DETAILS (Exness)*\n'
    msg += '\u251C \U0001F3AF Pending Entry: `$' + '{:,.2f}'.format(signal['entry']) + '`\n'
    msg += '\u251C \u2705 Take Profit:  `$' + '{:,.2f}'.format(signal['tp']) + '` (+' + str(TP_PIPS) + ' pips)\n'
    msg += '\u2514 \u274C Stop Loss:    `$' + '{:,.2f}'.format(signal['sl']) + '` (-' + str(SL_PIPS) + ' pips)\n\n'
    msg += '\U0001F4CA *INDICATORS*\n'
    msg += '\u251C RSI: `' + str(signal['rsi']) + '`\n'
    msg += '\u251C Risk/Reward: `1:2\n'
    msg += '\u2514 Strength: `' + str(conf) + '%`\n'
    msg += bar + '\n\n'
    msg += note + '\n'
    msg += '\u26A0\uFE0F _Manage your risk. Never risk more than 1-2% per trade._\n'
    msg += '\u2501' * 20
    return msg

def build_update_msg(ind, live_price, source):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    trend = 'Bullish' if ind['ema9'] > ind['ema21'] else 'Bearish'
    rsi = round(ind['rsi'], 1)
    msg  = '\U0001F4E1 *XAUUSD M5 MONITOR*\n'
    msg += '\u2501' * 20 + '\n'
    msg += '\U0001F4B0 Price: `$' + '{:,.2f}'.format(live_price) + '` (' + source + ')\n'
    msg += '\u23F0 `' + now + '`\n'
    msg += '\U0001F4CA Trend: `' + trend + '`\n'
    msg += '\U0001F4C9 RSI: `' + str(rsi) + '`\n'
    msg += '\U0001F539 Swing High: `$' + '{:,.2f}'.format(ind['swing_high']) + '`\n'
    msg += '\U0001F538 Swing Low:  `$' + '{:,.2f}'.format(ind['swing_low']) + '`\n\n'
    msg += '_No 85%+ breakout setup yet. Monitoring..._\n'
    msg += '\u2501' * 20
    return msg

def main():
    logger.info('Bot starting...')
    send_telegram(
        '\U0001F916 *XAUUSD Breakout Bot LIVE!*\n\n'
        '\u2705 M5 Timeframe | Exness\n'
        '\U0001F3AF BUY STOP / SELL STOP signals\n'
        '\U0001F4AA Only 85-100% strength\n'
        '\U0001F4B0 Target: 40 pips | SL: 20 pips\n'
        '\U0001F4CA RR: 1:2\n\n'
        '_First signal coming shortly..._ \U0001F680'
    )

    while True:
        try:
            live_price, source = get_live_price()
            df = get_historical_data()

            if live_price and df is not None:
                ind = calculate_indicators(df, live_price)
                signal = generate_signal(ind, live_price)
                if signal:
                    msg = build_signal_msg(signal, live_price, source)
                else:
                    msg = build_update_msg(ind, live_price, source)
                send_telegram(msg)
            else:
                logger.warning('Could not get data')
                send_telegram('\u26A0\uFE0F Could not fetch price data. Retrying in 5 mins...')

        except Exception as e:
            logger.error('Main loop error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
