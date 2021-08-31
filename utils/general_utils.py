from datetime import datetime


def time_now_in_ms():
    return int(datetime.now().timestamp() * (10 ** 3))
