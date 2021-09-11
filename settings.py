from os.path import dirname, abspath
from binance_f.model.constant import CandlestickInterval
from custom_types.controller_type import EMode
from custom_types.exchange_type import EToken

MODE = EMode.TEST
TELEGRAM_MODE = EMode.TEST
EXCHANGE_MODE = EMode.TEST
IS_PAPER_TRADING = True
SYMBOL = EToken.MATIC_USDT
INTERVAL = CandlestickInterval.MIN1
MAX_CONCURRENT_TRADE = 1
TRADE_LEVERAGE = 5

# MODE = EMode.PRODUCTION
# TELEGRAM_MODE = EMode.PRODUCTION
# EXCHANGE_MODE = EMode.PRODUCTION
# IS_PAPER_TRADING = True
# SYMBOL = EToken.MATIC_USDT
# INTERVAL = CandlestickInterval.MIN1
# MAX_CONCURRENT_TRADE = 1
# TRADE_LEVERAGE = 5

BASE_DIR = dirname(abspath(__file__))