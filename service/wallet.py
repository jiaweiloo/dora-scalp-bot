import time
from datetime import datetime
from typing import List

from binance_f.model import OrderSide, PositionSide, OrderType, WorkingType

from classes.singleton import Singleton
from custom_types.controller_type import EMode
from custom_types.exchange_type import IPosition, IBalance, EToken, EWalletToken
from database.dora_trade_transaction import DoraTradeTransaction, DoraTradeTransactionDAL
from service.exchange import exchange
from service.logging import wallet_logger as logger
from service.telegram_bot import telegram_bot
from settings import IS_PAPER_TRADING, SYMBOL, MODE, MAX_CONCURRENT_TRADE, TRADE_LEVERAGE
from utils.events import ee, TelegramEventType
from utils.general_utils import write_to_csv


def first(iterable, default=None):
    for item in iterable:
        return item
    return default


class Wallet(metaclass=Singleton):
    overall_wallet_fund = 1000
    starting_amount = 0
    tradeable_amount = 0

    cumulative_pnl = 0
    pnl_percentage = 0
    total_completed_trade = 0
    active_trade = 0
    winning_trade = 0
    losing_trade = 0

    total_winning_usdt = 0
    total_losing_usdt = 0
    total_losing_pct = 0

    max_continuous_losing = 0
    max_continuous_losing_overall = 0

    def __init__(self):
        if not IS_PAPER_TRADING:
            usdt_ibalance_object = self.get_usdt_bal()
            self.overall_wallet_fund = usdt_ibalance_object['availableBalance']
        self.starting_amount = self.overall_wallet_fund
        self.tradeable_amount = self.starting_amount / MAX_CONCURRENT_TRADE
        ee.on(TelegramEventType.STATS, self.stats_requested)

    def get_start_amount(self):
        if self.active_trade == 0:
            if not IS_PAPER_TRADING:
                usdt_ibalance_object = self.get_usdt_bal()
                self.overall_wallet_fund = usdt_ibalance_object['availableBalance']
            self.tradeable_amount = self.overall_wallet_fund / MAX_CONCURRENT_TRADE
        self.active_trade += 1
        return self.tradeable_amount

    def end_trade(self, pnl, dora_trade_transaction: DoraTradeTransaction):
        if self.active_trade == 0:
            logger.error("There is no active trade to end")
            return

        final_pnl = TRADE_LEVERAGE * pnl
        if MODE == EMode.TEST:
            temp_fees = self.overall_wallet_fund * 0.002
            final_pnl = final_pnl - temp_fees
        logger.info(f"ori pnl {pnl:.4f} * {TRADE_LEVERAGE} = {final_pnl:.4f}")
        self.active_trade -= 1
        self.overall_wallet_fund += final_pnl
        self.cumulative_pnl += final_pnl

        if self.active_trade == 0 and not IS_PAPER_TRADING:
            usdt_ibalance_object = self.get_usdt_bal()
            self.overall_wallet_fund = usdt_ibalance_object['availableBalance']
            self.cumulative_pnl = self.overall_wallet_fund - self.starting_amount

        prev_percentage = self.pnl_percentage
        self.pnl_percentage = self.cumulative_pnl / self.starting_amount * 100
        self.total_completed_trade += 1
        if final_pnl >= 0:
            self.winning_trade += 1
            self.max_continuous_losing = 0
            self.total_winning_usdt += final_pnl
        else:
            self.losing_trade += 1
            self.total_losing_usdt += final_pnl
            self.total_losing_pct += (prev_percentage - self.pnl_percentage)
            self.max_continuous_losing += 1
            if self.max_continuous_losing > self.max_continuous_losing_overall:
                self.max_continuous_losing_overall = self.max_continuous_losing

        if dora_trade_transaction.end_time is None:
            dora_trade_transaction.end_time = datetime.now()

        if self.losing_trade > 0:
            winning_p_trade = self.total_winning_usdt / self.total_completed_trade
            losing_p_trade = self.total_losing_usdt / self.total_completed_trade
        else:
            winning_p_trade = 0
            losing_p_trade = 0

        msg = (f"END OF TRANSACTION REPORT\n"
               f"===========================\n"
               f"{'date':<14}: {dora_trade_transaction.end_time:%Y-%m-%d %H:%M:%S}\n"
               f"{'cumulative pnl':<14}: {self.cumulative_pnl:.4f} USD\n"
               f"{'overall fund':<14}: {self.overall_wallet_fund:.4f} USD\n"
               f"{'overall pnl(%)':<14}: {self.pnl_percentage:.4f}%\n"
               f"{'total completed trade':<14}: {self.total_completed_trade}\n"
               f"{'total winning usdt':<14}: {self.total_winning_usdt:.4f} USD\n"
               f"{'total losing trade':<14}: {self.losing_trade}\n"
               f"{'total losing usdt':<14}: {self.total_losing_usdt:.4f} USD\n"
               f"{'total losing (%)':<14}: -{self.total_losing_pct:.4f} %\n"
               f"{'cont. losing streak':<14}: {self.max_continuous_losing_overall}\n"
               f"{'avg trade':<14}: {winning_p_trade - losing_p_trade :.4f} USDT\n"
               f"{'leverage':<14}: {TRADE_LEVERAGE}\n"
               f"===========================\n")
        logger.info(msg)
        telegram_bot.send_message(message=msg)
        dora_trade_transaction.pnl = final_pnl
        dora_trade_transaction.overall_fund = self.overall_wallet_fund
        if MODE == EMode.TEST:
            write_to_csv(dora_trade_transaction)
        self.save_txn_to_db(dora_trade_transaction)

    def get_active_trade(self):
        return self.active_trade

    def save_txn_to_db(self, dora_trade_transaction: DoraTradeTransaction):
        if MODE == EMode.TEST or IS_PAPER_TRADING:
            return
        dora_trade_transaction.end_time = datetime.now()
        dora_trade_transaction.created_at = datetime.now()
        dora_trade_transaction.updated_at = datetime.now()
        trade_txn_dal: DoraTradeTransactionDAL = DoraTradeTransactionDAL()
        trade_txn_dal.create(dora_trade_transaction)

    def get_usdt_bal(self):
        retry = 0
        bal_list = []
        while True and retry <= 3:
            try:
                bal_list: List[IBalance] = exchange.get_balance()
            except Exception as ex:
                logger.error(f"get_usdt_bal() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break
        balance: IBalance = first(x for x in bal_list if x['asset'].upper() == 'USDT')
        return balance

    def get_position(self, position_side) -> IPosition:
        retry = 0
        pos_list = []
        while True and retry <= 3:
            try:
                pos_list: List[IPosition] = exchange.get_position()
            except Exception as ex:
                logger.error(f"get_position() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break
        position: IPosition = first(x for x in pos_list if (x['symbol'].lower() == SYMBOL and
                                                            x['positionSide'] == position_side))
        return position

    def get_bal_by_symbol(self, symbol=EWalletToken.USDT):
        retry = 0
        bal_list = []
        while True and retry <= 3:
            try:
                bal_list: List[IBalance] = exchange.get_balance()
                print(bal_list)
            except Exception as ex:
                logger.error(f"get_bal_by_symbol() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break
        balance: IBalance = first(x for x in bal_list if x['asset'].upper() == symbol)
        return balance

    def open_long_position(self, quantity_in_coin: float, order_id: str = None):
        retry = 0
        quantity_in_coin = TRADE_LEVERAGE * quantity_in_coin
        print(f"open_long_position {quantity_in_coin:.3f}")
        while True and retry <= 3:
            try:
                exchange.post_order(side=OrderSide.BUY, position_side=PositionSide.LONG,
                                    order_type=OrderType.MARKET, quantity=f"{quantity_in_coin:.0f}", price=None,
                                    stop_price=None, close_position=None, activation_price=None,
                                    callback_rate=None, working_type=WorkingType.MARK_PRICE, order_id=order_id)
            except Exception as ex:
                logger.error(f"open_long_position() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break

    def close_long_position(self, position_amt: float, order_id: str = None):
        position_amt = TRADE_LEVERAGE * position_amt
        print(f"close_long_pos {position_amt:.3f}")
        retry = 0
        while True and retry <= 3:
            try:
                exchange.post_order(side=OrderSide.SELL, position_side=PositionSide.LONG, order_type=OrderType.MARKET,
                                    quantity=f"{position_amt:.3f}", price=None, stop_price=None, close_position=None,
                                    activation_price=None, callback_rate=None, working_type=WorkingType.MARK_PRICE,
                                    order_id=order_id)
            except Exception as ex:
                logger.error(f"close_long_position() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break

    def open_short_position(self, quantity_in_coin: float, order_id: str = None):
        quantity_in_coin = TRADE_LEVERAGE * quantity_in_coin
        print(f"open_short_position {quantity_in_coin:.3f}")
        retry = 0
        while True and retry <= 3:
            try:
                exchange.post_order(side=OrderSide.SELL, position_side=PositionSide.SHORT, order_type=OrderType.MARKET,
                                    quantity=f"{quantity_in_coin:.3f}", price=None, stop_price=None,
                                    close_position=None, activation_price=None, callback_rate=None,
                                    working_type=WorkingType.MARK_PRICE, order_id=order_id)
            except Exception as ex:
                logger.error(f"open_short_position() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break

    def close_short_position(self, position_amt: float, order_id: str = None):
        position_amt = TRADE_LEVERAGE * position_amt
        print(f"close_short_position {position_amt:.3f}")
        retry = 0
        while True and retry <= 3:
            try:
                exchange.post_order(side=OrderSide.BUY, position_side=PositionSide.SHORT, order_type=OrderType.MARKET,
                                    quantity=f"{abs(position_amt):.3f}", price=None, stop_price=None,
                                    close_position=None, activation_price=None, callback_rate=None,
                                    working_type=WorkingType.MARK_PRICE, order_id=order_id)
            except Exception as ex:
                logger.error(f"close_short_position() failed {retry}...\n"
                             f"{ex}")
                time.sleep(2)
                retry += 1
                continue
            break

    def stats_requested(self, chat_id):
        usdt_ibalance_object = self.get_bal_by_symbol()
        bnb_bal = wallet.get_bal_by_symbol(symbol=EWalletToken.BNB)
        overall_wallet_fund = usdt_ibalance_object['availableBalance']

        msg = (f"📊 WALLET STATS\n"
               f"=======================\n"
               f"{'overall_wallet_fund':<15}: {overall_wallet_fund:.4f} USD \n"
               f"{'BNB bal':<15}: {bnb_bal['availableBalance']:.4f} BNB \n"
               f"{'cumulative pnl':<14}: {self.cumulative_pnl:.4f} USD\n"
               f"{'overall pnl(%)':<14}: {self.pnl_percentage:.4f}%\n"
               f"{'total losing trade':<14}: {self.losing_trade}\n"
               f"{'total completed trade':<14}: {self.total_completed_trade}\n"
               f"{'active trade':<14}: {self.active_trade}\n"
               f"{'leverage':<14}: {TRADE_LEVERAGE}\n"
               f"=======================\n")
        telegram_bot.send_message(chat_id=chat_id, message=msg)


wallet = Wallet()

if __name__ == '__main__':
    wallet: Wallet = Wallet()
    res = exchange.get_income_history(symbol=EToken.MATIC_USDT)
    for p in res: print(p.__dict__)
