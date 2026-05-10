from dataclasses import asdict, dataclass
from typing import Dict


@dataclass
class RoomType:
    name: str
    roomCount: int
    bedsPerRoom: int
    weighting: float


@dataclass
class Accommodation:
    totalCost: float
    currency: str
    roomTypes: Dict[str, RoomType]
    depositRatio: float = 0.0

    def total_beds(self) -> int:
        return sum(room.roomCount * room.bedsPerRoom for room in self.roomTypes.values())

    def total_weighted_beds(self) -> float:
        return sum(
            room.roomCount * room.bedsPerRoom * room.weighting
            for room in self.roomTypes.values()
        )

    def base_cost_per_bed(self) -> float:
        weighted_beds = self.total_weighted_beds()
        return self.totalCost / weighted_beds if weighted_beds else 0.0

    def room_cost(self, room_type_name: str) -> float:
        room = self.roomTypes.get(room_type_name)
        if not room:
            return 0.0
        return self.base_cost_per_bed() * room.weighting

    def to_dict(self):
        return {
            "totalCost": self.totalCost,
            "currency": self.currency,
            "roomTypes": {name: asdict(room) for name, room in self.roomTypes.items()},
            "depositRatio": self.depositRatio,
        }

    @classmethod
    def from_dict(cls, d):
        rooms = {k: RoomType(**v) for k, v in d["roomTypes"].items()}
        return cls(d["totalCost"], d["currency"], rooms, d.get("depositRatio", 1.0))
