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

    # EMAs
    df['ema9'] = close.ewm(span=9).mean()
    df['ema21'] = close.ewm(span=21).mean()
    df['ema50'] = close.ewm(span=50).mean()
    df['ema200'] = close.ewm(span=200).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['signal_line'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['signal_line']

    # Swing highs/lows (last 20 candles)
    df['swing_high'] = high.rolling(20).max()
    df['swing_low'] = low.rolling(20).min()

    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

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
    atr = latest['atr']

    # --- BUY STOP scoring ---
    buy_score = 0
    buy_reasons = []

    if price > ema200:
        buy_score += 20
        buy_reasons.append('Above EMA200 (uptrend)')
    if ema9 > ema21 > ema50:
        buy_score += 20
        buy_reasons.append('EMA9>21>50 aligned bullish')
    if macd > macd_sig and macd_hist > prev_macd_hist:
        buy_score += 20
        buy_reasons.append('MACD bullish crossover')
    if 45 < rsi < 70:
        buy_score += 20
        buy_reasons.append('RSI in bullish zone')
    if price > ema9 and price > ema21:
        buy_score += 20
        buy_reasons.append('Price above key EMAs')

    # --- SELL STOP scoring ---
    sell_score = 0
    sell_reasons = []

    if price < ema200:
        sell_score += 20
        sell_reasons.append('Below EMA200 (downtrend)')
    if ema9 < ema21 < ema50:
        sell_score += 20
        sell_reasons.append('EMA9<21<50 aligned bearish')
    if macd < macd_sig and macd_hist < prev_macd_hist:
        sell_score += 20
        sell_reasons.append('MACD bearish crossover')
    if 30 < rsi < 55:
        sell_score += 20
        sell_reasons.append('RSI in bearish zone')
    if price < ema9 and price < ema21:
        sell_score += 20
        sell_reasons.append('Price below key EMAs')

    # Pip size for JPY pairs = 0.01
    pip = 0.01
    tp_pips = 30
    sl_pips = 15
    rr = tp_pips / sl_pips

    if buy_score >= sell_score:
        direction = 'BUY STOP'
        entry = round(swing_high + (2 * pip), 3)
        tp = round(entry + (tp_pips * pip), 3)
        sl = round(entry - (sl_pips * pip), 3)
        strength = buy_score
        reasons = buy_reasons
        emoji = '🟢'
        arrow = '📈'
    else:
        direction = 'SELL STOP'
        entry = round(swing_low - (2 * pip), 3)
        tp = round(entry - (tp_pips * pip), 3)
        sl = round(entry + (sl_pips * pip), 3)
        strength = sell_score
        reasons = sell_reasons
        emoji = '🔴'
        arrow = '📉'

    label = 'STRONG 🔥' if strength >= 80 else ('MODERATE ⚡' if strength >= 60 else 'WEAK 🟡')

    reasons_text = '\n'.join([f'  ✅ {r}' for r in reasons]) if reasons else '  ⚠️ Mixed signals'

    msg = (
        f'{emoji} <b>USDJPY {direction}</b> {arrow}\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'💰 <b>Current Price:</b> {price:.3f}\n'
        f'🎯 <b>Pending Entry:</b> {entry:.3f}\n'
        f'✅ <b>Take Profit:</b>   {tp:.3f} (+{tp_pips} pips)\n'
        f'❌ <b>Stop Loss:</b>     {sl:.3f} (-{sl_pips} pips)\n'
        f'⚖️ <b>Risk/Reward:</b>   1:{rr:.1f}\n'
        f'📊 <b>RSI:</b> {rsi:.1f} | <b>MACD:</b> {"Bullish" if macd > macd_sig else "Bearish"}\n'
        f'💪 <b>Strength:</b> {strength}% — {label}\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'📋 <b>Why this signal:</b>\n{reasons_text}\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'📌 <b>Lot size:</b> 0.01 (safe for $10 account)\n'
        f'⚠️ <b>Demo test recommended first!</b>\n'
        f'⏰ {datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC'
    )

    return msg

def main():
    print('USDJPY Signal Bot starting...')
    send_telegram(
        '🤖 <b>USDJPY Signal Bot LIVE!</b>\n\n'
        '✅ Real-time USDJPY prices\n'
        '🎯 BUY STOP / SELL STOP signals\n'
        '📊 EMA + RSI + MACD strategy\n'
        '💰 Optimised for 0.01 lot / $10 account\n'
        '⏱ Signals every 5 minutes\n\n'
        '⚠️ <b>Always test on demo first!</b>\n'
        'Loading market data... first signal in ~1 min 🚀'
    )

    df = load_history()

    while True:
        try:
            price = get_usdjpy_price()
            if price and not df.empty:
                now = datetime.utcnow()
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
