"""Signal bot class"""
import os
from typing import List

from binance_f.model import IncomeType
from dotenv import load_dotenv

from Binance_futures_python.binance_f import RequestClient
from Binance_futures_python.binance_f.exception.binanceapiexception import BinanceApiException
from Binance_futures_python.binance_f.model.constant import SubscribeMessageType, CandlestickInterval, OrderType, \
    OrderSide, PositionSide, WorkingType
from Binance_futures_python.binance_f.subscriptionclient import SubscriptionClient
from classes.singleton import Singleton
from custom_types.controller_type import EMode
from custom_types.exchange_type import ICandlestick, IPostOrder, IAggregateTradeEvent, IPosition, \
    IBalance, ICandlestickEvent, ICancelAllOrders, IOrder, IMarkPrice, IAccountTrade
from settings import SYMBOL, INTERVAL, EXCHANGE_MODE
from utils.events import ee, EExchange

load_dotenv()
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')


class Exchange(metaclass=Singleton):
    """Get user position and token prices from Binance"""

    def __init__(self, api_key, secret_key):
        self.req_client = RequestClient(api_key=api_key, secret_key=secret_key)
        if EXCHANGE_MODE == EMode.PRODUCTION:
            self.sub_client = SubscriptionClient(api_key=api_key, secret_key=secret_key)
            self.sub_client.subscribe_aggregate_trade_event(SYMBOL, Exchange.on_aggregate_trade_event,
                                                            Exchange.error)
            self.sub_client.subscribe_candlestick_event(SYMBOL, CandlestickInterval.MIN5,
                                                        Exchange.on_candlestick_event, Exchange.error)

    def get_candlestick(self, interval=CandlestickInterval.MIN1,
                        start_time=None,
                        end_time=None,
                        limit=10,
                        symbol=SYMBOL) -> List[ICandlestick]:
        """Return a list of dictionary of type ICandlestick"""
        result = self.req_client.get_candlestick_data(symbol=symbol, interval=interval, startTime=start_time,
                                                      endTime=end_time, limit=limit)
        return Exchange.parse_obj_list_to_dict_list(result)

    def get_position(self) -> List[IPosition]:
        """Return a list of dictionary of type IPosition"""
        result = self.req_client.get_position_v2()
        return Exchange.parse_obj_list_to_dict_list(result)

    def get_balance(self) -> List[IBalance]:
        """Return a list of dictionary of type IBalance"""
        result = self.req_client.get_balance_v2()
        return Exchange.parse_obj_list_to_dict_list(result)

    def get_order(self, order_id: int) -> IOrder:
        """Return a dictionary of type IOrder"""
        result = self.req_client.get_order(symbol=SYMBOL, orderId=order_id)
        return Exchange.parse_obj_to_dict(result)

    def get_open_orders(self) -> List[IOrder]:
        """Return a list of dictionary of type IOrder"""
        result = self.req_client.get_open_orders(symbol=SYMBOL)
        return Exchange.parse_obj_list_to_dict_list(result)

    def cancel_order(self, order_id: int) -> IOrder:
        """Return a dictionary of type IOrder"""
        result = self.req_client.cancel_order(symbol=SYMBOL, orderId=order_id)
        return Exchange.parse_obj_to_dict(result)

    def cancel_all_orders(self) -> ICancelAllOrders:
        """Return a dictionary of type ICancelAllOrders"""
        result = self.req_client.cancel_all_orders(symbol=SYMBOL)
        return Exchange.parse_obj_to_dict(result)

    def post_order(self, side: OrderSide, position_side: PositionSide, order_type: OrderType, quantity: str = None,
                   price: float = None, stop_price: float = None, close_position: bool = None,
                   activation_price: float = None, callback_rate: float = None,
                   working_type: WorkingType = WorkingType.MARK_PRICE, order_id: str = None) -> IPostOrder:
        """
        Return a dictionary of type IPostOrder
        :param side: OrderSide.BUY/SELL/BOTH/INVALID
        :param position_side: str; PositionSide.LONG/SHORT/BOTH/INVALID
        :param order_type: OrderType.LIMIT/MARKET/STOP/STOP_MARKET/TAKE_PROFIT/TAKE_PROFIT_MARKET/TRAILING_STOP_MARKET/INVALID
        :param quantity: float; Cannot be sent with closePosition=True
        :param price: float;
        :param stop_price: float; Used with OrderType.STOP/STOP_MARKET or OrderType.TAKE_PROFIT/TAKE_PROFIT_MARKET orders
        :param close_position: bool; Close all positions. Used with OrderType.STOP_MARKET/TAKE_PROFIT_MARKET
        :param activation_price: float;
        :param callback_rate: float;
        :param working_type: stopPrice triggered by: WorkingType.MARK_PRICE/CONTRACT_PRICE/INVALID
        """
        result = self.req_client.post_order(symbol=SYMBOL, side=side, positionSide=position_side,
                                            ordertype=order_type, quantity=quantity, price=price, stopPrice=stop_price,
                                            closePosition=close_position, activationPrice=activation_price,
                                            callbackRate=callback_rate, workingType=working_type,
                                            newClientOrderId=order_id)
        return Exchange.parse_obj_to_dict(result)

    def get_income_history(self,
                           incomeType: IncomeType = None,
                           startTime: int = None,
                           endTime: int = None,
                           limit: int = None,
                           symbol=SYMBOL):
        result = self.req_client.get_income_history(symbol=symbol, incomeType=incomeType,
                                                    startTime=startTime, endTime=endTime, limit=limit)
        return (result)

    def get_account_trade_list(self, start_time: int = None, end_time: int = None) -> List[IAccountTrade]:
        result = self.req_client.get_account_trades(symbol=SYMBOL, startTime=start_time, endTime=end_time)
        return Exchange.parse_obj_list_to_dict_list(result)

    def get_mark_price(self, symbol) -> IMarkPrice:
        result = self.req_client.get_mark_price(symbol)
        return Exchange.parse_obj_to_dict(result)

    @staticmethod
    def on_aggregate_trade_event(data_type: SubscribeMessageType, event: any):
        """Emit an event of type EExchange.TRADE_EVENT with value of type IAggregateTradeEvent"""
        if data_type == SubscribeMessageType.PAYLOAD:
            _dict: IAggregateTradeEvent = Exchange.parse_obj_to_dict(event)
            ee.emit(EExchange.TRADE_EVENT, _dict)

    @staticmethod
    def on_candlestick_event(data_type: SubscribeMessageType, event: any):
        """Emit an event of type EExchange.CANDLESTICK_EVENT with value of type ICandlestickEvent"""
        if data_type == SubscribeMessageType.PAYLOAD:
            _dict: ICandlestickEvent = Exchange.parse_obj_to_dict(event)
            ee.emit(EExchange.CANDLESTICK_EVENT, _dict)

    @staticmethod
    def error(e: BinanceApiException):
        print(e.error_code + e.error_message)

    @staticmethod
    def parse_obj_list_to_dict_list(obj_list):
        _list = []
        for obj in obj_list:
            _dict = Exchange.parse_obj_to_dict(obj)
            _list.append(_dict)
        return _list

    @staticmethod
    def parse_obj_to_dict(obj):
        _dict = {}
        members = [attr for attr in dir(obj) if not callable(attr) and not attr.startswith("__")]
        for member in members:
            val = getattr(obj, member)
            if isinstance(val, list):
                _dict[member] = Exchange.parse_obj_list_to_dict_list(val)
            elif 'binance' in val.__class__.__module__:
                _dict[member] = Exchange.parse_obj_to_dict(val)
            else:
                _dict[member] = val
        return _dict


exchange = Exchange(API_KEY, SECRET_KEY)

if __name__ == '__main__':
    print(exchange.get_candlestick())
