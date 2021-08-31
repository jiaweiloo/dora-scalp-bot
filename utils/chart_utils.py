import csv
import os
from os.path import join, dirname, basename, splitext

import mplfinance as mpf
import pandas as pd

from binance_f.model.constant import CandlestickInterval

CANDLESTICK_INTERVAL_MAP = {
    CandlestickInterval.MIN1: 60,
    CandlestickInterval.MIN3: 180,
    CandlestickInterval.MIN5: 300,
    CandlestickInterval.MIN15: 900,
    CandlestickInterval.MIN30: 1800,
    CandlestickInterval.HOUR1: 3600,
    CandlestickInterval.HOUR2: 7200,
    CandlestickInterval.HOUR4: 14400,
    CandlestickInterval.HOUR6: 21600,
    CandlestickInterval.HOUR8: 28800,
    CandlestickInterval.HOUR12: 43200,
    CandlestickInterval.DAY1: 86400,
    CandlestickInterval.DAY3: 259200,
    CandlestickInterval.WEEK1: 604800,
}


def split_full_path(full_path: str) -> (str, str, str):
    filename, ext = splitext(basename(full_path.rstrip(os.sep)))
    return dirname(full_path), filename, ext


def aggregate_chart_time(full_path: str, interval: CandlestickInterval, reverse=False) -> str:
    df = pd.read_csv(full_path, sep=',')
    if reverse:
        df = df[::-1].reset_index(drop=True)  # Reverse dataframe

    prev_time_in_ms, date = 0, ''
    _open, high, low, close = 0, 0, 0, 0
    interval_in_ms = CANDLESTICK_INTERVAL_MAP[interval] * (10 ** 3)

    dirpath, filename, ext = split_full_path(full_path)
    new_path = join(dirpath, f'{filename}_{interval}{ext}')
    with open(new_path, 'w') as f:
        writer = csv.writer(f)
        writer.writerow(['unix', 'date', 'open', 'high', 'low', 'close'])

    for _, row in df.iterrows():
        time_in_ms = row['unix']
        remainder = time_in_ms % interval_in_ms

        if remainder == 0:  # We are at a new starting point
            if prev_time_in_ms != 0:
                with open(new_path, 'a') as f:
                    writer = csv.writer(f)
                    writer.writerow([prev_time_in_ms, date, _open, high, low, close])
            high, low = 0, 0
            prev_time_in_ms = row['unix']
            date = row['date']
            _open = row['open']
        if row['high'] > high:
            high = row['high']
        if row['low'] < low or low == 0:
            low = row['low']
        close = row['close']

    with open(new_path, 'a') as f:
        writer = csv.writer(f)
        writer.writerow([prev_time_in_ms, date, _open, high, low, close])
    return new_path


def plot_from_csv(full_path: str, addplot=None, limit=None, markersize=50, marker=None) -> str:
    df = pd.read_csv(full_path, index_col=1, parse_dates=True)
    if limit:
        df = df[:limit]
    mc = mpf.make_marketcolors(base_mpf_style='binance', vcdopcod=True)
    style = mpf.make_mpf_style(base_mpf_style='binance', marketcolors=mc)
    dirpath, _, _ = split_full_path(full_path)
    save_path = join(dirpath, 'plot.jpg')

    apds = []
    if addplot and isinstance(addplot, list):
        if isinstance(addplot[0], list):
            for idx, _addplot in enumerate(addplot):
                apds.append(mpf.make_addplot(_addplot, type='scatter', markersize=markersize, marker=marker[idx]))
        else:
            apds.append(mpf.make_addplot(addplot, type='scatter', markersize=markersize, marker=marker))
    mpf.plot(df, type='candle', style=style, figratio=(18, 10), addplot=apds, savefig=save_path)
    return save_path


if __name__ == '__main__':
    path = join(os.getcwd(), '../assets/Binance_MATICUSDT_minute_live.csv')
    new_path = aggregate_chart_time(path, CandlestickInterval.MIN1)
    plot_from_csv(new_path)
