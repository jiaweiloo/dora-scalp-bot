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
from service.wallet import Wallet
from settings import MODE, INTERVAL
from utils.chart_utils import CANDLESTICK_INTERVAL_MAP
from utils.events import ee, ESignal, TelegramEventType, Trade
from utils.general_utils import time_now_in_ms

ZigzagIndicator = Optional[Literal['peak', 'trough']]
Divergence = Optional[Literal['bullish', 'bearish']]

CANDLESTICK_LIMIT = 499
BUFFER_TIMEOUT_IN_SEC = 1

# If price within 0.0001 different will not consider green/red candle
CANDLE_BUFFER = 0.0002

class SignalBot(metaclass=Singleton):
    """Read chart data and indicate trade signals"""
    candlestick_list: List[Ohlc] = []
    divergence: Divergence = None
    point0_price = 0

    tema_dema_crossed_counter = 0
    temadema_slopped = False
    rsi_retest_complete = False
    stop_loss_price = 0

    wallet = Wallet()

    skip_divergence = False
    double_candles_complete = False

    def __init__(self, origin):
        logger.info(f'START SIGNAL_BOT from {origin} interval: {INTERVAL}')
        ee.on(TelegramEventType.STATS, self.stats_requested)

    async def run(self):
        logger.info("start stream candles")
        now_in_ms = time_now_in_ms()
        interval_in_ms = self.interval_in_ms()
        num_complete_candles = 350  # To calculate RSI
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
        window = 100
        result = None
        if len(self.candlestick_list) >= window:
            ohlc.rsi = SignalBot.get_latest_rsi(self.candlestick_list, data_len, window)
            ohlc.rsi8 = SignalBot.get_latest_rsi(self.candlestick_list, data_len, window=8)
            ohlc.dema = self.get_latest_dema(self.candlestick_list, data_len, window=50)
            ohlc.tema = self.get_latest_tema(self.candlestick_list, data_len, window=50)

            bb_result = SignalBot.get_bollinger_band(self.candlestick_list, data_len=28)
            ohlc.mavg, ohlc.hband, ohlc.lband = itemgetter('mavg', 'hband', 'lband')(bb_result)

            ee.emit(Trade.COMPLETE_CANDLESTICK_EVENT, ohlc)

            if MODE == EMode.PRODUCTION:
                logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} candlestick: {ohlc.close} rsi: {ohlc.rsi:.4f} "
                            f"dema 50: {ohlc.dema:.5f} tema 50: {ohlc.tema:.5f}")

            self.candlestick_list[-1] = ohlc
            if len(self.candlestick_list) >= data_len:
                self.check_dema_tema_cross(ohlc)
                self.check_dema_tema_slope_correct(ohlc)
                self.check_rsi_retest(ohlc)
                self.get_stop_loss(ohlc)
                result = self.check_2_white_soldiers(ohlc)
        return result

    def stats_requested(self, chat_id):
        msg = (f"📊 STATS REQUESTED\n"
               f"==========================\n"
               f"{'interval':<12}: {INTERVAL} \n"
               f"{'ohlc date':<12}: {self.candlestick_list[-1].date:%Y-%m-%d %H:%M}\n"
               f"{'ohlc close':<12}: {self.candlestick_list[-1].close:.5f} USD\n"
               f"{'ohlc dema':<12}: {self.candlestick_list[-1].dema:.4f} \n"
               f"{'ohlc tema':<12}: {self.candlestick_list[-1].tema:.4f} \n"
               f"{'EMA crossed count':<12}: {self.tema_dema_crossed_counter} \n"
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
        # IchimokuIndicator
        return ema_list.iloc[-1]

    def get_latest_dema(self, data: List[Ohlc], data_len, window=50):
        """Calculate DEMA from a pandas Series and return the latest EMA"""
        close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
        EMA = _ema(series=close_price_list, periods=window)
        DEMA = (2 * EMA) - _ema(series=EMA, periods=window)
        # print(DEMA)
        return DEMA.iloc[-1]

    def get_latest_tema(self, data: List[Ohlc], data_len, window=50):
        """Calculate TEMA from a pandas Series and return the latest EMA"""
        close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
        EMA = _ema(series=close_price_list, periods=window)
        EMA2 = _ema(series=EMA, periods=window)
        EMA3 = _ema(series=EMA2, periods=window)
        TEMA = (3 * EMA) - (3 * EMA2) + EMA3
        # print(DEMA)
        return TEMA.iloc[-1]

    def check_dema_tema_cross(self, ohlc: Ohlc):

        if ohlc.tema < ohlc.dema and self.divergence != "bearish":
            self.skip_divergence = False
            self.reset_all(is_invalidate=True)
            self.divergence = "bearish"
            msg = (f"{ohlc.date:%Y-%m-%d %H:%M:%S} DEMA_TEMA_CROSSED {self.divergence} "
                   f"TEMA: {ohlc.tema:.4F} DEMA:{ohlc.dema:.4F}")
            logger.info(msg)
            telegram_bot.send_message(message=msg)
            self.tema_dema_crossed_counter += 1
            if self.wallet.active_trade > 0:
                self.skip_divergence = True
        elif ohlc.tema > ohlc.dema and self.divergence != "bullish":
            self.skip_divergence = False
            self.reset_all(is_invalidate=True)
            self.divergence = "bullish"
            msg = (f"{ohlc.date:%Y-%m-%d %H:%M:%S} DEMA_TEMA_CROSSED {self.divergence} "
                   f"TEMA: {ohlc.tema:.4F} DEMA:{ohlc.dema:.4F}")
            logger.info(msg)
            telegram_bot.send_message(message=msg)
            self.tema_dema_crossed_counter += 1
            if self.wallet.active_trade > 0:
                self.skip_divergence = True

    def check_dema_tema_slope_correct(self, ohlc: Ohlc):

        if self.temadema_slopped or self.candlestick_list[-3].dema is None \
                or self.tema_dema_crossed_counter < 2 or self.skip_divergence:
            return

        if self.divergence == "bearish" \
                and self.candlestick_list[-3].dema > self.candlestick_list[-2].dema > self.candlestick_list[-1].dema:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} DEMA GOING DOWN")
            self.temadema_slopped = True
        elif self.divergence == "bullish" \
                and self.candlestick_list[-3].dema < self.candlestick_list[-2].dema < self.candlestick_list[-1].dema:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} DEMA GOING UP")
            self.temadema_slopped = True

    def check_rsi_retest(self, ohlc: Ohlc):
        if not self.temadema_slopped or self.rsi_retest_complete:
            return

        if self.divergence == "bearish" and self.candlestick_list[-2].rsi8 > 65 \
                and self.candlestick_list[-2].rsi8 > self.candlestick_list[-1].rsi8:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} RSI RETEST COMPLETE")
            self.stop_loss_price = ohlc.high
            self.rsi_retest_complete = True
        elif self.divergence == "bullish" and self.candlestick_list[-2].rsi8 < 35 \
                and self.candlestick_list[-2].rsi8 < self.candlestick_list[-1].rsi8:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} RSI RETEST COMPLETE")
            self.stop_loss_price = ohlc.low
            self.rsi_retest_complete = True

    # Check 2 red/green candlesticks to trigger
    def check_2_white_soldiers(self, ohlc: Ohlc):
        if not self.rsi_retest_complete or self.double_candles_complete:
            return

        divergence_result = {
            'divergence': self.divergence,
            'rsi2': ohlc,
            'price': self.point0_price,
            'retest_ohlc': self.candlestick_list[-2],
            'stop_loss_price': self.stop_loss_price
        }
        candle1 = self.candlestick_list[-2].close - self.candlestick_list[-2].open
        candle2 = self.candlestick_list[-1].close - self.candlestick_list[-1].open

        if self.divergence == "bearish" and candle1 <= -CANDLE_BUFFER and candle2 <= -CANDLE_BUFFER:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} TWO RED CANDLE {candle1:.5f} {candle2:.5f}")
            if MODE == EMode.PRODUCTION:
                ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            # self.reset_all()
            self.double_candles_complete = True
            return divergence_result
        elif self.divergence == "bullish" and candle1 >= CANDLE_BUFFER and candle2 >= CANDLE_BUFFER:
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} TWO GREEN CANDLE  {candle1:.5f} {candle2:.5f}")
            if MODE == EMode.PRODUCTION:
                ee.emit(ESignal.DIVERGENCE_FOUND, divergence_result)
            self.double_candles_complete = True
            # self.reset_all()
            return divergence_result

    def get_stop_loss(self, ohlc: Ohlc):
        if not self.rsi_retest_complete:
            return

        if self.divergence == "bearish" and ohlc.high > self.stop_loss_price:
            self.stop_loss_price = ohlc.high
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} NEW STOP LOSS {self.stop_loss_price:.4f}")

        elif self.divergence == "bullish" and ohlc.low < self.stop_loss_price:
            self.stop_loss_price = ohlc.low
            logger.info(f"{ohlc.date:%Y-%m-%d %H:%M:%S} NEW STOP LOSS {self.stop_loss_price:.4f}")

    def reset_all(self, is_invalidate=False):
        if is_invalidate:
            msg = (f"SIGNALS INVERTED\n"
                   f"{self.divergence} divergence\n"
                   f"EMA crossed counter: {self.tema_dema_crossed_counter}")
            logger.info(msg)
            telegram_bot.send_message(message=msg)
        self.point0_price = 0
        self.temadema_slopped = False
        self.rsi_retest_complete = False
        self.double_candles_complete = False

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
