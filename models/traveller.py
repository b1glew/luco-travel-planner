from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Traveller:
    name: str
    selectedOptions: List[str] = field(default_factory=list)
    roomType: Optional[str] = None
