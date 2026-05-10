from dataclasses import dataclass


@dataclass
class Option:
    name: str
    cost: float
    currency: str
    depositRatio: float = 1.0
