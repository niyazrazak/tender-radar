from dataclasses import dataclass, field, asdict


@dataclass
class Lead:
    """One tender / RFQ opportunity, normalized across all portals."""

    source: str
    source_id: str
    country: str
    title: str
    url: str
    status: str = "open"  # open | future | opened (bids opened) | awarded
    ref_no: str = ""
    buyer: str = ""
    category: str = ""
    tender_type: str = ""
    published: str = ""  # ISO date YYYY-MM-DD
    closing: str = ""  # ISO date YYYY-MM-DD
    bond: str = ""
    doc_fee: str = ""
    currency: str = ""
    brief: str = ""
    activities: str = ""
    extra: dict = field(default_factory=dict)
    score: int = 0
    matched: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def searchable_text(self) -> str:
        return " ".join([self.title, self.brief, self.activities, self.category])

    def to_dict(self) -> dict:
        return asdict(self)
