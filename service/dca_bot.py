import asyncio
from functools import reduce
from operator import itemgetter
from uuid import uuid4

import math
import os

from time import sleep
from datetime import datetime
from typing import Literal, Union, List, Optional
from dotenv import load_dotenv

from classes.ohlc import Ohlc
from custom_types.controller_type import EMode
from custom_types.exchange_type import ICandlestick, ICandlestickEvent, ICandlestickEventData, IAccountTrade
from custom_types.trade_type import ICalcFee, IFeeItems
from database.dora_trade_transaction import DoraTradeTransaction
from service.exchange import exchange
from service.logging import dca_bot_logger as logger
from service.telegram_bot import telegram_bot
from service.wallet import wallet
from settings import IS_PAPER_TRADING, SYMBOL, INTERVAL, MODE
from utils.events import ee, Trade, TelegramEventType, EExchange
from utils.candlestick_utils import time_now_in_ms

load_dotenv()
DEFAULT_TELEGRAM_NOTIFICATION_ID = os.getenv('DEFAULT_TELEGRAM_NOTIFICATION_ID')

TARGET_PROFIT_PERCENTAGE = 0.0025
STOP_LOSS_PERCENTAGE = 0.005


class DcaBot:
    dora_trade_transaction: DoraTradeTransaction
    _id = None
    date = datetime.now()
    divergence: Optional[Literal['bullish', 'bearish']] = None
    entry_price = 0
    avg_buyin_price = 0
    stop_loss_price = 0
    take_profit_price = 0

    base_order_complete = False
    current_ohlc: Ohlc = None
    candlestick_list: List[Ohlc] = []

    fee_items: IFeeItems = {'trade_start_time': None, 'order_ids': None}

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

    end_counter = 0

    candles_count_passed_entry = 0
    reverse_ema_counter = 0
    current_position_on_ema: Literal['above', 'below'] = None

    def __init__(self, _id, divergence, date, ohlc: Ohlc, stop_loss_price):
        self._id = _id
        self.date = date
        self.divergence = divergence
        self.current_ohlc = ohlc
        self.stop_loss_price = stop_loss_price
        self.trade_bot_balance = wallet.get_start_amount()
        self.fee_items = {'trade_start_time': time_now_in_ms(), 'order_ids': []}
        if self.trade_bot_balance == 0:
            self.divergence = None
            ee.emit(Trade.STOP_TRADE, self._id)

        logger.info(f"INIT WALLET\n"
                    f"==============================\n"
                    f"{date:%Y-%m-%d %H:%M:%S}\n"
                    f"{'_id':<15}: {self._id} \n"
                    f"{'divergence':<15}: {self.divergence} \n"
                    f"{'start_price':<15}: {self.entry_price} usd\n"
                    f"{'trade_bot_balance':<15}: {self.trade_bot_balance:.4f} usd\n")
        self.end_counter = 0
        ee.on(TelegramEventType.STATS, self.stats_requested)
        ee.on(EExchange.CANDLESTICK_EVENT, self.on_candlestick_event)
        ee.on(Trade.COMPLETE_CANDLESTICK_EVENT, self.on_complete_candlestick_event)
        self.dora_trade_transaction = DoraTradeTransaction(_id=self._id, symbol=SYMBOL, start_time=self.date,
                                                           txn_type="", txn_interval=INTERVAL)

    def on_candlestick_event(self, i_candlestick_event: ICandlestickEvent):
        candlestick = i_candlestick_event['data']
        self.process_candlestick(candlestick)

    def on_complete_candlestick_event(self, ohlc: Ohlc):
        self.date = ohlc.date
        self.current_ohlc = ohlc
        self.candlestick_list.append(ohlc)
        self.check_hit_stop_loss(self.current_ohlc)
        self.candlestick_list = self.candlestick_list[-4:]

    def process_candlestick(self, candlestick: Union[ICandlestick, ICandlestickEventData]):
        if self.divergence is None:
            if self.end_counter < 1:
                msg = (f"??? Divergence not exist for dca bot, popping instances\n"
                       f"_id: {self._id}")
                logger.info(msg)
                telegram_bot.send_message(message=msg)
                ee.emit(Trade.STOP_TRADE, self._id)
            self.end_counter += 1
            return self._id

        if MODE == EMode.TEST:
            self.date = datetime.utcfromtimestamp(candlestick['openTime'] / 1000)
            self.process_current_price(candlestick['open'])
            self.process_current_price(candlestick['high'])
            self.process_current_price(candlestick['low'])
        else:
            self.date = datetime.fromtimestamp(candlestick['startTime'] / 1000)
            self.process_current_price(float(candlestick['close']))

    def process_current_price(self, current_price):
        self.trigger_base_order(current_price)
        self.check_price_hit_target_profit(current_price)

    def trigger_base_order(self, current_price):
        if self.base_order_complete:
            return
        self.base_order_complete = True
        self.entry_price = current_price

        if self.divergence == "bullish":
            self.take_profit_price = current_price * (1 + TARGET_PROFIT_PERCENTAGE)
            self.stop_loss_price = current_price * (1 - STOP_LOSS_PERCENTAGE)
            self.open_long_position(current_price, self.trade_bot_balance)
        elif self.divergence == "bearish":
            self.take_profit_price = current_price * (1 - TARGET_PROFIT_PERCENTAGE)
            self.stop_loss_price = current_price * (1 + STOP_LOSS_PERCENTAGE)
            self.open_short_position(current_price, self.trade_bot_balance)

        logger.info(f"INITIATE ORDER {self.date:%Y-%m-%d %H:%M:%S}\n"
                    f"{'Current Price':<15}: {current_price:.04f}\n"
                    f"{'Take Profit':<15}: {self.take_profit_price:.04f}\n"
                    f"{'Stop Loss':<15}: {self.stop_loss_price:.04f}")

    def check_price_hit_target_profit(self, current_price):
        if self.divergence is None:
            return

        if self.divergence == "bullish" and current_price >= self.take_profit_price:
            if MODE == EMode.TEST:
                current_price = self.take_profit_price
            self.close_long_position(current_price, 100)
            self.reset_all()
        elif self.divergence == "bearish" and current_price <= self.take_profit_price:
            if MODE == EMode.TEST:
                current_price = self.take_profit_price
            self.close_short_position(current_price, 100)
            self.reset_all()

    def check_hit_stop_loss(self, ohlc: Ohlc):
        if self.divergence == "bullish" and ohlc.close <= self.stop_loss_price:
            logger.info(f"HIT STOP LOSS! @ {self.stop_loss_price:.04f}USD")
            self.close_long_position(ohlc.close, 100)
            self.reset_all()
        elif self.divergence == "bearish" and ohlc.close >= self.stop_loss_price:
            logger.info(f"HIT STOP LOSS! @ {self.stop_loss_price:.04f}USD")
            self.close_short_position(ohlc.close, 100)
            self.reset_all()

    def reset_all(self):
        self.divergence = None
        asset, fee, fee_in_usdt = itemgetter('asset', 'fee', 'fee_in_usdt')(self.calc_fee())
        pnl = self.cumulative_pnl - fee_in_usdt
        pnl_percentage = pnl / self.trade_bot_balance * 100

        if MODE == EMode.TEST:
            self.dora_trade_transaction.end_time = self.date

        msg = (f"END TRADE REPORT\n"
               f"==============================\n"
               f"{'_id':<12}: {self._id}\n"
               f"{'pnl':<12}: {pnl:.2f} USD\n"
               f"{'pnl(%)':<12}: {pnl_percentage:.4f}%\n"
               f"{'trade wallet bal':<12}: {self.trade_bot_balance:.2f} USD\n"
               f"{'fee':<12}: {fee:.4f} {asset.upper()}; {fee_in_usdt:.4f} USD\n"
               f"==============================\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)
        wallet.end_trade(pnl, self.dora_trade_transaction)
        ee.emit(Trade.STOP_TRADE, self._id)

    def stats_requested(self, chat_id):
        msg = (f"???? DCA BOT STATS\n"
               f"=======================\n"
               f"{'_id':<15}: {self._id} \n"
               f"{'divergence':<15}: {self.divergence} \n"
               f"{'Entry price':<15}: {self.entry_price} USD\n"
               f"{'Coin amount':<15}: {self.coin_amount} \n"
               f"{'Trade bot bal':<15}: {self.trade_bot_balance:.3f} USD\n"
               f"=======================\n")
        telegram_bot.send_message(chat_id=chat_id, message=msg)

    def open_short_position(self, current_price, collateral_amount):
        borrowed_coin_amount = math.floor(collateral_amount / current_price)
        collateral_amount = borrowed_coin_amount * current_price

        self.avg_buyin_price = (self.stables_amt_in_short + collateral_amount) / (
                self.owed_coin_amount + borrowed_coin_amount)

        self.trade_bot_balance -= collateral_amount
        self.owed_coin_amount += borrowed_coin_amount
        self.stables_amt_in_short += collateral_amount
        self.full_owed_coin_amount = self.owed_coin_amount
        self.full_stables_amt_in_short += collateral_amount

        if not IS_PAPER_TRADING:
            order_id = str(uuid4())
            self.fee_items['order_ids'].append(order_id)
            wallet.open_short_position(quantity_in_coin=borrowed_coin_amount, order_id=order_id)

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
        coin_amount = math.floor(collateral_amount / current_price)
        collateral_amount = coin_amount * current_price
        self.avg_buyin_price = (self.stables_amt_in_long + collateral_amount) / (self.coin_amount + coin_amount)
        self.trade_bot_balance -= collateral_amount
        self.coin_amount += coin_amount
        self.stables_amt_in_long += collateral_amount
        self.full_coin_amount = self.coin_amount
        self.full_stables_amt_in_long = self.stables_amt_in_long

        if not IS_PAPER_TRADING:
            order_id = str(uuid4())
            self.fee_items['order_ids'].append(order_id)
            wallet.open_long_position(quantity_in_coin=coin_amount, order_id=order_id)

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
            order_id = str(uuid4())
            self.fee_items['order_ids'].append(order_id)
            wallet.close_short_position(position_amt=coin_amount_to_rebuy, order_id=order_id)

        msg = (f"{self.date} SHORT CLOSED (% of position: {percentage_of_position}%)\n"
               f"--------------------------\n"
               f"{'_id':<15}: {self._id}\n"
               f"{'Price':<15}: {current_price:.4f} USD\n"
               f"{'USD Bal':<15}: {self.trade_bot_balance:.2f} USD\n"
               f"{'Coin':<15}: {self.coin_amount:.4f}\n"
               f"{'Borrowed':<15}: {self.owed_coin_amount:.2f}\n"
               f"{'Amt To rebuy':<15}: {coin_amount_to_rebuy:.2f} ({amount_of_coin_to_rebuy_in_usdt:.2f} USD)\n"
               f"{'Entry price':<15}: {self.entry_price} USD\n"
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
            order_id = str(uuid4())
            self.fee_items['order_ids'].append(order_id)
            wallet.close_long_position(position_amt=coin_amount_to_sell, order_id=order_id)

        msg = (f"{self.date} LONG CLOSED (% of position: {percentage_of_position}%)\n"
               f"----------------------------\n"
               f"{'_id':<15}: {self._id}\n"
               f"{'Price':<15}: {current_price:.4f} USD\n"
               f"{'USD Bal':<15}: {self.trade_bot_balance:.2f} USD\n"
               f"{'Coin':<15}: {self.coin_amount:.4f}\n"
               f"{'Borrowed':<15}: {self.owed_coin_amount:.2f}\n"
               f"{'stables_amt_in_long':<15}: {value_to_close_in_stables:.2f}\n"
               f"{'Amt To sell':<15}: {coin_amount_to_sell:.2f} ({amount_of_coin_to_sell_in_usdt:.2f} USD)\n"
               f"{'PNL':<15}: {pnl:.4f} USD\n"
               f"{'Entry price':<15}: {self.entry_price} USD\n"
               f"----------------------------\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)

    def calc_fee(self) -> ICalcFee:
        """
        :returns: asset=token name; fee=sum of asset; asset_price=price of token in USDT
        """
        if IS_PAPER_TRADING:
            return {'asset': 'usdt', 'fee': 0.0, 'fee_in_usdt': 0.0}

        trade_start_time = self.fee_items['trade_start_time']
        retry_limit = 3
        while True:
            trades = exchange.get_account_trade_list(trade_start_time)
            if len(trades) == 0:
                retry_limit -= 1
            if retry_limit <= 0 or len(trades):
                break
            sleep(5)
        order_ids = self.fee_items['order_ids']

        def get_by_order_id(trade: IAccountTrade) -> bool:
            return trade['orderId'] in order_ids

        def sum_fees(acc: float, trade: IAccountTrade) -> float:
            return acc + trade['commission']

        asset = trades[0]['commissionAsset'] if len(trades) else 'None'
        fee: float = reduce(sum_fees, filter(get_by_order_id, trades), .0)
        fee_in_usdt = fee
        if asset and 'usdt' not in asset.lower():
            mark_price_obj = exchange.get_mark_price(f'{asset}usdt')
            fee_in_usdt = mark_price_obj['markPrice'] * fee
        return {'asset': asset, 'fee': fee, 'fee_in_usdt': fee_in_usdt}

    def remove_all_listeners(self):
        try:
            if TelegramEventType.STATS in ee._events and self.stats_requested in ee._events[TelegramEventType.STATS]:
                ee.remove_listener(TelegramEventType.STATS, self.stats_requested)
            if EExchange.CANDLESTICK_EVENT in ee._events and self.on_candlestick_event in ee._events[
                EExchange.CANDLESTICK_EVENT]:
                ee.remove_listener(EExchange.CANDLESTICK_EVENT, self.on_candlestick_event)
            if Trade.COMPLETE_CANDLESTICK_EVENT in ee._events and self.on_complete_candlestick_event in ee._events[
                Trade.COMPLETE_CANDLESTICK_EVENT]:
                ee.remove_listener(Trade.COMPLETE_CANDLESTICK_EVENT, self.on_complete_candlestick_event)
        except Exception as ex:
            logger.error(f"remove_all_listeners() failed...\n"
                         f"{ex}")

    def __repr__(self):
        return self._id

    def __del__(self):
        logger.info(f"dca_bot {self._id} deleted")


async def main():
    telegram_bot.start_bot()
    DcaBot(f"A0001", divergence="bearish", date=datetime.now())


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(main())
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
