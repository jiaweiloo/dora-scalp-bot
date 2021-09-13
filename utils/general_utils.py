import codecs
from datetime import datetime

from database.dora_trade_transaction import DoraTradeTransaction
from settings import BASE_DIR
from utils.path_utils import build_path


def time_now_in_ms():
    return int(datetime.now().timestamp() * (10 ** 3))


def init_backtest_file():
    filename = f"backtest_result"
    write_file_path = build_path([BASE_DIR, 'assets', f'{filename}.csv'])
    with codecs.open(write_file_path, 'w', 'utf-8') as f:
        f.write('dora_txn_seqno,_id,symbol,start_time,end_time,pnl,overall_fund,txn_type,txn_interval\n')


def write_to_csv(txn: DoraTradeTransaction):
    filename = f"backtest_result"
    write_file_path = build_path([BASE_DIR, 'assets', f'{filename}.csv'])
    with codecs.open(write_file_path, 'a', 'utf-8') as f:
        line = f"{txn.dora_txn_seqno},{txn._id},{txn.symbol},{txn.start_time},{txn.end_time},{txn.pnl}," \
               f"{txn.overall_fund},{txn.txn_type},{txn.txn_interval}"
        f.write(line)
        f.write('\n')

