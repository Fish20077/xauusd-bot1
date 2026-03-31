import os
import time
import logging
from datetime import datetime
import requests
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
GOLD_API_KEY = os.environ.get('GOLD_API_KEY')

TP_PIPS = 50
SL_PIPS = 25
PIP = 0.10

# Store candle history for indicators
candle_history = []

def send_telegram(msg):
    url = 'https://api.telegram.org/bot' + TOKEN + '/sendMessage'
    data = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, data=data, timeout=10)
        return r.ok
    except Exception as e:
        logger.error('Telegram error: ' + str(e))
        return False

def get_spot_price():
    # Source 1: GoldAPI.io - true XAUUSD spot
    try:
        url = 'https://www.goldapi.io/api/XAU/USD'
        headers = {'x-access-token': GOLD_API_KEY}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = data.get('price')
        open_price = data.get('open_price')
        high = data.get('high_price')
        low = data.get('low_price')
        if price:
            logger.info('GoldAPI spot: ' + str(price))
            return float(price), float(open_price or price), float(high or price), float(low or price)
    except Exception as e:
        logger.error('GoldAPI error: ' + str(e))

    # Source 2: Frankfurter / metals API fallback
    try:
        url = 'https://api.metals.live/v1/spot/gold'
        r = requests.get(url, timeout=10)
        data = r.json()
        price = float(data[0].get('price'))
        logger.info('Metals.live spot: ' + str(price))
        return price, price, price, price
    except Exception as e:
        logger.error('Metals.live error: ' + str(e))

    # Source 3: Gold-API.com free
    try:
        url = 'https://gold-api.com/price/XAU'
        r = requests.get(url, timeout=10)
        data = r.json()
        price = float(data.get('price'))
        logger.info('Gold-api.com spot: ' + str(price))
        return price, price, price, price
    except Exception as e:
        logger.error('Gold-api.com error: ' + str(e))

    return None, None, None, None

def update_candles(price, open_p, high, low):
    candle = {'close': price, 'open': open_p, 'high': high, 'low': low}
    candle_history.append(candle)
    if len(candle_history) > 300:
        candle_history.pop(0)

def get_series():
    closes = [c['close'] for c in candle_history]
    highs  = [c['high']  for c in candle_history]
    lows   = [c['low']   for c in candle_history]
    return pd.Series(closes), pd.Series(highs), pd.Series(lows)

def analyze():
    if len(candle_history) < 50:
        return None

    close, high, low = get_series()
    price = close.iloc[-1]

    ema9   = close.ewm(span=9,   adjust=False).mean()
    ema21  = close.ewm(span=21,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema200 = close.ewm(span=min(200, len(close)), adjust=False).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss))

    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_sig  = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_sig

    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    swing_high = high.rolling(14).max()
    swing_low  = low.rolling(14).min()

    macd_cross_up   = float(macd_line.iloc[-1]) > float(macd_sig.iloc[-1]) and float(macd_line.iloc[-2]) <= float(macd_sig.iloc[-2])
    macd_cross_down = float(macd_line.iloc[-1]) < float(macd_sig.iloc[-1]) and float(macd_line.iloc[-2]) >= float(macd_sig.iloc[-2])

    return {
        'price':       price,
        'ema9':        float(ema9.iloc[-1]),
        'ema21':       float(ema21.iloc[-1]),
        'ema50':       float(ema50.iloc[-1]),
        'ema200':      float(ema200.iloc[-1]),
        'rsi':         float(rsi.iloc[-1]),
        'macd_hist':   float(macd_hist.iloc[-1]),
        'macd_prev':   float(macd_hist.iloc[-2]),
        'macd_cross_up':   macd_cross_up,
        'macd_cross_down': macd_cross_down,
        'atr':         float(atr.iloc[-1]),
        'swing_high':  float(swing_high.iloc[-1]),
        'swing_low':   float(swing_low.iloc[-1]),
        'hh':          price > float(close.iloc[-6]),
        'll':          price < float(close.iloc[-6]),
    }

def generate_signal(ind):
    price = ind['price']
    rsi = ind['rsi']
    buys = sells = 0

    # Major trend EMA200 - 3pts
    if price > ind['ema200']: buys += 3
    else: sells += 3

    # EMA alignment - 3pts
    if ind['ema9'] > ind['ema21'] > ind['ema50']: buys += 3
    elif ind['ema9'] < ind['ema21'] < ind['ema50']: sells += 3

    # MACD cross - 2pts
    if ind['macd_cross_up']: buys += 2
    elif ind['macd_cross_down']: sells += 2
    elif ind['macd_hist'] > 0 and ind['macd_hist'] > ind['macd_prev']: buys += 1
    elif ind['macd_hist'] < 0 and ind['macd_hist'] < ind['macd_prev']: sells += 1

    # RSI - 2pts
    if 45 <= rsi <= 65 and buys > sells: buys += 2
    elif 35 <= rsi <= 55 and sells > buys: sells += 2
    elif rsi < 35: buys += 2
    elif rsi > 65: sells += 2

    # Structure - 1pt
    if ind['hh']: buys += 1
    elif ind['ll']: sells += 1

    total = buys + sells
    if total == 0: return None

    if buys > sells:
        raw = buys / total
        conf = min(int(50 + raw * 50), 99)
        entry = round(ind['swing_high'] + PIP * 3, 2)
        return {'type': 'BUY STOP', 'entry': entry,
                'tp': round(entry + TP_PIPS * PIP, 2),
                'sl': round(entry - SL_PIPS * PIP, 2),
                'rsi': round(rsi, 1), 'conf': conf,
                'buys': buys, 'sells': sells}
    else:
        raw = sells / total
        conf = min(int(50 + raw * 50), 99)
        entry = round(ind['swing_low'] - PIP * 3, 2)
        return {'type': 'SELL STOP', 'entry': entry,
                'tp': round(entry - TP_PIPS * PIP, 2),
                'sl': round(entry + SL_PIPS * PIP, 2),
                'rsi': round(rsi, 1), 'conf': conf,
                'buys': buys, 'sells': sells}

def strength_bar(conf):
    filled = max(0, int((conf - 50) / 50 * 10))
    if conf >= 80: block = '\U0001F7E9'
    elif conf >= 65: block = '\U0001F7E8'
    else: block = '\U0001F7E5'
    return block * filled + '\u2B1C' * (10 - filled)

def strength_label(conf):
    if conf >= 80: return '\U0001F525 STRONG'
    elif conf >= 65: return '\u26A1 MODERATE'
    else: return '\U0001F7E1 WEAK'

def build_msg(s, ind):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    price = ind['price']
    conf = s['conf']
    major = 'Bullish' if price > ind['ema200'] else 'Bearish'
    trend = 'Bullish' if ind['ema9'] > ind['ema21'] else 'Bearish'

    if s['type'] == 'BUY STOP':
        header = '\U0001F7E2 *XAUUSD BUY STOP* \U0001F4C8'
        note = '_On MT5: New Order > Buy Stop > Set entry, TP, SL_'
    else:
        header = '\U0001F534 *XAUUSD SELL STOP* \U0001F4C9'
        note = '_On MT5: New Order > Sell Stop > Set entry, TP, SL_'

    msg  = header + '\n'
    msg += '\u2501' * 22 + '\n'
    msg += '\U0001F4B0 *XAUUSD Spot: `$' + '{:,.2f}'.format(price) + '`*\n'
    msg += '\u23F0 `' + now + '`\n\n'
    msg += '\U0001F4CB *ORDER DETAILS*\n'
    msg += '\u251C \U0001F3AF Pending Entry: `$' + '{:,.2f}'.format(s['entry']) + '`\n'
    msg += '\u251C \u2705 Take Profit:  `$' + '{:,.2f}'.format(s['tp']) + '`\n'
    msg += '\u2514 \u274C Stop Loss:    `$' + '{:,.2f}'.format(s['sl']) + '`\n\n'
    msg += '\U0001F4CA *MARKET ANALYSIS*\n'
    msg += '\u251C Major Trend: `' + major + '` (EMA200)\n'
    msg += '\u251C M5 Trend:    `' + trend + '` (EMA9/21)\n'
    msg += '\u251C RSI:         `' + str(s['rsi']) + '`\n'
    msg += '\u251C Score: `' + str(s['buys']) + ' BUY vs ' + str(s['sells']) + ' SELL`\n'
    msg += '\u2514 RR: `1:2` \U0001F3AF\n\n'
    msg += '\U0001F4AA Strength: `' + str(conf) + '%` ' + strength_label(conf) + '\n'
    msg += strength_bar(conf) + '\n\n'
    msg += note + '\n'
    msg += '\u26A0\uFE0F _DEMO ONLY - 1 trade at a time!_\n'
    msg += '\u2501' * 22
    return msg

def main():
    logger.info('Bot starting...')
    send_telegram(
        '\U0001F916 *XAUUSD Spot Signal Bot*\n\n'
        '\u2705 Same price as MT5/Exness\n'
        '\U0001F3AF BUY STOP / SELL STOP\n'
        '\U0001F4B0 TP: +50 pips | SL: -25 pips\n'
        '\U0001F4CA RR: 1:2\n'
        '\U0001F6E1 *DEMO MODE - Practice first!*\n\n'
        '_Collecting spot price data..._\n'
        '_Signals start in ~10 mins_ \U0001F680'
    )

    while True:
        try:
            price, open_p, high, low = get_spot_price()
            if price:
                update_candles(price, open_p, high, low)
                ind = analyze()
                if ind:
                    s = generate_signal(ind)
                    if s:
                        msg = build_msg(s, ind)
                        send_telegram(msg)
                    else:
                        now = datetime.utcnow().strftime('%H:%M UTC')
                        trend = 'Bullish' if ind['ema9'] > ind['ema21'] else 'Bearish'
                        send_telegram(
                            '\U0001F4E1 *XAUUSD Update*\n'
                            '\U0001F4B0 Spot: `$' + '{:,.2f}'.format(price) + '`\n'
                            '\u23F0 `' + now + '`\n'
                            '\U0001F4CA Trend: `' + trend + '`\n'
                            '\U0001F4C9 RSI: `' + str(round(ind['rsi'], 1)) + '`\n'
                            '_Monitoring for strong setup..._'
                        )
                else:
                    logger.info('Building price history: ' + str(len(candle_history)) + '/50')
            else:
                logger.warning('Could not get spot price')

        except Exception as e:
            logger.error('Error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
