import asyncio
import logging
from datetime import datetime

from binance_f.model import CandlestickInterval
from typing import List, Optional

from pydantic.main import BaseModel
from sqlalchemy import Column, desc, Integer, String, DateTime, Numeric, Sequence, update
from sqlalchemy.future import select
from sqlalchemy.orm import Query

from classes.singleton import Singleton
from custom_types.controller_type import EMode
from custom_types.exchange_type import EToken
from database.base import Base
from utils.dal_utils import DALUtils
from utils.json_utils import parse_obj_to_dict


class DoraBotSettingsModel(BaseModel):
    dora_setting_seqno: Optional[int] = None
    active_mode: Optional[str] = EMode.PRODUCTION
    is_paper_trading: Optional[str] = 'Y'
    active_interval: Optional[str] = CandlestickInterval.MIN1
    active_symbol: Optional[str] = EToken.MATIC_USDT
    active_telegram_id: Optional[str] = '-1001433775775'
    base_order_size: float
    max_safety_order_count: int
    target_profit_percentage: float
    price_deviation_trigger_so: float

    created_at: datetime
    updated_at: datetime


class DoraBotSettings(Base):
    __tablename__ = 'dora_bot_settings'
    dora_setting_seqno = Column(Integer, Sequence('dora_setting_seq'), nullable=False, primary_key=True)
    active_mode = Column(String, nullable=False, default=EMode.PRODUCTION)
    is_paper_trading = Column(String, nullable=False, default='Y')
    active_interval = Column(String, nullable=False, default=CandlestickInterval.MIN1)
    active_symbol = Column(String, nullable=False, default=EToken.MATIC_USDT)
    active_telegram_id = Column(String, nullable=False, default='-1001433775775')
    base_order_size = Column(Numeric(32, 8), nullable=True)
    max_safety_order_count = Column(Integer, nullable=False)
    target_profit_percentage = Column(Numeric(32, 8), nullable=True)
    price_deviation_trigger_so = Column(Numeric(32, 8), nullable=True)

    def __repr__(self):
        return f"{self.dora_setting_seqno=} {self.active_mode=} {self.active_symbol=} {self.is_paper_trading=}"


class DoraBotSettingsDAL(metaclass=Singleton):
    db_session = None

    def __init__(self):
        if self.db_session is None:
            self.db_session = DALUtils().session

    def get_single_obj(self, dora_setting_seqno) -> DoraBotSettings:
        query: Query = self.db_session.query(DoraBotSettings).filter(
            DoraBotSettings.dora_setting_seqno == dora_setting_seqno)
        return query.first()

    async def get_last_signal_status(self) -> List[DoraBotSettings]:
        q = await self.db_session.execute(select(DoraBotSettings).order_by(desc(DoraBotSettings.updated_at)))
        return q.scalars().first()

    def create(self, dora_trade_transaction: DoraBotSettings):
        ret = self.db_session.add(dora_trade_transaction)
        self.db_session.commit()

    def update_obj(self, dbt: DoraBotSettings):
        ret = self.db_session.add(dbt)
        self.db_session.commit()

        # dbt_dict = parse_obj_to_dict(dbt)
        # q = update(DoraBotSettings).where(DoraBotSettings.dora_setting_seqno == dbt.dora_setting_seqno).values(**dbt_dict)
        #
        # # self.db_session.
        # # self.db_session.add(dora_trade_transaction)
        # print(q)
        # return q


async def main():
    dora_trade_transaction = DoraBotSettings(active_mode=EMode.PRODUCTION,
                                             is_paper_trading='Y',
                                             active_interval=CandlestickInterval.MIN1,
                                             active_symbol=EToken.MATIC_USDT,
                                             active_telegram_id='-1001433775775',
                                             base_order_size=0,
                                             max_safety_order_count=4,
                                             target_profit_percentage=0.0075,
                                             price_deviation_trigger_so=0.01,
                                             created_at=datetime.now(),
                                             updated_at=datetime.now())
    trade_txn_dal: DoraBotSettingsDAL = DoraBotSettingsDAL()
    print("inserting")
    # trade_txn_dal.create(dora_trade_transaction)

    obj: DoraBotSettings = (trade_txn_dal.get_single_obj(dora_setting_seqno=1))
    # obj.ohlc_open = 2.01
    # pt_dal.update_signal_status(obj)

    # print(json.dumps(obj))
    print(obj.__dict__)

    print("done")


if __name__ == '__main__':
    logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
