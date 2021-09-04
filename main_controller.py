import asyncio
import sys
import time
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime, timedelta
from operator import itemgetter
from typing import List

import pandas as pd

from custom_types.controller_type import EMode
from custom_types.exchange_type import ICandlestick
from service.dca_bot import DcaBot
from service.logging import setup_logging, controller_logger as logger
from service.signal_bot2 import SignalBot
from service.telegram_bot import telegram_bot
from settings import MODE, SYMBOL, INTERVAL, IS_PAPER_TRADING, MAX_CONCURRENT_TRADE, TRADE_LEVERAGE
from utils.events import ESignal, ee, Trade, TelegramEventType

startTime = time.time()


def get_uptime():
    """
    Returns the number of seconds since the program started.
    """
    # do return startTime if you just want the process start time
    return time.time() - startTime


dateparse = lambda x: datetime.strptime(x, '%d-%m-%y %H:%M')
date = datetime.now()


def exception_handler(type, value, tb):
    logger.exception("Uncaught exception: {0}".format(str(value)))


# Install exception handler
sys.excepthook = exception_handler


class Controller:
    CANDLESTICK_LIMIT = 499
    BUFFER_TIMEOUT_IN_SEC = 1
    list_15m: List[ICandlestick] = []
    list_5m: List[ICandlestick] = []
    dca_bots: List[DcaBot] = []
    signal_bot: SignalBot = None

    dca_bot_counter = 0

    active_dca_bot_counter = 0

    def __init__(self):
        self.signal_bot = SignalBot(origin="main_controller")
        ee.on(ESignal.DIVERGENCE_FOUND, self.on_divergence)
        ee.on(Trade.STOP_TRADE, self.pop_dca_bot)
        ee.on(TelegramEventType.STATS, self.stats_requested)
        logger.info(f"{SYMBOL=} {INTERVAL=}")
        telegram_bot.send_message(message=f"start {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                                          f"{MODE=}\n"
                                          f"{SYMBOL=}\n"
                                          f"{INTERVAL=}\n"
                                          f"{IS_PAPER_TRADING=}\n"
                                          f"{TRADE_LEVERAGE=}")

    async def run_signal_bot(self):
        await self.signal_bot.run()

    def read_filepath_or_buffer(self, filepath_or_buffer=None):
        """Read chart data from a filepath or buffer"""
        if filepath_or_buffer is None:
            df = pd.read_csv("assets/01Jan21-00꞉00.csv", parse_dates=["date"], date_parser=dateparse)
            # df = pd.read_csv("assets/01Aug21-00꞉00.csv", parse_dates=["date"], date_parser=dateparse)
            # df = pd.read_csv("assets/Binance_MATICUSDT_minute_2021.csv", parse_dates=["date"], date_parser=dateparse)
            # df = df[(df["date"] >= datetime(2021, 1, 1, 0, 00)) & (df["date"] < datetime(2021, 7, 30, 23, 0))]
            # df = df[(df["date"] >= datetime(2021, 1, 1, 0, 00)) & (df["date"] < datetime(2021, 1, 30, 23, 0))]
            # df = df[(df["date"] >= datetime(2021, 7, 1, 0, 00)) & (df["date"] < datetime(2021, 7, 30, 23, 0))]
            # df = df[(df["date"] >= datetime(2021, 1, 1, 0, 00)) & (df["date"] < datetime(2021, 8, 20, 23, 0))]
            df = df[(df["date"] >= datetime(2021, 1, 1, 0, 00)) & (df["date"] < datetime(2021, 8, 30, 23, 0))]
            print(f"{date:%Y-%m-%d %H:%M:%S} loading data... number of rows: {len(df.index)}")
            for _, row in df.iterrows():
                candlestick = {'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'],
                               'openTime': int(row['date'].timestamp()*1000)}

                divergence_result = self.signal_bot.candle_incoming(candlestick)
                if isinstance(divergence_result, dict):
                    self.on_divergence(divergence_result)

                # if self.check_safe_resample_5m(candlestick):
                #     self.resample_candle_5m(self.list_5m)

                # if self.check_safe_resample_15m(candlestick):
                #     self.resample_candle_15m(self.list_15m)

                for dca_bot in self.dca_bots:
                    _id = dca_bot.process_candlestick(candlestick)
                    # if _id is not None:
                    #     self.pop_dca_bot(_id)
            logger.info("--end--")

    def check_safe_resample_15m(self, _1m_candlestick_dict: ICandlestick):
        minute = int(datetime.fromtimestamp(_1m_candlestick_dict['openTime']/1000).strftime("%M"))
        if minute % 15 == 0:
            self.list_15m = []
        self.list_15m.append(_1m_candlestick_dict)
        return True if len(self.list_15m) == 15 else False

    def resample_candle_15m(self, candles: List[ICandlestick]):
        ohlc = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
        df = pd.DataFrame(candles)
        df['openTime'] = pd.to_datetime(df['openTime']/1000, unit='s')
        df = df.resample(rule='15Min', on='openTime').apply(ohlc)
        df['openTime'] = df.index
        row = df.iloc[0]
        candlestick = {'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'],
                       'openTime': int(row['openTime'].timestamp() * 1000)}
        divergence_result = self.signal_bot.candle_incoming(candlestick)
        if isinstance(divergence_result, dict):
            self.on_divergence(divergence_result)

    def check_safe_resample_5m(self, _1m_candlestick_dict: ICandlestick):
        minute = int(datetime.fromtimestamp(_1m_candlestick_dict['openTime']/1000).strftime("%M"))
        if minute % 5 == 0:
            self.list_5m = []
        self.list_5m.append(_1m_candlestick_dict)
        return True if len(self.list_5m) == 5 else False

    def resample_candle_5m(self, candles: List[ICandlestick]):
        ohlc = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
        df = pd.DataFrame(candles)
        df['openTime'] = pd.to_datetime(df['openTime']/1000, unit='s')
        df = df.resample(rule='5Min', on='openTime').apply(ohlc)
        df['openTime'] = df.index
        row = df.iloc[0]
        candlestick = {'open': row['open'], 'high': row['high'], 'low': row['low'], 'close': row['close'],
                       'openTime': int(row['openTime'].timestamp()*1000)}
        divergence_result = self.signal_bot.candle_incoming(candlestick)
        if isinstance(divergence_result, dict):
            self.on_divergence(divergence_result)

    def on_divergence(self, data):
        if self.active_dca_bot_counter < MAX_CONCURRENT_TRADE:
            self.dca_bot_counter += 1
            self.active_dca_bot_counter += 1
            divergence, rsi2, retest_ohlc = itemgetter('divergence', 'rsi2', 'retest_ohlc')(data)
            dca_bot = DcaBot(f"A{self.dca_bot_counter:04d}", divergence, rsi2.date, rsi2, retest_ohlc)
            self.dca_bots.append(dca_bot)
        else:
            msg = f"Active trade overload {self.active_dca_bot_counter=}"
            logger.info(msg)
            telegram_bot.send_message(message=msg)

    def pop_dca_bot(self, _id):
        bot_lists_to_remove = list(filter(lambda item: str(item) == str(_id), self.dca_bots))
        logger.info(f"popping with {_id} : {len(self.dca_bots)} to remove {len(bot_lists_to_remove)}")
        for dca_bot in bot_lists_to_remove:
            dca_bot.remove_all_listeners()
            try:
                self.dca_bots.remove(dca_bot)
            except Exception as ex:
                logger.error(f"dca_bots remove from list failed...\n"
                             f"{ex}")
            logger.info(f"REMAINING {len(self.dca_bots)}")
            self.active_dca_bot_counter -= 1

        for dca_bot in self.dca_bots:
            logger.info(f"remaining bots _id: {str(dca_bot)}")

    def stats_requested(self, chat_id):
        bots_msg = ""
        for dca_bot in self.dca_bots:
            bots_msg = f"{bots_msg}_id: {str(dca_bot)}\n"

        td = timedelta(seconds=round(get_uptime()))
        timeup = f"{td.days}days, {(td.seconds // 3600) % 24}hrs, {(td.seconds // 60) % 60}mins, {td.seconds % 60}secs"
        msg = (f"📊 STATS REQUESTED\n"
               f"==========================\n"
               f"{'Uptime':<12}: {timeup} \n"
               f"{'ACTIVE bots':<12}: {len(self.dca_bots)} \n"
               f"{bots_msg}"
               f"==========================\n")
        telegram_bot.send_message(chat_id=chat_id, message=msg)


async def main():
    setup_logging()
    logger.info("start controller")

    telegram_bot.start_bot()
    controller = Controller()
    if MODE == EMode.PRODUCTION:
        with ThreadPoolExecutor(max_workers=1) as executor:
            event_loop = asyncio.get_event_loop()
            await asyncio.gather(controller.run_signal_bot(),
                                 event_loop.run_in_executor(executor, telegram_bot.run_bot)
                                 )
    elif MODE == EMode.TEST:
        controller.read_filepath_or_buffer()


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(main())
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
