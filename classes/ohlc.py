from settings import SYMBOL


class Ohlc(object):
    mavg: float = 0
    hband: float = 0
    lband: float = 0
    rsi8: float = 0
    ema_fast: float = 0
    atr: float = 0
    vwap: float = 0
    quoteAssetVolume: float = 0

    def __init__(self, unix, date, open: float, high: float, low: float,
                 close: float, volume_btc: float = None, volume_usdt: float = None, tradecount=None,
                 rsi=0, peak=False, trough=False, valid_pt=False, ema=None, dema=None, tema=None,
                 quoteAssetVolume: float = 0):
        self.unix = unix
        self.date = date
        self.symbol = SYMBOL
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume_btc = volume_btc
        self.volume_usdt = volume_usdt
        self.tradecount = tradecount
        self.rsi = rsi
        self.peak = peak
        self.trough = trough
        self.valid_pt = valid_pt
        self.ema_slow = ema
        self.dema = dema
        self.tema = tema
        self.quoteAssetVolume=quoteAssetVolume

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

    def __repr__(self):
        return str(self.__class__) + ": " + str(self.__dict__)
