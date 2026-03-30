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
            prices = df['Close'].dropna().tolist()
            logger.info('Loaded ' + str(len(prices)) + ' historical prices')
            return prices
    except Exception as e:
        logger.error('Historical fetch error: ' + str(e))
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

    if ema9 > ema21 > ema50: buys += 3
    elif ema9 < ema21 < ema50: sells += 3

    if price > ema200: buys += 2
    else: sells += 2

    if rsi < 35: buys += 2
    elif rsi > 65: sells += 2
    elif 35 <= rsi < 45: buys += 1
    elif 55 < rsi <= 65: sells += 1

    if macd_hist > 0 and macd_hist > macd_prev: buys += 2
    elif macd_hist < 0 and macd_hist < macd_prev: sells += 2

    if price > prices[-5]: buys += 1
    else: sells += 1

    total = buys + sells
    if total == 0:
        return None, rsi, 0, atr

    if buys > sells:
        raw = buys / total
        if raw >= 0.80:
            conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)
            return 'BUY', rsi, conf, atr
    elif sells > buys:
        raw = sells / total
        if raw >= 0.80:
            conf = min(int(85 + (raw - 0.80) / 0.20 * 15), 100)
            return 'SELL', rsi, conf, atr

    return None, rsi, 0, atr

def build_message(prices, price, direction, rsi, conf, atr):
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    rsi_str = str(round(rsi, 1))
    rsi_comment = 'Oversold' if rsi < 35 else 'Overbought' if rsi > 65 else 'Neutral'
    filled = int((conf - 85) / 15 * 10) if conf >= 85 else 0
    bar = filled * 'green' 

    ema9 = calculate_ema(prices, 9)
    ema21 = calculate_ema(prices, 21)
    trend = 'Bullish' if ema9 > ema21 else 'Bearish'

    if direction == 'BUY':
        tp = round(price + (atr * 2.0), 2)
        sl = round(price - atr, 2)
        msg = '\U0001F7E2 *XAUUSD BUY SIGNAL* \U0001F4C8\n'
        msg += '\u2501' * 20 + '\n'
        msg += '\U0001F4B0 *Live Price:* `$' + '{:,.2f}'.format(price) + '`\n'
        msg += '\u23F0 `' + now + '`\n\n'
        msg += '\U0001F4CA *TRADE DETAILS*\n'
        msg += '\u251C \U0001F3AF Entry: `$' + '{:,.2f}'.format(price) + '`\n'
        msg += '\u251C \u2705 TP:    `$' + '{:,.2f}'.format(tp) + '`\n'
        msg += '\u2514 \u274C SL:    `$' + '{:,.2f}'.format(sl) + '`\n\n'
        msg += '\U0001F4C9 RSI: `' + rsi_str + '` ' + rsi_comment + '\n'
        msg += '\U0001F4AA Strength: `' + str(conf) + '%`\n'
        msg += '\u26A0\uFE0F _Trade at your own risk_\n'
        msg += '\u2501' * 20
        return msg
    elif direction == 'SELL':
        tp = round(price - (atr * 2.0), 2)
        sl = round(price + atr, 2)
        msg = '\U0001F534 *XAUUSD SELL SIGNAL* \U0001F4C9\n'
        msg += '\u2501' * 20 + '\n'
        msg += '\U0001F4B0 *Live Price:* `$' + '{:,.2f}'.format(price) + '`\n'
        msg += '\u23F0 `' + now + '`\n\n'
        msg += '\U0001F4CA *TRADE DETAILS*\n'
        msg += '\u251C \U0001F3AF Entry: `$' + '{:,.2f}'.format(price) + '`\n'
        msg += '\u251C \u2705 TP:    `$' + '{:,.2f}'.format(tp) + '`\n'
        msg += '\u2514 \u274C SL:    `$' + '{:,.2f}'.format(sl) + '`\n\n'
        msg += '\U0001F4C9 RSI: `' + rsi_str + '` ' + rsi_comment + '\n'
        msg += '\U0001F4AA Strength: `' + str(conf) + '%`\n'
        msg += '\u26A0\uFE0F _Trade at your own risk_\n'
        msg += '\u2501' * 20
        return msg
    else:
        msg = '\U0001F4E1 *XAUUSD LIVE UPDATE*\n'
        msg += '\u2501' * 20 + '\n'
        msg += '\U0001F4B0 Price: `$' + '{:,.2f}'.format(price) + '`\n'
        msg += '\u23F0 `' + now + '`\n'
        msg += '\U0001F4CA Trend: `' + trend + '`\n'
        msg += '\U0001F4C9 RSI: `' + rsi_str + '` ' + rsi_comment + '\n'
        msg += '_Waiting for 85%+ signal..._\n'
        msg += '\u2501' * 20
        return msg

def main():
    logger.info('Bot starting...')
    send_telegram('\U0001F916 *XAUUSD Signal Bot LIVE!*\n\n\u2705 Real-time gold prices\n\U0001F4AA Only 85-100% strength signals\n\U0001F4E1 Checking every 5 minutes\n\n_Loading data... first signal in 1 min_ \U0001F680')

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
                msg = build_message(price_history, live_price, direction, rsi, conf, atr)
                send_telegram(msg)
            else:
                logger.warning('Could not fetch live price')
        except Exception as e:
            logger.error('Main loop error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
