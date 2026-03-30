import os
import time
import logging
import requests
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
GOLD_API_KEY = os.environ.get('GOLD_API_KEY', '')

price_history = []

def send_telegram(message):
    url = 'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        logger.info('Telegram response: ' + str(r.status_code))
        return r.status_code == 200
    except Exception as e:
        logger.error('Telegram error: ' + str(e))
        return False

def get_price_gold_api():
    try:
        headers = {
            'x-access-token': GOLD_API_KEY,
            'Content-Type': 'application/json'
        }
        r = requests.get('https://www.goldapi.io/api/XAU/USD', headers=headers, timeout=10)
        data = r.json()
        price = float(data['price'])
        logger.info('Gold API price: ' + str(price))
        return price
    except Exception as e:
        logger.error('Gold API failed: ' + str(e))
        return None

def get_price_yahoo():
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/GC=F'
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = float(data['chart']['result'][0]['meta']['regularMarketPrice'])
        logger.info('Yahoo price: ' + str(price))
        return price
    except Exception as e:
        logger.error('Yahoo failed: ' + str(e))
        return None

def get_price_metals_live():
    try:
        r = requests.get('https://metals-api.com/api/latest?access_key=free&base=USD&symbols=XAU', timeout=10)
        data = r.json()
        price = float(1.0 / data['rates']['XAU'])
        logger.info('Metals-live price: ' + str(price))
        return price
    except Exception as e:
        logger.error('Metals-live failed: ' + str(e))
        return None

def get_live_price():
    price = get_price_gold_api()
    if price and price > 1000:
        return price
    logger.warning('Gold API failed, trying Yahoo...')
    price = get_price_yahoo()
    if price and price > 1000:
        return price
    logger.warning('Yahoo failed, trying backup...')
    price = get_price_metals_live()
    if price and price > 1000:
        return price
    logger.error('All price sources failed')
    return None

def load_history():
    global price_history
    try:
        import yfinance as yf
        ticker = yf.Ticker('GC=F')
        hist = ticker.history(period='5d', interval='5m')
        if not hist.empty:
            price_history = list(hist['Close'].dropna().values)[-100:]
            logger.info('Loaded ' + str(len(price_history)) + ' historical prices')
    except Exception as e:
        logger.warning('Could not load history: ' + str(e))

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains = []
    losses = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema

def calculate_macd(prices):
    if len(prices) < 26:
        return 0, 0
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    macd_line = ema12 - ema26
    signal = macd_line
    return macd_line, signal

def generate_signal(current_price):
    global price_history
    price_history.append(current_price)
    if len(price_history) > 200:
        price_history = price_history[-200:]

    if len(price_history) < 30:
        return None

    prices = price_history

    rsi = calculate_rsi(prices)
    ema9 = calculate_ema(prices, 9)
    ema21 = calculate_ema(prices, 21)
    ema50 = calculate_ema(prices, 50) if len(prices) >= 50 else current_price
    macd, signal = calculate_macd(prices)

    buy_score = 0
    sell_score = 0

    if rsi < 35:
        buy_score += 25
    elif rsi < 45:
        buy_score += 15
    if rsi > 65:
        sell_score += 25
    elif rsi > 55:
        sell_score += 15

    if ema9 > ema21:
        buy_score += 20
    else:
        sell_score += 20

    if current_price > ema50:
        buy_score += 20
    else:
        sell_score += 20

    if macd > signal:
        buy_score += 20
    else:
        sell_score += 20

    recent = prices[-5:]
    if len(recent) >= 3:
        if recent[-1] > recent[-3]:
            buy_score += 15
        else:
            sell_score += 15

    if buy_score >= 85:
        direction = 'BUY'
        strength = min(buy_score, 100)
        entry = current_price
        tp1 = round(entry + 5.0, 2)
        tp2 = round(entry + 10.0, 2)
        tp3 = round(entry + 18.0, 2)
        sl = round(entry - 8.0, 2)
        return direction, strength, entry, tp1, tp2, tp3, sl
    elif sell_score >= 85:
        direction = 'SELL'
        strength = min(sell_score, 100)
        entry = current_price
        tp1 = round(entry - 5.0, 2)
        tp2 = round(entry - 10.0, 2)
        tp3 = round(entry - 18.0, 2)
        sl = round(entry + 8.0, 2)
        return direction, strength, entry, tp1, tp2, tp3, sl

    return None

def format_signal(direction, strength, entry, tp1, tp2, tp3, sl, price):
    bar_filled = int(strength / 10)
    bar = '🟩' * bar_filled + '⬜' * (10 - bar_filled)
    arrow = '📈' if direction == 'BUY' else '📉'
    emoji = '🟢' if direction == 'BUY' else '🔴'

    msg = (
        '<b>⚡ XAUUSD SIGNAL ALERT ⚡</b>\n\n'
        + emoji + ' <b>Direction: ' + direction + '</b> ' + arrow + '\n'
        + '💰 <b>Live Price: $' + str(round(price, 2)) + '</b>\n\n'
        + '📊 <b>Signal Strength: ' + str(strength) + '%</b>\n'
        + bar + '\n\n'
        + '🎯 <b>Entry:</b> $' + str(entry) + '\n'
        + '✅ <b>TP1:</b> $' + str(tp1) + '\n'
        + '✅ <b>TP2:</b> $' + str(tp2) + '\n'
        + '✅ <b>TP3:</b> $' + str(tp3) + '\n'
        + '🛑 <b>Stop Loss:</b> $' + str(sl) + '\n\n'
        + '⏱ Next signal in 5 minutes\n'
        + '#XAUUSD #Gold #Forex'
    )
    return msg

def main():
    logger.info('Bot starting...')

    test = send_telegram('🤖 <b>XAUUSD Signal Bot is LIVE!</b>\n\n✅ Real-time gold prices active\n💪 Only 85-100% strength signals\n📡 Checking every 5 minutes\n\n<i>First signal coming shortly...</i>')
    logger.info('Startup message sent: ' + str(test))

    load_history()

    no_signal_count = 0

    while True:
        try:
            price = get_live_price()

            if price is None:
                logger.error('Could not get price from any source')
                time.sleep(60)
                continue

            logger.info('Current XAUUSD price: $' + str(price))

            result = generate_signal(price)

            if result:
                direction, strength, entry, tp1, tp2, tp3, sl = result
                msg = format_signal(direction, strength, entry, tp1, tp2, tp3, sl, price)
                send_telegram(msg)
                logger.info('Signal sent: ' + direction + ' ' + str(strength) + '%')
                no_signal_count = 0
            else:
                no_signal_count += 1
                logger.info('No strong signal yet. Price: $' + str(price))
                if no_signal_count >= 6:
                    send_telegram(
                        '📡 <b>XAUUSD Monitor</b>\n\n'
                        + '💰 Live Price: $' + str(round(price, 2)) + '\n'
                        + '🔍 Scanning for 85-100% signal...\n'
                        + '⏳ Market conditions not ideal yet\n'
                        + '✅ Bot is active and watching!'
                    )
                    no_signal_count = 0

        except Exception as e:
            logger.error('Main loop error: ' + str(e))

        logger.info('Sleeping 5 minutes...')
        time.sleep(300)

if __name__ == '__main__':
    main()
