"""Signal bot class"""
import asyncio
from datetime import datetime, timedelta
from operator import itemgetter
from typing import Literal, Optional, List, Any, Union

import pandas as pd
import pytz
from scipy.signal import find_peaks
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

from classes.ohlc import Ohlc
from classes.singleton import Singleton
from custom_types.controller_type import EMode
from custom_types.exchange_type import ICandlestick, ICandlestickEvent
from service.exchange import exchange
from service.logging import setup_logging, signal_bot_logger as logger
from service.telegram_bot import telegram_bot
from settings import MODE, INTERVAL
from utils.chart_utils import CANDLESTICK_INTERVAL_MAP
from utils.events import ee, ESignal, TelegramEventType, Trade, EExchange
from utils.general_utils import time_now_in_ms
from utils.indicator_utils import get_bollinger_band, get_avg_true_range, get_vwap, get_latest_rsi, get_latest_ema

ZigzagIndicator = Optional[Literal['peak', 'trough']]
Divergence = Optional[Literal['bullish', 'bearish']]

CANDLESTICK_LIMIT = 499
BUFFER_TIMEOUT_IN_SEC = 1


class SignalBot(metaclass=Singleton):
    """Read chart data and indicate trade signals"""
    candlestick_list: List[Ohlc] = []
    candlestick_htf_list: List[Ohlc] = []  # Higher time frame candles
    last_peak: Ohlc = None
    last_trough: Ohlc = None
    divergence: Divergence = None
    point0_price = 0
    is_safe_last_peak = False
    is_safe_last_trough = False

    hit_opposite_rsi = False
    divergence_counter = 0

    last_start_date = None
    last_candlestick = None

    def __init__(self, origin):
        logger.info(f'START SIGNAL_BOT5 from {origin} interval: {INTERVAL}')
        ee.on(TelegramEventType.STATS, self.stats_requested)
        ee.on(EExchange.CANDLESTICK_EVENT, self.on_candlestick_event)
        self.run()

    def on_candlestick_event(self, i_candlestick_event: ICandlestickEvent):

        candlestick = i_candlestick_event['data']
        start_time = datetime.fromtimestamp(candlestick['startTime'] / 1000, tz=pytz.UTC)
        if self.last_candlestick is None:
            self.last_start_date = start_time
            self.last_candlestick = candlestick
            logger.info(f"{self.last_start_date:%Y-%m-%d %H:%M:%S}: {self.last_candlestick['close']} "
                        f"(incomplete first streamed)")

        if self.last_start_date != start_time and self.last_candlestick is not None:
            # logger.info(f"{self.last_start_date:%Y-%m-%d %H:%M:%S}: {self.last_candlestick['close']}")
            ohlc = Ohlc(unix=self.last_candlestick['startTime'],
                        date=datetime.fromtimestamp(self.last_candlestick['startTime'] / 1000, tz=pytz.UTC),
                        open=float(self.last_candlestick['open']),
                        high=float(self.last_candlestick['high']),
                        low=float(self.last_candlestick['low']),
                        close=float(self.last_candlestick['close']),
                        volume_usdt=float(self.last_candlestick['volume']),
                        quoteAssetVolume=float(self.last_candlestick['quoteAssetVolume']))
            self.candle_incoming(candle=None, ohlc=ohlc)

        self.last_start_date = start_time
        self.last_candlestick = candlestick

    def run(self):
        now_in_ms = time_now_in_ms()
        interval_in_ms = self.interval_in_ms()
        num_complete_candles = 251  # To calculate RSI
        logger.info(F"PRE-FEED CANDLESTICKS: {num_complete_candles}")
        start_time = now_in_ms - (now_in_ms % interval_in_ms) - (interval_in_ms * num_complete_candles)
        self.stream_candles(timestamp=start_time)

    def candle_incoming(self, candle: Optional[ICandlestick], ohlc: Ohlc = None):
        """Process trade data by bigger row"""
        if ohlc is None:
            ohlc = Ohlc(unix=candle['openTime'],
                        date=datetime.fromtimestamp(candle['openTime'] / 1000, tz=pytz.UTC),
                        open=float(candle['open']), high=float(candle['high']), low=float(candle['low']),
                        close=float(candle['close']),
                        volume_usdt=float(candle['volume']),
                        quoteAssetVolume=float(candle['quoteAssetVolume']))

        self.candlestick_list.append(ohlc)
        self.candlestick_list = self.candlestick_list[-700:]
        data_len = 350
        window = 14
        result = None
        if len(self.candlestick_list) < window:
            return result

        prev_ohlc: Ohlc = self.candlestick_list[-2]
        ohlc.rsi = get_latest_rsi(self.candlestick_list, data_len, window=14)
        ohlc.ema_fast = get_latest_ema(self.candlestick_list, data_len, window=10)
        ohlc.ema_slow = get_latest_ema(self.candlestick_list, data_len, window=20)
        ee.emit(Trade.COMPLETE_CANDLESTICK_EVENT, ohlc)

        if MODE == EMode.PRODUCTION:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} candlestick: {ohlc.close:.04f} RSI: {ohlc.rsi:.04f} "
                        f"EMA: {ohlc.ema_slow:.05f}")
        # logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} candlestick: {ohlc.close} RSI: {ohlc.rsi:.4f} "
        #             f"EMA 60: {ohlc.ema:.5f} ema9 {ohlc.ema9:.5f}")

        self.candlestick_list[-1] = ohlc
        if len(self.candlestick_list) < data_len:
            return result

        self.check_rsi_oversold_overbought(ohlc)
        result = self.check_divergence(ohlc)
        self.adjust_p0(ohlc)
        return result

    def check_rsi_oversold_overbought(self, ohlc: Ohlc):
        # if ohlc.rsi >= 70 and self.divergence is None and self.divergence != 'bearish':
        #     self.divergence = 'bearish'
        #     logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} {self.divergence} formed")
        # elif ohlc.rsi <= 30 and self.divergence is None and self.divergence != 'bullish':
        #     self.divergence = 'bullish'
        #     logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} {self.divergence} formed")

        if ohlc.rsi >= 70 and self.divergence != 'bearish':
            self.divergence = 'bearish'
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} {self.divergence} formed")
        elif ohlc.rsi <= 30 and self.divergence != 'bullish':
            self.divergence = 'bullish'
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} {self.divergence} formed")

    def check_divergence(self, ohlc: Ohlc):
        divergence_result = {'divergence': self.divergence, 'rsi2': ohlc, 'price': self.point0_price}

        if self.divergence == "bearish" and ohlc.ema_fast < ohlc.ema_slow:
            if MODE == EMode.PRODUCTION:
                ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} "
                        f"EMA fast crossed, fast: {ohlc.ema_fast:.05f} < slow {ohlc.ema_slow:.05f} {self.divergence}")
            self.reset_all()
            return divergence_result
        elif self.divergence == "bullish" and ohlc.ema_fast > ohlc.ema_slow:
            if MODE == EMode.PRODUCTION:
                ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} "
                        f"EMA fast crossed, fast: {ohlc.ema_fast:.05f} > slow {ohlc.ema_slow:.05f} {self.divergence}")
            self.reset_all()
            return divergence_result

    def adjust_p0(self, ohlc: Ohlc):
        if self.divergence == "bearish" and ohlc.high > self.point0_price:
            self.point0_price = ohlc.high
        elif self.divergence == "bullish" and ohlc.low < self.point0_price:
            self.point0_price = ohlc.low

    def reset_all(self):
        self.divergence = None
        self.point0_price = 0

    def stream_candles(self, timestamp, timeout_in_sec=0):
        retry_limit = 3
        while True:
            candlesticks = exchange.get_candlestick(interval=INTERVAL, start_time=timestamp, limit=CANDLESTICK_LIMIT)
            if len(candlesticks) < 2:
                retry_limit -= 1
            if retry_limit <= 0 or len(candlesticks) >= 2:
                break
            asyncio.sleep(5)

        chart_data: List[Ohlc] = []
        if len(self.candlestick_list) <= 0:
            for candle in candlesticks[:-2]:
                ohlc = Ohlc(unix=candle['openTime'],
                            date=datetime.fromtimestamp(candle['openTime'] / 1000, tz=pytz.UTC),
                            open=float(candle['open']), high=float(candle['high']), low=float(candle['low']),
                            close=float(candle['close']))
                chart_data.append(ohlc)
            self.candlestick_list = chart_data
            logger.info(f"chart data length: {len(self.candlestick_list)}")

        latest_incomplete_close_time_in_ms = candlesticks[-1]['closeTime']
        latest_complete_close_time_in_ms = candlesticks[-2]['closeTime']

        # Current time is always between the opening and closing time of the latest candlestick. Latest incomplete
        # candlestick's closing time will always be in the future, so 2nd last candlestick in the list will be
        # the complete candlestick
        if self.get_latest_complete_candlestick_start_time() == candlesticks[-2]['openTime']:
            # Caught up to the latest candlestick, listen to real-time data
            self.candle_incoming(candlesticks[-2])
            return latest_complete_close_time_in_ms, latest_incomplete_close_time_in_ms

    def get_latest_incomplete_candlestick_start_time(self):
        return self.get_candlestick_start_time(time_now_in_ms())

    def get_candlestick_start_time(self, timestamp_in_ms):
        return timestamp_in_ms - (timestamp_in_ms % self.interval_in_ms())

    def interval_in_ms(self):
        return CANDLESTICK_INTERVAL_MAP[INTERVAL] * (10 ** 3)

    def get_latest_complete_candlestick_start_time(self):
        return self.get_latest_incomplete_candlestick_start_time() - self.interval_in_ms()

    def stats_requested(self, chat_id):
        msg = (f"📊 STATS REQUESTED\n"
               f"==========================\n"
               f"{'interval':<12}: {INTERVAL} \n"
               f"{'ohlc date':<12}: {self.candlestick_list[-1].date:%Y-%m-%d %H:%M}\n"
               f"{'ohlc close':<12}: {self.candlestick_list[-1].close:.5f} USD\n"
               f"{'ohlc rsi':<12}: {self.candlestick_list[-1].rsi:.4f} \n"
               f"{'peak rsi':<12}: {(self.last_peak.rsi if self.last_peak else 0):.4f}\n"
               f"{'peak date':<12}: {(self.last_peak.date if self.last_peak else datetime.now()):%Y-%m-%d %H:%M}\n"
               f"{'trough rsi':<12}: {(self.last_trough.rsi if self.last_trough else 0):.4f}\n"
               f"{'trough date':<12}: {(self.last_trough.date if self.last_trough else datetime.now()):%Y-%m-%d %H:%M}\n"
               f"==========================\n")
        telegram_bot.send_message(chat_id=chat_id, message=msg)

    def __del__(self):
        logger.info("signal_bot deleted")


async def main():
    print("start signal_bot.py")
    setup_logging()
    signal_bot = SignalBot(origin="signal_bot")
    await signal_bot.run()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(main())
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
