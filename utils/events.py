from pyee import AsyncIOEventEmitter, EventEmitter

ee = AsyncIOEventEmitter()
# ee = EventEmitter()

class EExchange:
    TRADE_EVENT = 'TRADE_EVENT'
    CANDLESTICK_EVENT = 'CANDLESTICK_EVENT'
    USER_DATA_EVENT = 'USER_DATA_EVENT'


class Trade:
    STOP_TRADE = 'STOP_TRADE'
    COMPLETE_CANDLESTICK_EVENT = 'COMPLETE_CANDLESTICK_EVENT'


class TelegramEventType:
    STATS = 'STATS'
    STOP = 'STOP'


class ESignal:
    DIVERGENCE_FOUND = 'DIVERGENCE_FOUND'
