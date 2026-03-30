import os
import time
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
GOLD_API_KEY = os.environ.get('GOLD_API_KEY', '')

price_history = []

def send_telegram(message):
    url = 'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage'
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error('Telegram error: ' + str(e))
        return False

def get_price_yahoo():
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/GC=F'
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        price = float(data['chart']['result'][0]['meta']['regularMarketPrice'])
        logger.info('Price: ' + str(price))
        return price
    except Exception as e:
        logger.error('Yahoo failed: ' + str(e))
        return None

def get_price_gold_api():
    try:
        headers = {'x-access-token': GOLD_API_KEY, 'Content-Type': 'application/json'}
        r = requests.get('https://www.goldapi.io/api/XAU/USD', headers=headers, timeout=10)
        data = r.json()
        price = float(data['price'])
        return price
    except Exception as e:
        logger.error('Gold API failed: ' + str(e))
        return None

def get_live_price():
    price = get_price_yahoo()
    if price and price > 1000:
        return price
    price = get_price_gold_api()
    if price and price > 1000:
        return price
    return None

def load_history():
    global price_history
    try:
        import yfinance as yf
        ticker = yf.Ticker('GC=F')
        hist = ticker.history(period='5d', interval='5m')
        if not hist.empty:
            price_history = list(hist['Close'].dropna().values)[-100:]
            logger.info('Loaded ' + str(len(price_history)) + ' prices')
    except Exception as e:
        logger.warning('History load failed: ' + str(e))

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
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

def generate_signal(current_price):
    global price_history
    price_history.append(current_price)
    if len(price_history) > 200:
        price_history = price_history[-200:]

    if len(price_history) < 20:
        return None

    prices = price_history
    rsi = calculate_rsi(prices)
    ema9 = calculate_ema(prices, 9)
    ema21 = calculate_ema(prices, 21)
    ema50 = calculate_ema(prices, min(50, len(prices)))

    buy_score = 0
    sell_score = 0

    if rsi < 30:
        buy_score += 30
    elif rsi < 40:
        buy_score += 22
    elif rsi < 50:
        buy_score += 12
    if rsi > 70:
        sell_score += 30
    elif rsi > 60:
        sell_score += 22
    elif rsi > 50:
        sell_score += 12

    diff_pct = abs(ema9 - ema21) / ema21 * 100
    if ema9 > ema21:
        buy_score += min(25, 15 + int(diff_pct * 10))
    else:
        sell_score += min(25, 15 + int(diff_pct * 10))

    if current_price > ema50:
        buy_score += 20
    else:
        sell_score += 20

    if len(prices) >= 4:
        recent_change = prices[-1] - prices[-4]
        if recent_change > 0:
            buy_score += 15
        else:
            sell_score += 15

    if buy_score >= 60:
        strength = 85 + min(15, int((buy_score - 60) / 3))
        direction = 'BUY'
        entry = round(current_price, 2)
        tp1 = round(entry + 5.0, 2)
        tp2 = round(entry + 10.0, 2)
        tp3 = round(entry + 18.0, 2)
        sl = round(entry - 8.0, 2)
        return direction, strength, entry, tp1, tp2, tp3, sl
    elif sell_score >= 60:
        strength = 85 + min(15, int((sell_score - 60) / 3))
        direction = 'SELL'
        entry = round(current_price, 2)
        tp1 = round(entry - 5.0, 2)
        tp2 = round(entry - 10.0, 2)
        tp3 = round(entry - 18.0, 2)
        sl = round(entry + 8.0, 2)
        return direction, strength, entry, tp1, tp2, tp3, sl

    return None

def format_signal(direction, strength, entry, tp1, tp2, tp3, sl, price):
    bar_filled = int((strength - 85) / 1.5)
    bar = '🟩' * bar_filled + '⬜' * (10 - bar_filled)
    arrow = '📈' if direction == 'BUY' else '📉'
    emoji = '🟢' if direction == 'BUY' else '🔴'
    return (
        '<b>⚡ XAUUSD SIGNAL ALERT ⚡</b>\n\n'
        + emoji + ' <b>' + direction + '</b> ' + arrow + '\n'
        + '💰 <b>Live Price: $' + str(round(price, 2)) + '</b>\n\n'
        + '📊 <b>Signal Strength: ' + str(strength) + '%</b>\n'
        + bar + '\n\n'
        + '🎯 <b>Entry:</b> $' + str(entry) + '\n'
        + '✅ <b>TP1:</b> $' + str(tp1) + '\n'
        + '✅ <b>TP2:</b> $' + str(tp2) + '\n'
        + '✅ <b>TP3:</b> $' + str(tp3) + '\n'
        + '🛑 <b>Stop Loss:</b> $' + str(sl) + '\n\n'
        + '⏱ Next check in 5 minutes\n'
        + '#XAUUSD #Gold #Forex'
    )

def main():
    logger.info('Bot starting...')
    send_telegram(
        '🤖 <b>XAUUSD Signal Bot is LIVE!</b>\n\n'
        + '✅ Connected and fetching live prices\n'
        + '💪 Signals: 85-100% strength only\n'
        + '📡 Checking every 5 minutes\n\n'
        + '<i>Loading price history... first signal coming shortly!</i>'
    )

    load_history()
    no_signal_count = 0

    while True:
        try:
            price = get_live_price()
            if price is None:
                logger.error('No price available')
                time.sleep(60)
                continue

            logger.info('XAUUSD: $' + str(price))
            result = generate_signal(price)

            if result:
                direction, strength, entry, tp1, tp2, tp3, sl = result
                msg = format_signal(direction, strength, entry, tp1, tp2, tp3, sl, price)
                send_telegram(msg)
                logger.info('Signal sent: ' + direction + ' ' + str(strength) + '%')
                no_signal_count = 0
            else:
                no_signal_count += 1
                logger.info('No signal. Count: ' + str(no_signal_count))
                if no_signal_count >= 3:
                    send_telegram(
                        '📡 <b>XAUUSD Live Monitor</b>\n\n'
                        + '💰 Current Price: <b>$' + str(round(price, 2)) + '</b>\n'
                        + '🔍 Scanning for high-strength signal...\n'
                        + '✅ Bot active and watching!\n\n'
                        + '⏱ Next check in 5 minutes'
                    )
                    no_signal_count = 0

        except Exception as e:
            logger.error('Loop error: ' + str(e))

        time.sleep(300)

if __name__ == '__main__':
    main()
