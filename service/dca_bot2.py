import asyncio
import os

import time
from datetime import datetime
from typing import Literal, Union
import pytz
from dotenv import load_dotenv

from classes.ohlc import Ohlc
from custom_types.controller_type import EMode
from custom_types.exchange_type import ICandlestick, ICandlestickEvent, ICandlestickEventData
from database.dora_trade_transaction import DoraTradeTransaction
from service.logging import dca_bot_logger as logger
from service.telegram_bot import telegram_bot
from service.wallet import wallet
from settings import IS_PAPER_TRADING, SYMBOL, INTERVAL, MODE
from utils.events import ee, Trade, TelegramEventType, EExchange

load_dotenv()
DEFAULT_TELEGRAM_NOTIFICATION_ID = os.getenv('DEFAULT_TELEGRAM_NOTIFICATION_ID')
EXIT_PRICE_BUFFER = .0005


class DcaBot:
    dora_trade_transaction: DoraTradeTransaction
    _id = None
    date = datetime.now()
    divergence: Literal['bullish', 'bearish'] = None
    start_price = 0
    top_price = 0
    avg_buyin_price = 0
    last_buyin_price = 0
    stop_loss_price = 0
    next_safety_order_price = 0
    base_order_complete = False

    current_ohlc: Ohlc = None
    prev_ohlc: Ohlc = None

    base_order_size = 100
    safety_order_size = 100
    target_profit_percentage = 0.005
    max_safety_trades_count = 4
    price_deviation_trigger_so = 0.01  # percentage
    next_deviation_trigger_so = 0.01
    safety_trade_opened = 0

    # Test wallet part
    trade_bot_balance = 600
    coin_amount = 0
    owed_coin_amount = 0

    stables_amt_in_short = 0
    stables_amt_in_long = 0
    full_stables_amt_in_short = 0
    full_stables_amt_in_long = 0

    full_coin_amount = 0
    full_owed_coin_amount = 0
    cumulative_pnl = 0
    cummulative_pnl_pct = 0
    current_price = 0

    end_counter = 0

    def __init__(self, _id, divergence, date, ohlc: Ohlc):
        self._id = _id
        self.date = date
        self.divergence = divergence
        self.current_ohlc = ohlc
        self.trade_bot_balance = wallet.get_start_amount()
        if self.trade_bot_balance == 0:
            self.divergence = None
            ee.emit(Trade.STOP_TRADE, self._id)
        # 1 for base order, 4 for safety order
        self.base_order_size = self.trade_bot_balance / (self.max_safety_trades_count + 1)
        self.safety_order_size = self.base_order_size
        logger.info(f"INIT WALLET\n"
                    f"==============================\n"
                    f"{date:%Y-%m-%d %H:%M:%S}\n"
                    f"{'_id':<15}: {self._id} \n"
                    f"{'divergence':<15}: {self.divergence} \n"
                    f"{'start_price':<15}: {self.start_price} usd\n"
                    f"{'base order':<15}: {self.base_order_size:.4f} usd\n"
                    f"{'trade_bot_balance':<15}: {self.trade_bot_balance:.4f} usd\n")
        self.end_counter = 0
        ee.on(TelegramEventType.STATS, self.stats_requested)
        ee.on(EExchange.CANDLESTICK_EVENT, self.on_candlestick_event)
        ee.on(Trade.COMPLETE_CANDLESTICK_EVENT, self.on_complete_candlestick_event)
        self.dora_trade_transaction = DoraTradeTransaction(_id=self._id, symbol=SYMBOL, start_time=datetime.now(),
                                                           txn_type="", txn_interval=INTERVAL)

    def on_candlestick_event(self, i_candlestick_event: ICandlestickEvent):
        candlestick = i_candlestick_event['data']
        self.process_candlestick(candlestick)

    def on_complete_candlestick_event(self, ohlc: Ohlc):
        self.current_ohlc = ohlc
        self.prev_ohlc = ohlc

    def process_candlestick(self, candlestick: Union[ICandlestick, ICandlestickEventData]):
        if self.divergence is None:
            if self.end_counter < 1:
                msg = (f"⛔ Divergence not exist for dca bot, popping instances\n"
                       f"_id: {self._id}")
                logger.info(msg)
                telegram_bot.send_message(message=msg)
                ee.emit(Trade.STOP_TRADE, self._id)
            self.end_counter += 1
            return self._id

        self.current_price = float(candlestick['close'])
        if MODE == EMode.TEST:
            self.date = datetime.utcfromtimestamp(candlestick['openTime']/1000)
            self.process_current_price(candlestick['open'])
            self.process_current_price(candlestick['high'])
            self.process_current_price(candlestick['low'])
        else:
            self.date = datetime.fromtimestamp(candlestick['startTime'] / 1000)
            self.process_current_price(self.current_price)

    def process_current_price(self, current_price):
        self.trigger_base_order(current_price)
        self.check_price_hit_target_profit(current_price)
        self.trigger_safety_order(current_price)
        self.exit_at_avg_price(current_price)

    def trigger_base_order(self, current_price):
        if self.base_order_complete:
            return
        self.base_order_complete = True
        self.last_buyin_price = current_price
        self.avg_buyin_price = current_price
        self.start_price = current_price
        self.calc_final_stop_loss_price()
        logger.info(f"TRIGGERING BASE ORDER {self.date:%Y-%m-%d %H:%M:%S}")
        if self.divergence == "bullish":
            self.next_safety_order_price = current_price * (1 - self.next_deviation_trigger_so)
            self.open_long_position(current_price, self.base_order_size)
        elif self.divergence == "bearish":
            self.next_safety_order_price = current_price * (1 + self.next_deviation_trigger_so)
            self.open_short_position(current_price, self.base_order_size)
        self.show_target_price(current_price, send_telegram=True)

    def show_target_price(self, current_price, chat_id=DEFAULT_TELEGRAM_NOTIFICATION_ID, send_telegram=False):
        msg = (f"TARGET:\n"
               f"{'🆔 _id':<15}: {self._id}\n"
               f"{'avg buy price':<15}: {self.avg_buyin_price:.4f} USD\n"
               f"{'❌ loss price':<15}: {self.stop_loss_price:.4f}\n"
               f"{'⏫ s.o. price':<15}: {self.next_safety_order_price:.4f} USD\n")
        if send_telegram:
            logger.info(msg)
            telegram_bot.send_message(chat_id=chat_id, message=msg)
        return msg

    def check_price_hit_target_profit(self, current_price):
        if self.divergence is None:
            return

        price_diff = current_price - self.avg_buyin_price
        percent_diff = (price_diff / self.avg_buyin_price) * 100

        # logger.info(f"{price_diff=} {percent_diff=}")
        # if self.divergence == "bullish" and current_price < self.current_ohlc.tema:
        #     self.close_long_position(current_price, 100)
        #     self.reset_all()
        # elif self.divergence == "bearish" and current_price > self.current_ohlc.tema:
        #     self.close_short_position(current_price, 100)
        #     self.reset_all()

        if self.divergence == "bullish" and percent_diff > 0.5:
            self.close_long_position(current_price, 100)
            self.reset_all()
        elif self.divergence == "bearish" and percent_diff < -0.5:
            self.close_short_position(current_price, 100)
            self.reset_all()

        # if self.divergence == "bullish" and self.current_ohlc.rsi > 70:
        #     self.close_long_position(current_price, 100)
        #     self.reset_all()
        # elif self.divergence == "bearish" and self.current_ohlc.rsi < 30:
        #     self.close_short_position(current_price, 100)
        #     self.reset_all()
        #
        # if self.divergence == "bullish" and self.current_ohlc.tema < self.current_ohlc.dema:
        #     self.close_long_position(current_price, 100)
        #     self.reset_all()
        # elif self.divergence == "bearish" and self.current_ohlc.tema > self.current_ohlc.dema:
        #     self.close_short_position(current_price, 100)
        #     self.reset_all()

    def trigger_safety_order(self, current_price):
        price_diff_from_end = current_price - self.last_buyin_price
        percent_diff = price_diff_from_end / self.last_buyin_price

        if self.divergence == "bullish" and percent_diff <= -self.next_deviation_trigger_so:
            if self.max_safety_trades_count > 0:
                self.last_buyin_price = current_price
                # self.avg_buyin_price = (self.avg_buyin_price + self.last_buyin_price) / 2
                self.max_safety_trades_count -= 1
                self.safety_trade_opened += 1
                self.open_long_position(current_price, self.safety_order_size)
                self.next_safety_order_price = current_price * (1 - self.next_deviation_trigger_so)
                # self.next_deviation_trigger_so += self.price_deviation_trigger_so
                target_msg = self.show_target_price(current_price)
                msg = (f"🦺 Safety order trigger\n"
                       f"{'_id':<15}: {self._id}\n"
                       f"{'Avg buy price':<15}: {self.avg_buyin_price:.4f} USD\n"
                       f"{'Remaining s.o.':<15}: {self.max_safety_trades_count}\n"
                       f"{'Next s.o. price':<15}: {self.next_safety_order_price:.4f} USD\n"
                       f"{'Next s.o.(%)':<15}: {self.next_deviation_trigger_so * 100}%\n"
                       f"{target_msg}")
                logger.info(msg)
                telegram_bot.send_message(message=msg)
            else:
                self.close_long_position(current_price, 100)
                self.reset_all()
        elif self.divergence == "bearish" and percent_diff >= self.next_deviation_trigger_so:
            if self.max_safety_trades_count > 0:
                self.last_buyin_price = current_price
                # self.avg_buyin_price = (self.avg_buyin_price + self.last_buyin_price) / 2
                self.max_safety_trades_count -= 1
                self.safety_trade_opened += 1
                self.open_short_position(current_price, self.safety_order_size)
                self.next_safety_order_price = current_price * (1 + self.next_deviation_trigger_so)
                # self.next_deviation_trigger_so += self.price_deviation_trigger_so
                target_msg = self.show_target_price(current_price)
                msg = (f"🦺 Safety order trigger\n"
                       f"{'_id':<15}: {self._id}\n"
                       f"{'Avg buy price':<15}: {self.avg_buyin_price:.4f} USD\n"
                       f"{'Remaining s.o.':<15}: {self.max_safety_trades_count}\n"
                       f"{'Next s.o. price':<15}: {self.next_safety_order_price:.4f} USD\n"
                       f"{'Next s.o.(%)':<15}: {self.next_deviation_trigger_so * 100}%\n"
                       f"{target_msg}")
                logger.info(msg)
                telegram_bot.send_message(message=msg)
            else:
                self.close_short_position(current_price, 100)
                self.reset_all()

    def exit_at_avg_price(self, current_price):
        if self.divergence == "bullish" and self.safety_trade_opened > 0 \
                and current_price >= (self.avg_buyin_price * (1 + EXIT_PRICE_BUFFER)):
            logger.info(f"UNSAFE EXIT AT AVG PRICE, safety opened: {self.safety_trade_opened}")
            self.close_long_position(current_price, 100)
            self.reset_all()
        elif self.divergence == "bearish" and self.safety_trade_opened > 0 \
                and current_price <= (self.avg_buyin_price * (1 - EXIT_PRICE_BUFFER)):
            logger.info(f"UNSAFE EXIT AT AVG PRICE, safety opened: {self.safety_trade_opened}")
            self.close_short_position(current_price, 100)
            self.reset_all()

    def calc_final_stop_loss_price(self):
        # total_percent = 0
        # last_cum_percent = 0
        # for x in range(self.max_safety_trades_count+1):
        #     last_cum_percent += self.price_deviation_trigger_so
        #     total_percent += last_cum_percent
        total_percent = (self.max_safety_trades_count + 1) * self.price_deviation_trigger_so

        if self.divergence == "bullish":
            self.stop_loss_price = self.start_price * (1 - total_percent)
        elif self.divergence == "bearish":
            self.stop_loss_price = self.start_price * (1 + total_percent)

    def reset_all(self):
        self.divergence = None
        if MODE == EMode.TEST:
            self.dora_trade_transaction.end_time = self.date
        wallet.end_trade(self.cumulative_pnl, self.dora_trade_transaction)
        ee.emit(Trade.STOP_TRADE, self._id)

    def stats_requested(self, chat_id):
        price_diff_from_end = self.current_price - self.avg_buyin_price
        percent_diff = price_diff_from_end / self.avg_buyin_price

        so_price_diff_from_end = self.current_price - self.last_buyin_price
        so_percent_diff = so_price_diff_from_end / self.last_buyin_price

        msg = (f"📊 DCA BOT STATS\n"
               f"=======================\n"
               f"{'_id':<15}: {self._id} \n"
               f"{'divergence':<15}: {self.divergence} \n"
               f"{'avg buy':<15}: {self.avg_buyin_price:.4f} USD\n"
               f"{'last buy':<15}: {self.last_buyin_price} USD\n"
               f"{'Safety trades':<15}: {self.max_safety_trades_count} \n"
               f"{'Coin amount':<15}: {self.coin_amount} \n"
               f"{'Trade bot bal':<15}: {self.trade_bot_balance:.3f} USD\n"
               f"{'Next S.O.':<15}: {self.next_safety_order_price:.3f} USD \n"
               f"{'TP':<15}: "
               f"{self.current_ohlc.hband if self.divergence == 'bullish' else self.current_ohlc.lband:.3f} USD\n"
               f"=======================\n")
        telegram_bot.send_message(chat_id=chat_id, message=msg)
        self.show_target_price(self.current_price, chat_id=chat_id)

    def open_short_position(self, current_price, collateral_amount):
        borrowed_coin_amount = round(collateral_amount / current_price)
        collateral_amount = borrowed_coin_amount * current_price

        self.avg_buyin_price = (self.stables_amt_in_short + collateral_amount) / (self.owed_coin_amount + borrowed_coin_amount)

        self.trade_bot_balance -= collateral_amount
        self.owed_coin_amount += borrowed_coin_amount
        self.stables_amt_in_short += collateral_amount
        self.full_owed_coin_amount = self.owed_coin_amount
        self.full_stables_amt_in_short += collateral_amount

        if not IS_PAPER_TRADING:
            wallet.open_short_position(quantity_in_coin=borrowed_coin_amount)

        msg = (f"{self.date}\n"
               f"SHORT OPENED\n"
               f"--------------------------\n"
               f"{'_id':<15}: {self._id}\n"
               f"{'Price':<15}: {current_price:.4f} USD\n"
               f"{'USDT Bal/trade':<15}: {self.trade_bot_balance:.2f} USD\n"
               f"{'Coin':<15}: {self.coin_amount:.4f}\n"
               f"{'Borrowed':<15}: {self.owed_coin_amount:.2f} ({collateral_amount:.2f} USD)\n"
               f"--------------------------\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)

    def open_long_position(self, current_price, collateral_amount):
        coin_amount = round(collateral_amount / current_price)
        collateral_amount = coin_amount * current_price
        self.avg_buyin_price = (self.stables_amt_in_long + collateral_amount) / (self.coin_amount + coin_amount)
        self.trade_bot_balance -= collateral_amount
        self.coin_amount += coin_amount
        self.stables_amt_in_long += collateral_amount
        self.full_coin_amount = self.coin_amount
        self.full_stables_amt_in_long = self.stables_amt_in_long

        if not IS_PAPER_TRADING:
            wallet.open_long_position(quantity_in_coin=coin_amount)

        msg = (f"{self.date}\n"
               f"LONG OPENED\n"
               f"--------------------------\n"
               f"{'_id':<15}: {self._id}\n"
               f"{'Price':<15}: {current_price} USD\n"
               f"{'avg price':<15}: {self.avg_buyin_price} USD\n"
               f"{'USD Bal/trade':<15}: {self.trade_bot_balance:.2f} USD\n"
               f"{'Coin':<15}: {self.coin_amount:.2f} ({collateral_amount:.2f} USD)\n"
               f"{'Borrowed':<15}: {self.owed_coin_amount:.2f}\n"
               f"--------------------------\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)

    def close_short_position(self, current_price, percentage_of_position):
        coin_amount_to_rebuy = round(self.full_owed_coin_amount * percentage_of_position / 100)
        value_to_close_in_stables = (coin_amount_to_rebuy / self.full_owed_coin_amount) * self.full_stables_amt_in_short

        if coin_amount_to_rebuy > self.owed_coin_amount:
            coin_amount_to_rebuy = self.owed_coin_amount
            value_to_close_in_stables = self.stables_amt_in_short

        amount_of_coin_to_rebuy_in_usdt = coin_amount_to_rebuy * current_price
        pnl = value_to_close_in_stables - amount_of_coin_to_rebuy_in_usdt
        self.cumulative_pnl += pnl
        self.trade_bot_balance += pnl + value_to_close_in_stables
        self.owed_coin_amount -= coin_amount_to_rebuy
        self.stables_amt_in_short -= value_to_close_in_stables
        if not IS_PAPER_TRADING:
            wallet.close_short_position(position_amt=coin_amount_to_rebuy)

        msg = (f"{self.date} SHORT CLOSED (% of position: {percentage_of_position}%)\n"
               f"--------------------------\n"
               f"{'_id':<15}: {self._id}\n"
               f"{'Price':<15}: {current_price:.4f} USD\n"
               f"{'USD Bal':<15}: {self.trade_bot_balance:.2f} USD\n"
               f"{'Coin':<15}: {self.coin_amount:.4f}\n"
               f"{'Borrowed':<15}: {self.owed_coin_amount:.2f}\n"
               f"{'Amt To rebuy':<15}: {coin_amount_to_rebuy:.2f} ({amount_of_coin_to_rebuy_in_usdt:.2f} USD)\n"
               f"{'PNL':<15}: {pnl:.4f} USD\n"
               f"{'SHORTED AMT':<15}: {value_to_close_in_stables:.4f} USD\n"
               f"--------------------------\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)

    def close_long_position(self, current_price, percentage_of_position):
        coin_amount_to_sell = round(self.full_coin_amount * percentage_of_position / 100)
        value_to_close_in_stables = (coin_amount_to_sell / self.full_coin_amount) * self.full_stables_amt_in_long

        if coin_amount_to_sell > self.coin_amount:
            coin_amount_to_sell = self.coin_amount
            value_to_close_in_stables = self.stables_amt_in_long
        amount_of_coin_to_sell_in_usdt = coin_amount_to_sell * current_price

        pnl = amount_of_coin_to_sell_in_usdt - value_to_close_in_stables
        self.trade_bot_balance += pnl + value_to_close_in_stables
        self.coin_amount -= coin_amount_to_sell
        self.cumulative_pnl += pnl
        self.stables_amt_in_long -= value_to_close_in_stables
        if not IS_PAPER_TRADING:
            wallet.close_long_position(position_amt=coin_amount_to_sell)

        msg = (f"{self.date} LONG CLOSED (% of position: {percentage_of_position}%)\n"
               f"----------------------------\n"
               f"{'_id':<15}: {self._id}\n"
               f"{'Price':<15}: {current_price:.4f} USD\n"
               f"{'USD Bal':<15}: {self.trade_bot_balance:.2f} USD\n"
               f"{'Coin':<15}: {self.coin_amount:.4f}\n"
               f"{'Borrowed':<15}: {self.owed_coin_amount:.2f}\n"
               f"{'stables_amt_in_long':<15}: {value_to_close_in_stables:.2f}\n"
               f"{'Amt To sell':<15}: {coin_amount_to_sell:.2f} ({amount_of_coin_to_sell_in_usdt:.2f} USD)\n"
               f"{'pnl':<15}: {pnl:.4f} USD\n"
               f"----------------------------\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)

    def get_id(self):
        return self._id

    def __repr__(self):
        return self._id

    def remove_all_listeners(self):
        try:
            if TelegramEventType.STATS in ee._events and self.stats_requested in ee._events[TelegramEventType.STATS]:
                ee.remove_listener(TelegramEventType.STATS, self.stats_requested)
            if EExchange.CANDLESTICK_EVENT in ee._events and self.on_candlestick_event in ee._events[EExchange.CANDLESTICK_EVENT]:
                ee.remove_listener(EExchange.CANDLESTICK_EVENT, self.on_candlestick_event)
        except Exception as ex:
            logger.error(f"remove_all_listeners() failed...\n"
                         f"{ex}")

    def __del__(self):
        logger.info(f"dca_bot {self._id} deleted")


async def main():
    telegram_bot.start_bot()
    DcaBot(f"A0001", divergence="bearish", start_price=1.3878, date=datetime.now())


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(main())
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
