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

# XAU/USD pip = $0.10, target 30-50 pips = $3.00 to $5.00
TP_PIPS = 40   # 40 pips target
SL_PIPS = 20   # 20 pips stop loss (1:2 RR)
PIP = 0.10     # 1 pip for XAUUSD on Exness

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
        price = float(data.get('price'))
        logger.info('Live price: ' + str(price))
        return price
    except Exception as e:
        logger.error('Gold API error: ' + str(e))
        return None

def get_historical_prices():
    try:
        df = yf.Ticker('GC=F').history(period='5d', interval='5m')
        if not df.empty:
            return df
    except Exception as e:
        logger.error('Historical fetch error: ' + str(e))
    return None

def calculate_indicators(df):
    close = df['Close']
    high = df['High']
    low = df['Low']

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
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - signal_line

    # Swing high/low for breakout levels (last 10 candles)
    swing_high = high.rolling(10).max()
    swing_low  = low.rolling(10).min()

    # ATR for volatility
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    return {
        'ema9':        float(ema9.iloc[-1]),
        'ema21':       float(ema21.iloc[-1]),
        'ema50':       float(ema50.iloc[-1]),
        'rsi':         float(rsi.iloc[-1]),
        'macd_hist':   float(macd_hist.iloc[-1]),
        'macd_prev':   float(macd_hist.iloc[-2]),
        'swing_high':  float(swing_high.iloc[-1]),
        'swing_low':   float(swing_low.iloc[-1]),
        'atr':         float(atr.iloc[-1]),
        'close':       float(close.iloc[-1]),
        'prev_close':  float(close.iloc[-2]),
    }

def generate_signal(ind, live_price):
    ema9  = ind['ema9']
    ema21 = ind['ema21']
    ema50 = ind['ema50']
    rsi   = ind['rsi']
    macd_hist = ind['macd_hist']
    macd_prev = ind['macd_prev']
    swing_high = ind['swing_high']
    swing_low  = ind['swing_low']
    atr   = ind['atr']

    buys = sells = 0

    # Trend alignment
    if ema9 > ema21 > ema50: buys += 3
    elif ema9 < ema21 < ema50: sells += 3

    # RSI
    if 40 <= rsi <= 60: buys += 1; sells += 1  # neutral - ok for breakout
    if rsi < 40: buys += 2
    elif rsi > 60: sells += 2

    # MACD momentum
    if macd_hist > 0 and macd_hist > macd_prev: buys += 3
    elif macd_hist < 0 and macd_hist < macd_prev: sells += 3

    # Price momentum
    if live_price > ind['prev_close']: buys += 2
    else: sells += 2

    total = buys + sells
    if total == 0:
        return None

    # Buy Stop setup - price approaching swing high
    if buys > sells:
        raw = buys / total
        if raw < 0.80:
            return None
        conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)

        # Buy Stop entry = just above swing high
        entry = round(swing_high + (PIP * 2), 2)
        tp    = round(entry + (TP_PIPS * PIP), 2)
        sl    = round(entry - (SL_PIPS * PIP), 2)

        # Only valid if entry is within 50 pips of current price
        if entry - live_price > SL_PIPS * PIP * 2:
            return None

        return {
            'type':   'BUY STOP',
            'entry':  entry,
            'tp':     tp,
            'sl':     sl,
            'rsi':    round(rsi, 1),
            'conf':   conf,
            'atr':    round(atr, 2),
        }

    # Sell Stop setup - price approaching swing low
    elif sells > buys:
        raw = sells / total
        if raw < 0.80:
            return None
        conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)

        # Sell Stop entry = just below swing low
        entry = round(swing_low - (PIP * 2), 2)
        tp    = round(entry - (TP_PIPS * PIP), 2)
        sl    = round(entry + (SL_PIPS * PIP), 2)

        # Only valid if entry is within 50 pips of current price
        if live_price - entry > SL_PIPS * PIP * 2:
            return None

        return {
            'type':   'SELL STOP',
            'entry':  entry,
            'tp':     tp,
            'sl':     sl,
            'rsi':    round(rsi, 1),
            'conf':   conf,
            'atr':    round(atr, 2),
        }

    return None

def build_signal_msg(signal, live_price):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    t = signal['type']
    conf = signal['conf']
    filled = int((conf - 85) / 15 * 10)
    bar = '\U0001F7E9' * filled + '\u2B1C' * (10 - filled)

    if t == 'BUY STOP':
        emoji = '\U0001F7E2'
        arrow = '\U0001F4C8'
        direction_line = '\U0001F7E2 *BUY STOP ORDER* \U0001F4C8'
        note = '_Place a BUY STOP order at entry. When price breaks up, trade runs to TP!_'
    else:
        emoji = '\U0001F534'
        arrow = '\U0001F4C9'
        direction_line = '\U0001F534 *SELL STOP ORDER* \U0001F4C9'
        note = '_Place a SELL STOP order at entry. When price breaks down, trade runs to TP!_'

    pips_tp = TP_PIPS
    pips_sl = SL_PIPS
    rr = str(round(TP_PIPS / SL_PIPS, 1))

    msg  = direction_line + '\n'
    msg += '\u2501' * 20 + '\n'
    msg += '\U0001F4B0 *Current Price:* `$' + '{:,.2f}'.format(live_price) + '`\n'
    msg += '\u23F0 `' + now + '`\n\n'
    msg += '\U0001F4CB *ORDER DETAILS*\n'
    msg += '\u251C \U0001F3AF Pending Entry: `$' + '{:,.2f}'.format(signal['entry']) + '`\n'
    msg += '\u251C \u2705 Take Profit:  `$' + '{:,.2f}'.format(signal['tp']) + '` (+' + str(pips_tp) + ' pips)\n'
    msg += '\u2514 \u274C Stop Loss:    `$' + '{:,.2f}'.format(signal['sl']) + '` (-' + str(pips_sl) + ' pips)\n\n'
    msg += '\U0001F4CA *ANALYSIS*\n'
    msg += '\u251C RSI: `' + str(signal['rsi']) + '`\n'
    msg += '\u251C ATR: `' + str(signal['atr']) + '`\n'
    msg += '\u251C Risk/Reward: `1:' + rr + '`\n'
    msg += '\u2514 Strength: `' + str(conf) + '%`\n'
    msg += bar + '\n\n'
    msg += note + '\n'
    msg += '\u26A0\uFE0F _Always use proper risk management_\n'
    msg += '\u2501' * 20
    return msg

def build_update_msg(ind, live_price):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    trend = 'Bullish' if ind['ema9'] > ind['ema21'] else 'Bearish'
    rsi = round(ind['rsi'], 1)
    msg  = '\U0001F4E1 *XAUUSD M5 UPDATE*\n'
    msg += '\u2501' * 20 + '\n'
    msg += '\U0001F4B0 Price: `$' + '{:,.2f}'.format(live_price) + '`\n'
    msg += '\u23F0 `' + now + '`\n'
    msg += '\U0001F4CA Trend: `' + trend + '`\n'
    msg += '\U0001F4C9 RSI: `' + str(rsi) + '`\n'
    msg += '\U0001F4A1 Swing High: `$' + '{:,.2f}'.format(ind['swing_high']) + '`\n'
    msg += '\U0001F4A1 Swing Low:  `$' + '{:,.2f}'.format(ind['swing_low']) + '`\n\n'
    msg += '_No 85%+ breakout setup yet. Monitoring..._\n'
    msg += '\u2501' * 20
    return msg

def main():
    logger.info('Bot starting...')
    send_telegram(
        '\U0001F916 *XAUUSD Breakout Signal Bot LIVE!*\n\n'
        '\u2705 M5 Timeframe\n'
        '\U0001F3AF BUY STOP / SELL STOP signals\n'
        '\U0001F4AA Only 85-100% strength setups\n'
        '\U0001F4B0 Target: 30-50 pips per trade\n'
        '\U0001F4CA Risk/Reward: 1:2\n\n'
        '_Loading market data... first signal in ~1 min_ \U0001F680'
    )

    while True:
        try:
            live_price = get_live_price()
            df = get_historical_prices()

            if live_price and df is not None and len(df) >= 50:
                ind = calculate_indicators(df)
                signal = generate_signal(ind, live_price)

                if signal:
                    msg = build_signal_msg(signal, live_price)
                else:
                    msg = build_update_msg(ind, live_price)

                send_telegram(msg)
            else:
                logger.warning('Not enough data yet')

        except Exception as e:
            logger.error('Main loop error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
