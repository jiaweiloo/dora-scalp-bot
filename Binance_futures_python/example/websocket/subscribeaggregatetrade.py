import logging
from binance_f import SubscriptionClient
from binance_f.constant.test import *
from binance_f.model import *
from binance_f.exception.binanceapiexception import BinanceApiException

from binance_f.base.printobject import *

logger = logging.getLogger("binance-client")
logger.setLevel(level=logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

sub_client = SubscriptionClient(api_key=g_api_key, secret_key=g_secret_key)


def callback(data_type: 'SubscribeMessageType', event: 'any'):
    if data_type == SubscribeMessageType.RESPONSE:
        print("Event ID: ", event)
    elif  data_type == SubscribeMessageType.PAYLOAD:
        PrintBasic.print_obj(event)
        # sub_client.unsubscribe_all()
    else:
        print("Unknown Data:")
    print()


def error(e: 'BinanceApiException'):
    print(e.error_code + e.error_message)

sub_client.subscribe_aggregate_trade_event("btcusdt", callback, error)