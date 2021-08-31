import asyncio
import logging
from datetime import datetime

from binance_f.model import CandlestickInterval
from typing import List

from sqlalchemy import Column, desc, Integer, String, DateTime, Numeric, Sequence
from sqlalchemy.future import select
from sqlalchemy.orm import Query

from classes.singleton import Singleton
from custom_types.exchange_type import EToken
from database.base import Base
from utils.dal_utils import DALUtils


class DoraTradeTransaction(Base):
    __tablename__ = 'dora_trade_transaction'

    dora_txn_seqno = Column(Integer, Sequence('dora_trade_transaction_seq'), nullable=False, primary_key=True)
    _id = Column(String, nullable=False, default=EToken.MATIC_USDT)
    symbol = Column(String, nullable=False, default=EToken.MATIC_USDT)
    start_time = Column(DateTime(timezone=False), nullable=False)
    end_time = Column(DateTime(timezone=False), nullable=False)
    pnl = Column(Numeric(32, 8), nullable=True)
    overall_fund = Column(Numeric(32, 8), nullable=True)
    txn_type = Column(String, nullable=True)
    txn_interval = Column(String, nullable=True)

    def __repr__(self):
        return f"{self.dora_txn_seqno=} {self._id=} {self.end_time=}"


class DoraTradeTransactionDAL(metaclass=Singleton):
    db_session = None

    def __init__(self):
        if self.db_session is None:
            self.db_session = DALUtils().session

    def get_single_obj(self, _id, symbol) -> DoraTradeTransaction:
        query: Query = self.db_session.query(DoraTradeTransaction).filter(DoraTradeTransaction._id == _id,
                                                                          DoraTradeTransaction.symbol == symbol)
        return query.first()

    async def get_last_signal_status(self) -> List[DoraTradeTransaction]:
        q = await self.db_session.execute(select(DoraTradeTransaction).order_by(desc(DoraTradeTransaction.updated_at)))
        return q.scalars().first()

    def create(self, dora_trade_transaction: DoraTradeTransaction):
        ret = self.db_session.add(dora_trade_transaction)
        self.db_session.commit()

    def update_signal_status(self, dora_trade_transaction: DoraTradeTransaction):
        # q = update(DoraTradeTransaction).where(DoraTradeTransaction.pt_seqno == dora_trade_transaction.pt_seqno)
        self.db_session.add(dora_trade_transaction)
        self.db_session.commit()


async def main():
    dora_trade_transaction = DoraTradeTransaction(_id="A0001",
                                                  symbol=EToken.MATIC_USDT,
                                                  start_time=datetime.now(),
                                                  end_time=datetime.now(),
                                                  pnl=1.12,
                                                  overall_fund=1000.1,
                                                  txn_type="",
                                                  txn_interval=CandlestickInterval.MIN5,
                                                  created_at=datetime.now(),
                                                  updated_at=datetime.now()
                                                  )
    trade_txn_dal: DoraTradeTransactionDAL = DoraTradeTransactionDAL()
    print("inserting")
    trade_txn_dal.create(dora_trade_transaction)

    # obj: DoraTradeTransaction = (trade_txn_dal.get_single_obj(pt_symbol=EToken.BTC_USDT, pt_type="trough"))
    # obj.ohlc_open = 2.01
    # pt_dal.update_signal_status(obj)

    # print(json.dumps(obj))
    # print(obj.__dict__)

    print("done")


if __name__ == '__main__':
    logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
