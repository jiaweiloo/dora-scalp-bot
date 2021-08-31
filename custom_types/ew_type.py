from typing import TypedDict


class IPoint(TypedDict):
    id: str
    point: int
    timestamp: int
    price: float
