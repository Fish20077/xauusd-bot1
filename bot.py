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

TP_PIPS = 50
SL_PIPS = 25
PIP = 0.10

def send_telegram(msg):
    url = 'https://api.telegram.org/bot' + TOKEN + '/sendMessage'
    data = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, data=data, timeout=10)
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
            return float(price)
    except:
        pass
    try:
        df = yf.Ticker('GC=F').history(period='1d', interval='1m')
        if not df.empty:
            return float(df['Close'].iloc[-1])
    except:
        pass
    return None

def get_data():
    try:
        df = yf.Ticker('GC=F').history(period='5d', interval='5m')
        if not df.empty and len(df) >= 100:
            return df
    except:
        pass
    return None

def analyze(df, live_price):
    df = df.copy()
    df.iloc[-1, df.columns.get_loc('Close')] = live_price
    close = df['Close']
    high  = df['High']
    low   = df['Low']

    # EMAs
    ema9   = close.ewm(span=9,   adjust=False).mean()
    ema21  = close.ewm(span=21,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss))

    # MACD
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    # ATR
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    # Swing levels
    swing_high = high.rolling(14).max()
    swing_low  = low.rolling(14).min()

    # Higher highs / lower lows (trend structure)
    hh = close.iloc[-1] > close.iloc[-6]  # price higher than 6 candles ago
    ll = close.iloc[-1] < close.iloc[-6]

    return {
        'ema9':        float(ema9.iloc[-1]),
        'ema21':       float(ema21.iloc[-1]),
        'ema50':       float(ema50.iloc[-1]),
        'ema200':      float(ema200.iloc[-1]),
        'rsi':         float(rsi.iloc[-1]),
        'macd_hist':   float(macd_hist.iloc[-1]),
        'macd_prev':   float(macd_hist.iloc[-2]),
        'macd_cross':  float(macd.iloc[-1]) > float(macd_signal.iloc[-1]) and float(macd.iloc[-2]) <= float(macd_signal.iloc[-2]),
        'macd_cross_down': float(macd.iloc[-1]) < float(macd_signal.iloc[-1]) and float(macd.iloc[-2]) >= float(macd_signal.iloc[-2]),
        'atr':         float(atr.iloc[-1]),
        'swing_high':  float(swing_high.iloc[-1]),
        'swing_low':   float(swing_low.iloc[-1]),
        'prev_close':  float(close.iloc[-2]),
        'hh':          hh,
        'll':          ll,
    }

def signal(ind, price):
    buys = sells = 0

    # 1. Major trend (EMA200) - 3 pts
    if price > ind['ema200']: buys += 3
    else: sells += 3

    # 2. EMA alignment - 3 pts
    if ind['ema9'] > ind['ema21'] > ind['ema50']: buys += 3
    elif ind['ema9'] < ind['ema21'] < ind['ema50']: sells += 3

    # 3. MACD cross - 2 pts (strongest signal)
    if ind['macd_cross']: buys += 2
    elif ind['macd_cross_down']: sells += 2
    elif ind['macd_hist'] > 0 and ind['macd_hist'] > ind['macd_prev']: buys += 1
    elif ind['macd_hist'] < 0 and ind['macd_hist'] < ind['macd_prev']: sells += 1

    # 4. RSI - 2 pts
    rsi = ind['rsi']
    if 45 <= rsi <= 60 and buys > sells: buys += 2      # bullish momentum
    elif 40 <= rsi <= 55 and sells > buys: sells += 2   # bearish momentum
    elif rsi < 35: buys += 2                             # oversold
    elif rsi > 65: sells += 2                            # overbought

    # 5. Price structure - 1 pt
    if ind['hh']: buys += 1
    elif ind['ll']: sells += 1

    total = buys + sells
    if total == 0:
        return None

    if buys > sells:
        raw = buys / total
        conf = min(int(50 + raw * 50), 99)
        entry = round(ind['swing_high'] + PIP * 3, 2)
        return {'type': 'BUY STOP', 'entry': entry,
                'tp': round(entry + TP_PIPS * PIP, 2),
                'sl': round(entry - SL_PIPS * PIP, 2),
                'rsi': round(rsi, 1), 'conf': conf,
                'buys': buys, 'sells': sells, 'total': total}
    else:
        raw = sells / total
        conf = min(int(50 + raw * 50), 99)
        entry = round(ind['swing_low'] - PIP * 3, 2)
        return {'type': 'SELL STOP', 'entry': entry,
                'tp': round(entry - TP_PIPS * PIP, 2),
                'sl': round(entry + SL_PIPS * PIP, 2),
                'rsi': round(rsi, 1), 'conf': conf,
                'buys': buys, 'sells': sells, 'total': total}

def bar(conf):
    filled = max(0, int((conf - 50) / 50 * 10))
    if conf >= 80: block = '\U0001F7E9'
    elif conf >= 65: block = '\U0001F7E8'
    else: block = '\U0001F7E5'
    return block * filled + '\u2B1C' * (10 - filled)

def label(conf):
    if conf >= 80: return '\U0001F525 STRONG'
    elif conf >= 65: return '\u26A1 MODERATE'
    else: return '\U0001F7E1 WEAK - USE CAUTION'

def build_msg(s, price, ind):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    conf = s['conf']
    trend = 'Bullish' if ind['ema9'] > ind['ema21'] else 'Bearish'
    major = 'Bullish' if price > ind['ema200'] else 'Bearish'

    if s['type'] == 'BUY STOP':
        header = '\U0001F7E2 *XAUUSD BUY STOP* \U0001F4C8'
        note = '_Place BUY STOP at entry on Exness demo_'
    else:
        header = '\U0001F534 *XAUUSD SELL STOP* \U0001F4C9'
        note = '_Place SELL STOP at entry on Exness demo_'

    msg  = header + '\n'
    msg += '\u2501' * 20 + '\n'
    msg += '\U0001F4B0 *Price:* `$' + '{:,.2f}'.format(price) + '`\n'
    msg += '\u23F0 `' + now + '`\n\n'
    msg += '\U0001F4CB *ORDER DETAILS*\n'
    msg += '\u251C \U0001F3AF Entry: `$' + '{:,.2f}'.format(s['entry']) + '`\n'
    msg += '\u251C \u2705 TP:    `$' + '{:,.2f}'.format(s['tp']) + '` (+' + str(TP_PIPS) + ' pips)\n'
    msg += '\u2514 \u274C SL:    `$' + '{:,.2f}'.format(s['sl']) + '` (-' + str(SL_PIPS) + ' pips)\n\n'
    msg += '\U0001F4CA *ANALYSIS*\n'
    msg += '\u251C Major Trend: `' + major + '`\n'
    msg += '\u251C M5 Trend:    `' + trend + '`\n'
    msg += '\u251C RSI: `' + str(s['rsi']) + '`\n'
    msg += '\u251C Score: `' + str(s['buys']) + ' buy vs ' + str(s['sells']) + ' sell pts`\n'
    msg += '\u2514 RR: `1:2` \U0001F3AF\n\n'
    msg += '\U0001F4AA *Strength: ' + str(conf) + '%* ' + label(conf) + '\n'
    msg += bar(conf) + '\n\n'
    msg += note + '\n'
    msg += '\u26A0\uFE0F _DEMO ONLY - Practice first!_\n'
    msg += '\u2501' * 20
    return msg

def main():
    logger.info('Bot starting...')
    send_telegram(
        '\U0001F916 *XAUUSD Signal Bot - DEMO MODE*\n\n'
        '\u2705 Signals every 5 minutes\n'
        '\U0001F3AF BUY STOP / SELL STOP\n'
        '\U0001F4B0 TP: +50 pips | SL: -25 pips\n'
        '\U0001F4CA RR: 1:2\n'
        '\U0001F6E1 *DEMO ACCOUNT ONLY*\n\n'
        '_Practice until consistently profitable_\n'
        '_before moving to real money!_ \U0001F4AA'
    )

    while True:
        try:
            price = get_live_price()
            df = get_data()

            if price and df is not None:
                ind = analyze(df, price)
                s = signal(ind, price)
                if s:
                    msg = build_msg(s, price, ind)
                    send_telegram(msg)
                else:
                    logger.info('No signal this cycle')
            else:
                logger.warning('No data')

        except Exception as e:
            logger.error('Error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
