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
from ta.utils import _ema
from ta.volatility import BollingerBands

from classes.ohlc import Ohlc
from classes.singleton import Singleton
from custom_types.controller_type import EMode
from custom_types.exchange_type import ICandlestick
from service.exchange import exchange
from service.logging import setup_logging, signal_bot_logger as logger
from service.telegram_bot import telegram_bot
from settings import MODE, INTERVAL
from utils.chart_utils import CANDLESTICK_INTERVAL_MAP
from utils.events import ee, ESignal, TelegramEventType, Trade
from utils.general_utils import time_now_in_ms

ZigzagIndicator = Optional[Literal['peak', 'trough']]
Divergence = Optional[Literal['bullish', 'bearish']]

CANDLESTICK_LIMIT = 499
BUFFER_TIMEOUT_IN_SEC = 1


class SignalBot(metaclass=Singleton):
    """Read chart data and indicate trade signals"""
    candlestick_list: List[Ohlc] = []
    last_peak: Ohlc = None
    last_trough: Ohlc = None
    divergence: Divergence = None
    point0_price = 0
    is_safe_last_peak = False
    is_safe_last_trough = False

    hit_opposite_rsi = False
    divergence_counter = 0

    def __init__(self, origin):
        logger.info(f'START SIGNAL_BOT4 from {origin} interval: {INTERVAL}')
        ee.on(TelegramEventType.STATS, self.stats_requested)

    async def run(self):
        logger.info("start stream candles")
        now_in_ms = time_now_in_ms()
        interval_in_ms = self.interval_in_ms()
        num_complete_candles = 250  # To calculate RSI
        start_time = now_in_ms - (now_in_ms % interval_in_ms) - (interval_in_ms * num_complete_candles)
        latest_complete_close_time_in_ms, latest_incomplete_close_time_in_ms \
            = await self.stream_candles(timestamp=start_time)
        while True:
            now_in_ms = time_now_in_ms()
            timeout_in_sec = ((latest_incomplete_close_time_in_ms - now_in_ms) // (10 ** 3)) + BUFFER_TIMEOUT_IN_SEC
            logger.info(f"timeout_in_sec: {timeout_in_sec}")
            latest_complete_close_time_in_ms, latest_incomplete_close_time_in_ms \
                = await self.stream_candles(latest_complete_close_time_in_ms, timeout_in_sec)

    def candle_incoming(self, candle: ICandlestick):
        """Process trade data by bigger row"""
        ohlc = Ohlc(unix=candle['openTime'], date=datetime.fromtimestamp(candle['openTime'] / 1000, tz=pytz.UTC),
                    open=float(candle['open']), high=float(candle['high']), low=float(candle['low']),
                    close=float(candle['close']))
        self.candlestick_list.append(ohlc)
        self.candlestick_list = self.candlestick_list[-300:]
        data_len = 250
        window = 14
        result = None
        if len(self.candlestick_list) >= window:
            prev_ohlc: Ohlc = self.candlestick_list[-2]
            ohlc.rsi = SignalBot.get_latest_rsi(self.candlestick_list, data_len, window=21)
            ohlc.ema20 = self.get_latest_ema(self.candlestick_list, data_len, window=20)
            ohlc.ema = self.get_latest_ema(self.candlestick_list, data_len, window=60)
            bb_result = SignalBot.get_bollinger_band(self.candlestick_list, data_len=28)
            ohlc.mavg, ohlc.hband, ohlc.lband = itemgetter('mavg', 'hband', 'lband')(bb_result)

            ee.emit(Trade.COMPLETE_CANDLESTICK_EVENT, ohlc)

            if MODE == EMode.PRODUCTION:
                logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} candlestick: {ohlc.close} RSI: {ohlc.rsi:.4f} "
                            f"EMA 20: {ohlc.ema:.5f}")

            self.candlestick_list[-1] = ohlc
            if len(self.candlestick_list) >= data_len:
                zigzag_indicator = SignalBot.check_zigzag_pattern(self.candlestick_list[-3:])
                valid_rsi_target = SignalBot.check_rsi_target(zigzag_indicator, prev_ohlc)
                self.invalidate_expired_peaktrough(prev_ohlc)
                self.check_divergence(zigzag_indicator, prev_ohlc, self.last_peak, self.last_trough, valid_rsi_target)
                # self.check_is_hit_opposite_rsi(ohlc)
                # self.check_is_safe_divergence(ohlc)
                self.adjust_p0(ohlc)
                result = self.safety_check(ohlc)
                # After ending only save the current peak/trough and last peak/trough
                if valid_rsi_target:
                    if zigzag_indicator == 'peak':
                        self.last_peak = prev_ohlc
                    elif zigzag_indicator == 'trough':
                        self.last_trough = prev_ohlc
        return result

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

    @classmethod
    def get_latest_rsi(cls, data: List[Ohlc], data_len, window) -> int:
        """Calculate RSI from a pandas Series and return the latest RSI"""
        close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
        rsi_list = RSIIndicator(close=close_price_list, window=window).rsi()
        return rsi_list.iloc[-1]

    @classmethod
    def get_bollinger_band(cls, data: List[Ohlc], data_len, window=20):
        """Calculate RSI from a pandas Series and return the latest RSI"""
        close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
        indicator_bb = BollingerBands(close=close_price_list, window=window, window_dev=2)

        # Add Bollinger Bands features
        mavg_list = indicator_bb.bollinger_mavg()
        hband_list = indicator_bb.bollinger_hband()
        lband_list = indicator_bb.bollinger_lband()
        bb_result = {'mavg': mavg_list.iloc[-1], 'hband': hband_list.iloc[-1], 'lband': lband_list.iloc[-1]}
        return bb_result

    def get_latest_ema(self, data: List[Ohlc], data_len, window=50):
        """Calculate DEMA from a pandas Series and return the latest EMA"""
        close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
        ema_list = EMAIndicator(close=close_price_list, window=window).ema_indicator()
        return ema_list.iloc[-1]

    @classmethod
    def check_zigzag_pattern(cls, data: List[Ohlc]) -> ZigzagIndicator:
        """Find peak/trough from a chart data"""
        assert len(data) >= 3

        # Check if peak/trough with last 3 item
        peaks, _ = find_peaks([obj.rsi for obj in data[-3:]])
        if len(peaks) > 0:
            return 'peak'
        troughs, _ = find_peaks(-pd.Series([obj.rsi for obj in data[-3:]]))
        if len(troughs) > 0:
            return 'trough'
        return None

    @classmethod
    def check_rsi_target(cls, zigzag_indicator: ZigzagIndicator, prev_ohlc: Ohlc):
        """Check if RSI target has been hit"""
        valid_rsi_target = False
        if zigzag_indicator == 'peak' and prev_ohlc.rsi >= 70:
            valid_rsi_target = True
        if zigzag_indicator == 'trough' and prev_ohlc.rsi <= 30:
            valid_rsi_target = True
        return valid_rsi_target

    def invalidate_expired_peaktrough(self, prev_ohlc: Ohlc):
        """ Invalidate peak and trough after last peak trough is more than 1 hours """
        if self.last_peak is not None and prev_ohlc.date - timedelta(minutes=12) > self.last_peak.date:
            self.last_peak = None
            self.is_safe_last_peak = False
        if self.last_trough is not None and prev_ohlc.date - timedelta(minutes=12) > self.last_trough.date:
            self.last_trough = None
            self.is_safe_last_trough = False

    def check_divergence(self, zigzag_indicator: ZigzagIndicator, prev_ohlc: Ohlc, last_peak: Ohlc, last_trough: Ohlc,
                         valid_rsi_target: bool):
        """Check if there is a bullish or bearish divergence"""
        divergence, rsi1_ohlc, rsi2_ohlc, point0_price = None, None, None, None
        if zigzag_indicator == 'peak' and last_peak and valid_rsi_target and prev_ohlc.rsi < last_peak.rsi \
                and prev_ohlc.high >= last_peak.high:
            rsi1_ohlc = last_peak
            rsi2_ohlc = prev_ohlc
            self.point0_price = prev_ohlc.high
            divergence = 'bearish'
            self.hit_opposite_rsi = False
        elif zigzag_indicator == 'trough' and last_trough and valid_rsi_target and prev_ohlc.rsi > last_trough.rsi \
                and prev_ohlc.low <= last_trough.low:
            rsi1_ohlc = last_trough
            rsi2_ohlc = prev_ohlc
            self.point0_price = prev_ohlc.low
            divergence = 'bullish'
            self.hit_opposite_rsi = False

        if divergence is not None:
            self.divergence_counter += 1
            self.divergence = divergence
            msg = (f"{rsi2_ohlc.date}\n"
                   f"{divergence} divergence\n"
                   f"TARGET 1️⃣: {rsi1_ohlc.rsi:.2f} [{rsi1_ohlc.close:.4f} USD] ({rsi1_ohlc.date:%H:%M})\n"
                   f"TARGET 2️⃣: {rsi2_ohlc.rsi:.2f} [{self.point0_price:.4f} USD]\n"
                   f"Divergence count: {self.divergence_counter}")
            logger.info(msg)
            telegram_bot.send_message(message=msg)
            # divergence_result = {'divergence': self.divergence, 'rsi2': prev_ohlc, 'price': self.point0_price}
            # if MODE == EMode.PRODUCTION:
            #     ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            # return divergence_result

    def check_is_safe_divergence(self, ohlc: Ohlc):
        if self.last_peak is not None and ohlc.rsi < 70:
            self.is_safe_last_peak = True
        if self.last_trough is not None and ohlc.rsi > 30:
            self.is_safe_last_trough = True

    def check_is_hit_opposite_rsi(self, ohlc: Ohlc):
        if self.divergence == "bearish" and ohlc.rsi < 30:
            logger.info("hit opposite, cancel divergence")
            self.reset_all()
        elif self.divergence == "bullish" and ohlc.rsi > 70:
            logger.info("hit opposite, cancel divergence")
            self.reset_all()

    def safety_check(self, ohlc: Ohlc) -> Union[Divergence, Any]:
        """Check if RSI ever goes against the target (30 for bull, 70 for bear)"""
        divergence_result = {'divergence': self.divergence, 'rsi2': ohlc, 'price': self.point0_price}
        if self.divergence == "bearish" and ohlc.close < ohlc.ema:
            if MODE == EMode.PRODUCTION:
                ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            logger.info(
                f"{ohlc.date:%Y-%m-%d %H:%M:%S} Price crossed EMA, close: {ohlc.close:.4f} < ema21 {ohlc.ema:.4f}")
            self.reset_all()
            return divergence_result
        if self.divergence == "bullish" and ohlc.close > ohlc.ema:
            if MODE == EMode.PRODUCTION:
                ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            logger.info(
                f"{ohlc.date:%Y-%m-%d %H:%M:%S} Price crossed EMA, close: {ohlc.close:.4f} > ema21 {ohlc.ema:.4f}")
            self.reset_all()
            return divergence_result

    def adjust_p0(self, ohlc: Ohlc):
        if self.divergence == "bearish" and ohlc.high > self.point0_price:
            self.point0_price = ohlc.high
            logger.info(f"NEW STOP LOSS {self.point0_price:.4f}")
        elif self.divergence == "bullish" and ohlc.rsi > 70:
            self.point0_price = ohlc.high
            logger.info(f"NEW STOP LOSS {self.point0_price:.4f}")

    def reset_all(self):
        self.point0_price = 0
        self.divergence = None
        self.is_safe_last_peak = False
        self.is_safe_last_trough = False

    async def stream_candles(self, timestamp, timeout_in_sec=0):
        await asyncio.sleep(timeout_in_sec)
        retry_limit = 3
        while True:
            candlesticks = exchange.get_candlestick(interval=INTERVAL, start_time=timestamp, limit=CANDLESTICK_LIMIT)
            if len(candlesticks) < 2:
                retry_limit -= 1
            if retry_limit <= 0 or len(candlesticks) >= 2:
                break
            await asyncio.sleep(5)

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
