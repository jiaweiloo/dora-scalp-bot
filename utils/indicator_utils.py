from typing import List

from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import volume_weighted_average_price

from classes.ohlc import Ohlc
import pandas as pd

from service.logging import indicator_util_logger as logger


def get_bollinger_band(data: List[Ohlc], data_len, window=20):
    """Calculate RSI from a pandas Series and return the latest RSI"""
    close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
    indicator_bb = BollingerBands(close=close_price_list, window=window, window_dev=2)

    # Add Bollinger Bands features
    mavg_list = indicator_bb.bollinger_mavg()
    hband_list = indicator_bb.bollinger_hband()
    lband_list = indicator_bb.bollinger_lband()
    bb_result = {'mavg': mavg_list.iloc[-1], 'hband': hband_list.iloc[-1], 'lband': lband_list.iloc[-1]}
    return bb_result


def get_avg_true_range(data: List[Ohlc], data_len, window=14):
    """Calculate ATR from a pandas Series and return the latest ATR"""
    close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
    high_price_list = pd.Series([obj.high for obj in data[-data_len:]])
    low_price_list = pd.Series([obj.low for obj in data[-data_len:]])
    atr = AverageTrueRange(high=high_price_list,
                           low=low_price_list,
                           close=close_price_list,
                           window=window)
    atr_list = atr.average_true_range()
    return atr_list.iloc[-1]


def get_vwap(data: List[Ohlc], data_len, window=14):
    high_price_list = pd.Series([obj.high for obj in data[-data_len:]])
    low_price_list = pd.Series([obj.low for obj in data[-data_len:]])
    close_price_list = pd.Series([obj.close for obj in data[-data_len:]])
    quoteAssetVolume_list = pd.Series([obj.quoteAssetVolume for obj in data[-data_len:]])
    # volume_list = pd.Series([obj.volume_usdt for obj in data[-data_len:]])
    # vol = volume_list * close_price_list
    vwap_list = volume_weighted_average_price(high=high_price_list, low=low_price_list, close=close_price_list,
                                              volume=quoteAssetVolume_list,
                                              window=window, fillna=True)
    # logger.info(f"quote: {quoteAssetVolume_list.iloc[-1]:.5f} vol:{volume_list.iloc[-1]:.5f} q*vol:{vol.iloc[-1]:.5f}")
    return vwap_list.iloc[-1]
