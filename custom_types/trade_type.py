from typing import TypedDict, Optional, List, Union


class IExtendedTrade(TypedDict):
    fib_9_hit: bool
    fib_9_hit_time: int
    new_fib_2_hit: bool
    inverted: bool
    fib: Optional[List[int]]
    sl_fib: Union[int, str]


class IFeeCalc(TypedDict):
    trade_start_time: int
    order_ids: List[str]


class ICalcFee(TypedDict):
    asset: str
    fee: float
    fee_in_usdt: float
