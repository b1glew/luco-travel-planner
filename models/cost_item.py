from dataclasses import dataclass
from enum import Enum


class CostType(Enum):
    PER_PERSON = "per_person"
    GROUP_TOTAL = "group_total"


def normalize_cost_type(value):
    if isinstance(value, CostType):
        return value

    raw_value = getattr(value, "value", value)
    try:
        return CostType(raw_value)
    except (TypeError, ValueError):
        raw_name = getattr(value, "name", "")

    if raw_name in CostType.__members__:
        return CostType[raw_name]

    return CostType.GROUP_TOTAL


@dataclass
class CostItem:
    name: str
    category: str
    amount: float
    currency: str
    costType: CostType
    depositRatio: float = 1.0
    discountRatio: float = 0.0

    def to_dict(self):
        return {
            "name": self.name,
            "category": self.category,
            "amount": self.amount,
            "currency": self.currency,
            "costType": self.costType.value,
            "depositRatio": self.depositRatio,
            "discountRatio": self.discountRatio,
        }

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d["depositRatio"] = d.get("depositRatio", 1.0)
        d["discountRatio"] = d.get("discountRatio", 0.0)
        d["costType"] = normalize_cost_type(d["costType"])
        return cls(**d)
