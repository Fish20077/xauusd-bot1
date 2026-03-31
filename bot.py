import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

def send_telegram(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f'Telegram error: {e}')

def get_usdjpy_price():
    try:
        ticker = yf.Ticker('JPY=X')
        data = ticker.history(period='1d', interval='1m')
        if not data.empty:
            price = float(data['Close'].iloc[-1])
            return round(price, 3)
    except Exception as e:
        print(f'Price error: {e}')
    return None

def load_history():
    try:
        ticker = yf.Ticker('JPY=X')
        data = ticker.history(period='5d', interval='5m')
        if not data.empty:
            print(f'Loaded {len(data)} candles of USDJPY history')
            return data
    except Exception as e:
        print(f'History error: {e}')
    return pd.DataFrame()

def calculate_indicators(df):
    close = df['Close']
    high = df['High']
    low = df['Low']

    df['ema9'] = close.ewm(span=9).mean()
    df['ema21'] = close.ewm(span=21).mean()
    df['ema50'] = close.ewm(span=50).mean()
    df['ema200'] = close.ewm(span=200).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['signal_line'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['signal_line']

    df['swing_high'] = high.rolling(20).max()
    df['swing_low'] = low.rolling(20).min()

    return df

def generate_signal(df):
    if len(df) < 200:
        return None

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    price = latest['Close']
    ema9 = latest['ema9']
    ema21 = latest['ema21']
    ema50 = latest['ema50']
    ema200 = latest['ema200']
    rsi = latest['rsi']
    macd = latest['macd']
    macd_sig = latest['signal_line']
    macd_hist = latest['macd_hist']
    prev_macd_hist = prev['macd_hist']
    swing_high = latest['swing_high']
    swing_low = latest['swing_low']

    buy_score = 0
    if price > ema200: buy_score += 20
    if ema9 > ema21 > ema50: buy_score += 20
    if macd > macd_sig and macd_hist > prev_macd_hist: buy_score += 20
    if 45 < rsi < 70: buy_score += 20
    if price > ema9 and price > ema21: buy_score += 20

    sell_score = 0
    if price < ema200: sell_score += 20
    if ema9 < ema21 < ema50: sell_score += 20
    if macd < macd_sig and macd_hist < prev_macd_hist: sell_score += 20
    if 30 < rsi < 55: sell_score += 20
    if price < ema9 and price < ema21: sell_score += 20

    pip = 0.01
    tp_pips = 30
    sl_pips = 15

    if buy_score >= sell_score:
        direction = 'BUY STOP'
        entry = round(swing_high + (2 * pip), 3)
        tp = round(entry + (tp_pips * pip), 3)
        sl = round(entry - (sl_pips * pip), 3)
        strength = buy_score
        emoji = '🟢'
    else:
        direction = 'SELL STOP'
        entry = round(swing_low - (2 * pip), 3)
        tp = round(entry - (tp_pips * pip), 3)
        sl = round(entry + (sl_pips * pip), 3)
        strength = sell_score
        emoji = '🔴'

    strength_bar = '█' * (strength // 20) + '░' * (5 - strength // 20)
    now = datetime.now()

    msg = (
        f'{emoji} <b>USDJPY {direction}</b>\n'
        f'━━━━━━━━━━━━━━━━\n'
        f'📍 Entry: <b>{entry:.3f}</b>\n'
        f'✅ TP:    <b>{tp:.3f}</b>\n'
        f'❌ SL:    <b>{sl:.3f}</b>\n'
        f'💪 Strength: {strength}% {strength_bar}\n'
        f'⏰ {now.strftime("%H:%M")}'
    )

    return msg

def main():
    print('USDJPY Signal Bot starting...')
    send_telegram('🤖 <b>USDJPY Bot LIVE</b> — signals every 5 mins 🚀')

    df = load_history()

    while True:
        try:
            price = get_usdjpy_price()
            if price and not df.empty:
                now = datetime.now()
                new_row = pd.DataFrame([{
                    'Open': price, 'High': price, 'Low': price,
                    'Close': price, 'Volume': 0
                }], index=[now])
                df = pd.concat([df, new_row]).tail(500)
                df = calculate_indicators(df)
                signal = generate_signal(df)
                if signal:
                    send_telegram(signal)
                    print(f'Signal sent at {now}')
            elif df.empty:
                df = load_history()
        except Exception as e:
            print(f'Loop error: {e}')

        time.sleep(300)

if __name__ == '__main__':
    main()
