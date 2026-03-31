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
    try:
        url = 'https://www.goldapi.io/api/XAU/USD'
        headers = {'x-access-token': GOLD_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data.get('price')
        if price is not None:
            return float(price), 'Live'
    except Exception as e:
        logger.error('GoldAPI error: ' + str(e))

    try:
        df = yf.Ticker('GC=F').history(period='1d', interval='1m')
        if not df.empty:
            return float(df['Close'].iloc[-1]), 'Live'
    except Exception as e:
        logger.error('Yahoo price error: ' + str(e))

    return None, None

def get_historical_data():
    try:
        df = yf.Ticker('GC=F').history(period='5d', interval='5m')
        if not df.empty and len(df) >= 50:
            return df
    except Exception as e:
        logger.error('Historical data error: ' + str(e))
    return None

def calculate_indicators(df, live_price):
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
    else:
        if ind['ema9'] > ind['ema21']: buys += 1
        else: sells += 1

    rsi = ind['rsi']
    if rsi < 40: buys += 2
    elif rsi > 60: sells += 2
    else: buys += 1; sells += 1

    if ind['macd_hist'] > 0 and ind['macd_hist'] > ind['macd_prev']: buys += 3
    elif ind['macd_hist'] < 0 and ind['macd_hist'] < ind['macd_prev']: sells += 3
    elif ind['macd_hist'] > 0: buys += 1
    else: sells += 1

    if live_price > ind['prev_close']: buys += 2
    else: sells += 2

    total = buys + sells
    if total == 0:
        return None, 0

    if buys >= sells:
        raw = buys / total
        conf = min(int(50 + raw * 50), 99)
        entry = round(ind['swing_high'] + PIP * 2, 2)
        return {
            'type': 'BUY STOP',
            'entry': entry,
            'tp': round(entry + TP_PIPS * PIP, 2),
            'sl': round(entry - SL_PIPS * PIP, 2),
            'rsi': round(rsi, 1),
            'conf': conf,
            'buys': buys,
            'sells': sells,
        }, conf
    else:
        raw = sells / total
        conf = min(int(50 + raw * 50), 99)
        entry = round(ind['swing_low'] - PIP * 2, 2)
        return {
            'type': 'SELL STOP',
            'entry': entry,
            'tp': round(entry - TP_PIPS * PIP, 2),
            'sl': round(entry + SL_PIPS * PIP, 2),
            'rsi': round(rsi, 1),
            'conf': conf,
            'buys': buys,
            'sells': sells,
        }, conf

def strength_bar(conf):
    filled = max(0, int((conf - 50) / 50 * 10))
    if conf >= 80:
        block = '\U0001F7E9'
    elif conf >= 65:
        block = '\U0001F7E8'
    else:
        block = '\U0001F7E5'
    return block * filled + '\u2B1C' * (10 - filled)

def strength_label(conf):
    if conf >= 80: return 'STRONG \U0001F525'
    elif conf >= 65: return 'MODERATE \u26A1'
    else: return 'WEAK \U0001F7E1'

def build_msg(signal, live_price, ind):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    conf = signal['conf']
    t = signal['type']
    bar = strength_bar(conf)
    label = strength_label(conf)
    trend = 'Bullish' if ind['ema9'] > ind['ema21'] else 'Bearish'

    if t == 'BUY STOP':
        header = '\U0001F7E2 *XAUUSD BUY STOP* \U0001F4C8'
        note = '_Place BUY STOP at entry. Profit when price breaks UP!_'
    else:
        header = '\U0001F534 *XAUUSD SELL STOP* \U0001F4C9'
        note = '_Place SELL STOP at entry. Profit when price breaks DOWN!_'

    msg  = header + '\n'
    msg += '\u2501' * 20 + '\n'
    msg += '\U0001F4B0 *Price:* `$' + '{:,.2f}'.format(live_price) + '`\n'
    msg += '\u23F0 `' + now + '`\n'
    msg += '\U0001F4CA Trend: `' + trend + '`\n\n'
    msg += '\U0001F4CB *ORDER DETAILS*\n'
    msg += '\u251C \U0001F3AF Entry: `$' + '{:,.2f}'.format(signal['entry']) + '`\n'
    msg += '\u251C \u2705 TP:    `$' + '{:,.2f}'.format(signal['tp']) + '` (+' + str(TP_PIPS) + ' pips)\n'
    msg += '\u2514 \u274C SL:    `$' + '{:,.2f}'.format(signal['sl']) + '` (-' + str(SL_PIPS) + ' pips)\n\n'
    msg += '\U0001F4C9 RSI: `' + str(signal['rsi']) + '`\n'
    msg += '\U0001F4AA Strength: `' + str(conf) + '%` ' + label + '\n'
    msg += bar + '\n\n'
    msg += note + '\n'
    msg += '\u26A0\uFE0F _Max 1-2% risk per trade_\n'
    msg += '\u2501' * 20
    return msg

def main():
    logger.info('Bot starting...')
    send_telegram(
        '\U0001F916 *XAUUSD Signal Bot LIVE!*\n\n'
        '\u2705 Signals every 5 minutes\n'
        '\U0001F3AF BUY STOP / SELL STOP\n'
        '\U0001F4B0 TP: +40 pips | SL: -20 pips\n'
        '\U0001F4CA RR: 1:2\n\n'
        '_Starting now..._ \U0001F680'
    )

    while True:
        try:
            live_price, source = get_live_price()
            df = get_historical_data()

            if live_price and df is not None:
                ind = calculate_indicators(df, live_price)
                signal, conf = generate_signal(ind, live_price)
                if signal:
                    msg = build_msg(signal, live_price, ind)
                    send_telegram(msg)
                else:
                    logger.warning('No signal generated')
            else:
                send_telegram('\u26A0\uFE0F Could not fetch price. Retrying in 5 mins...')

        except Exception as e:
            logger.error('Main loop error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
