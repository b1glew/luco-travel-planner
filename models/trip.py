from dataclasses import asdict, dataclass, field
from typing import List, Optional

from models.accommodation import Accommodation
from models.cost_item import CostItem
from models.options import Option
from models.traveller import Traveller


@dataclass
class Trip:
    name: str
    description: str
    travellers: List[Traveller] = field(default_factory=list)
    costItems: List[CostItem] = field(default_factory=list)
    options: List[Option] = field(default_factory=list)
    accommodation: Optional[Accommodation] = None
    categories: List[str] = field(
        default_factory=lambda: [
            "Flights",
            "Accommodation",
            "Equipment",
            "Food",
            "Transport",
            "Misc",
        ]
    )
    baseCurrency: str = "GBP"
    exchangeRates: dict = field(default_factory=dict)
    notes: str = ""
    startDate: str = ""
    endDate: str = ""

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "travellers": [asdict(t) for t in self.travellers],
            "costItems": [c.to_dict() for c in self.costItems],
            "options": [asdict(o) for o in self.options],
            "accommodation": self.accommodation.to_dict() if self.accommodation else None,
            "categories": self.categories,
            "baseCurrency": self.baseCurrency,
            "exchangeRates": self.exchangeRates,
            "notes": self.notes,
            "startDate": self.startDate,
            "endDate": self.endDate,
        }

    @classmethod
    def from_dict(cls, d):
        trip = cls(d["name"], d["description"])
        trip.travellers = [Traveller(**t) for t in d.get("travellers", [])]
        trip.costItems = [CostItem.from_dict(c) for c in d.get("costItems", [])]
        trip.options = [Option(**o) for o in d.get("options", [])]
        trip.accommodation = (
            Accommodation.from_dict(d["accommodation"])
            if d.get("accommodation")
            else None
        )
        trip.categories = d.get("categories", trip.categories)
        trip.baseCurrency = d.get("baseCurrency", trip.baseCurrency)
        trip.exchangeRates = d.get("exchangeRates", {})
        trip.notes = d.get("notes", "")
        trip.startDate = d.get("startDate", "")
        trip.endDate = d.get("endDate", "")
        return trip
