from typing import TypedDict, Callable, Optional, List

from Binance_futures_python.binance_f.model.constant import OrderType, PositionSide, OrderSide, TimeInForce, \
    WorkingType, FuturesMarginType


class ICandlestick(TypedDict):
    close: str  # float
    closeTime: int
    high: str  # float
    ignore: str  # int
    json_parse: Callable
    low: str  # float
    numTrades: int
    open: str  # float
    openTime: int
    quoteAssetVolume: str  # float
    takerBuyBaseAssetVolume: str  # float
    takerBuyQuoteAssetVolume: str  # float
    volume: str  # float
    rsi: float


class IAccountTrade(TypedDict):
    commission: float
    commissionAsset: str
    counterPartyId: None
    id: int
    isBuyer: bool
    isMaker: bool
    json_parse: Callable
    orderId: int
    price: float
    qty: float
    quoteQty: float
    realizedPnl: float
    side: OrderSide
    symbol: str
    time: int


class IMarkPrice(TypedDict):
    json_parse: Callable
    lastFundingRate: float
    markPrice: float
    nextFundingTime: int
    symbol: str
    time: int


class IPosition(TypedDict):
    symbol: str
    positionAmt: float
    entryPrice: float
    markPrice: float
    unRealizedProfit: float
    liquidationPrice: float
    leverage: float
    maxNotionalValue: float
    marginType: FuturesMarginType
    isolatedMargin: float
    isAutoAddMargin: bool
    positionSide: str  # BOTH | LONG | SHORT
    json_parse: Callable


class IBalance(TypedDict):
    accountAlias: str
    asset: str
    availableBalance: float
    balance: float
    crossUnPnl: float
    crossWalletBalance: float
    json_parse: Callable
    maxWithdrawAmount: float


class IOrder(TypedDict):
    activatePrice: Optional[float]
    avgPrice: float
    clientOrderId: str
    closePosition: bool
    cumQuote: float
    executedQty: float
    json_parse: Callable
    orderId: int
    origQty: float
    origType: OrderType
    positionSide: PositionSide
    price: float
    priceRate: Optional[float]
    reduceOnly: bool
    side: OrderSide
    status: str
    stopPrice: float
    symbol: str
    timeInForce: TimeInForce
    type: OrderType
    updateTime: int
    workingType: WorkingType


class ICancelAllOrders(TypedDict):
    code: int  # 200 if OK
    json_parse: Callable
    msg: str


class IPostOrder(TypedDict):
    activatePrice: Optional[float]
    avgPrice: float
    clientOrderId: str
    closePosition: bool
    cumQuote: float
    executedQty: float
    json_parse: Callable
    orderId: int
    origQty: float
    origType: OrderType
    positionSide: PositionSide
    price: float
    priceRate: Optional[float]
    reduceOnly: bool
    side: OrderSide
    status: str
    stopPrice: float
    symbol: str
    timeInForce: TimeInForce
    type: OrderType
    updateTime: int
    workingType: WorkingType


class IAggregateTradeEvent(TypedDict):
    eventTime: int
    eventType: str
    firstId: int
    id: int
    isBuyerMaker: bool
    json_parse: Callable
    lastId: int
    price: float
    qty: float
    symbol: str
    time: int


class ICandlestickEventData(TypedDict):
    close: float
    closeTime: int
    firstTradeId: int
    high: float
    ignore: int
    interval: str
    isClosed: bool
    json_parse: Callable
    lastTradeId: int
    low: float
    numTrades: int
    open: float
    quoteAssetVolume: float
    startTime: int
    symbol: str
    takerBuyBaseAssetVolume: float
    takerBuyQuoteAssetVolume: float
    volume: float


class ICandlestickEvent(TypedDict):
    data: ICandlestickEventData
    eventTime: int
    eventType: str
    json_parse: Callable
    symbol: str


class IUserDataAccountUpdate(TypedDict):
    activationPrice: Optional[float]
    asksNotional: float
    avgPrice: float
    bidsNotional: float
    callbackRate: Optional[float]
    clientOrderId: str
    commissionAmount: Optional[float]
    commissionAsset: Optional[float]
    cumulativeFilledQty: float
    eventTime: int
    eventType: str  # ORDER_TRADE_UPDATE
    executionType: str
    isClosePosition: bool
    isMarkerSide: bool
    isReduceOnly: bool
    json_parse: Callable
    lastFilledPrice: float
    lastFilledQty: float
    orderId: int
    orderStatus: str
    orderTradeTime: int
    origQty: float
    positionSide: PositionSide
    price: float
    side: OrderSide
    stopPrice: float
    symbol: str
    timeInForce: TimeInForce
    tradeID: int
    transactionTime: int
    type: OrderType
    workingType: WorkingType


class IUserDataBalance(TypedDict):
    asset: str
    crossWallet: float
    json_parse: Callable
    walletBalance: float


class IUserDataPosition(TypedDict):
    amount: float
    entryPrice: float
    isolatedWallet: float
    json_parse: Callable
    marginType: FuturesMarginType
    positionSide: PositionSide
    preFee: float
    symbol: str
    unrealizedPnl: float


class IUserDataOrderTradeUpdate(TypedDict):
    balances: List[IUserDataBalance]
    eventTime: int
    eventType: str  # ACCOUNT_UPDATE
    json_parse: Callable
    positions: List[IUserDataPosition]
    transactionTime: int


class EToken:
    MATIC_USDT = 'maticusdt'
    BTC_USDT = 'btcusdt'
    AVAX_USDT = 'avaxusdt'
