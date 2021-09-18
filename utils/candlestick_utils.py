import asyncio
import codecs
from datetime import datetime
from time import sleep

from binance_f.model.constant import CandlestickInterval

from custom_types.exchange_type import EToken
from service.exchange import exchange
from settings import BASE_DIR
from utils.path_utils import build_path

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


def interval_in_ms(interval: CandlestickInterval):
    return CANDLESTICK_INTERVAL_MAP[interval] * (10 ** 3)


def get_candlestick_start_time(timestamp_in_ms, interval: CandlestickInterval):
    return timestamp_in_ms - (timestamp_in_ms % interval_in_ms(interval))


def get_latest_incomplete_candlestick_start_time(interval: CandlestickInterval):
    return get_candlestick_start_time(time_now_in_ms(), interval)


def get_latest_complete_candlestick_start_time(interval: CandlestickInterval):
    return get_latest_incomplete_candlestick_start_time(interval) - interval_in_ms(interval)


def time_now_in_ms():
    return int(datetime.now().timestamp() * (10 ** 3))


def date_to_timestamp(date: datetime):
    return int(date.timestamp() * (10 ** 3))


def gen_candlestick_csv_data(interval: CandlestickInterval, start_date: datetime, end_date: datetime = None,
                             symbol=EToken.MATIC_USDT):
    start_timestamp = get_candlestick_start_time(date_to_timestamp(start_date), interval)
    date_fmt = '%d%b%y-%H{}%M'
    date_fmt2 = '%d-%m-%y %H:%M'

    DEFAULT_FORMAT = date_fmt2
    filename = f"{symbol}_{start_date.strftime(date_fmt).format('꞉')}"
    if end_date is not None:
        end_timestamp = get_candlestick_start_time(date_to_timestamp(end_date), interval)
        filename = f"{filename}_to_{end_date.strftime(DEFAULT_FORMAT)}"
    else:
        end_timestamp = get_latest_complete_candlestick_start_time(interval)
    write_file_path = build_path([BASE_DIR, 'assets', f'{filename}.csv'])
    with codecs.open(write_file_path, 'w', 'utf-8') as f:
        f.write('date,open,high,low,close,volume,quoteAssetVolume\n')
    limit = 1000
    while start_timestamp < end_timestamp:
        candlesticks = exchange.get_candlestick(interval, start_timestamp, end_timestamp, limit, symbol=symbol)
        with codecs.open(write_file_path, 'a', 'utf-8') as f:
            for candlestick in candlesticks:
                if candlestick['openTime'] == end_timestamp:
                    break
                formatted_date = datetime.fromtimestamp(candlestick['openTime'] / 1000).strftime(DEFAULT_FORMAT)
                line = f"{formatted_date},{candlestick['open']},{candlestick['high']},{candlestick['low']}," \
                       f"{candlestick['close']},{candlestick['volume']},{candlestick['quoteAssetVolume']}"
                f.write(line)
                f.write('\n')
        start_timestamp = candlesticks[-1]['openTime']
        if start_timestamp < end_timestamp:
            start_timestamp += interval_in_ms(interval)
        elif start_timestamp >= end_timestamp:
            break
        print(f"sleeping for 1s... {datetime.fromtimestamp(start_timestamp/1000):%Y-%m-%d %H:%M:%S}")
        sleep(1)
    print(f'done generating csv file:\n{write_file_path}')


async def main():
    gen_candlestick_csv_data(CandlestickInterval.MIN1, datetime(2021, 9, 1, 00, 0))
    print("---END---")


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(main())
        loop.run_forever()
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
