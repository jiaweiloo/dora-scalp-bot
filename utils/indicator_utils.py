from typing import List

from ta.volatility import BollingerBands, AverageTrueRange

from classes.ohlc import Ohlc
import pandas as pd


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
