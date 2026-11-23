"""Competitor intelligence from awarded tenders: who wins, from which buyers, at what price.

Reads the award reports stored in `lead.extra` (Monaqasat: winners, approved value, every bid).
"""

from collections import defaultdict

TOP = 25


def market_report(leads: list[dict], min_score: int) -> dict:
    """Aggregates awarded leads. `relevant` counts only leads that match the company (keywords or AI)."""
    awarded = [lead for lead in leads if lead["status"] == "awarded" and (lead.get("extra") or {}).get("winners")]
    competitors = defaultdict(lambda: {
        "wins": 0, "bids": 0, "relevant_wins": 0, "won_value": 0.0, "relevant_value": 0.0, "buyers": set(),
        "currency": "", "largest": None,
    })
    buyers = defaultdict(lambda: {"awards": 0, "relevant": 0, "value": 0.0, "currency": ""})
    recent = []
    for lead in awarded:
        extra = lead["extra"]
        relevant = _is_relevant(lead, min_score)
        buyer = lead.get("buyer_en") or lead.get("buyer") or "Unknown buyer"
        value = _number(extra.get("award_value"))
        buyers[buyer]["awards"] += 1
        buyers[buyer]["relevant"] += relevant
        buyers[buyer]["value"] += value
        buyers[buyer]["currency"] = lead.get("currency", "")
        bidders = {bid["company"] for bid in extra.get("bids", [])}
        for name in bidders:
            competitors[name]["bids"] += 1
        for winner in extra["winners"]:
            entry = competitors[winner["company"]]
            entry["wins"] += 1
            entry["relevant_wins"] += relevant
            value_won = _number(winner.get("value"))
            entry["won_value"] += value_won
            entry["buyers"].add(buyer)
            entry["currency"] = lead.get("currency", "")
            if relevant:
                entry["relevant_value"] += value_won
                if not entry["largest"] or value_won > entry["largest"]["value"]:
                    entry["largest"] = {"title": lead.get("title_en") or lead["title"], "value": value_won}
            if winner["company"] not in bidders:
                entry["bids"] += 1  # single-envelope reports list no bids; a winner did bid
        if relevant:
            recent.append(_award_row(lead, buyer))
    return {
        "awarded": len(awarded),
        "relevant_awarded": len(recent),
        "competitors": _top_competitors(competitors),
        "partners": _partners(competitors),
        "buyers": sorted(
            ({"buyer": name, **data} for name, data in buyers.items()),
            key=lambda b: (-b["relevant"], -b["awards"]),
        )[:TOP],
        "recent": sorted(recent, key=lambda row: row["date"], reverse=True)[:TOP * 2],
    }


def company_names(extra: dict) -> set:
    """Every winner and bidder name in one award report, for translation."""
    return {entry["company"] for part in ("winners", "bids") for entry in extra.get(part, []) if entry.get("company")}


def add_company_english(extra: dict, english):
    """Sets company_en on each winner and bid. `english(text)` returns the cached English."""
    for part in ("winners", "bids"):
        for entry in extra.get(part, []):
            entry["company_en"] = english(entry.get("company", ""))


def add_report_english(report: dict, english):
    """English names next to the originals in a market report."""
    for row in report["competitors"] + report.get("partners", []):
        row["company_en"] = english(row["company"])
    for row in report["recent"]:
        row["winners_en"] = [english(name) for name in row["winners"]]


def _top_competitors(competitors: dict) -> list[dict]:
    rows = [
        {
            "company": name, "wins": data["wins"], "bids": data["bids"], "relevant_wins": data["relevant_wins"],
            "win_rate": round(data["wins"] / data["bids"], 2) if data["bids"] else None,
            "won_value": round(data["won_value"], 2), "buyers": sorted(data["buyers"])[:5],
        }
        for name, data in competitors.items()
    ]
    return sorted(rows, key=lambda r: (-r["relevant_wins"], -r["wins"], -r["won_value"]))[:TOP]


def _partners(competitors: dict) -> list[dict]:
    """Companies that win large contracts in your field: a small company can offer to deliver
    the software part as their subcontractor, under their bond and their registration."""
    rows = [
        {
            "company": name, "relevant_wins": data["relevant_wins"], "relevant_value": round(data["relevant_value"], 2),
            "currency": data["currency"], "largest": data["largest"], "buyers": sorted(data["buyers"])[:5],
        }
        for name, data in competitors.items() if data["relevant_wins"]
    ]
    return sorted(rows, key=lambda r: -r["relevant_value"])[:TOP]


def _award_row(lead: dict, buyer: str) -> dict:
    extra = lead["extra"]
    bids = sorted(_number(bid["value"]) for bid in extra.get("bids", []) if _number(bid["value"]) > 0)
    return {
        "key": lead["key"],
        "title": lead.get("title_en") or lead["title"],
        "buyer": buyer,
        "winners": [winner["company"] for winner in extra["winners"]],
        "value": _number(extra.get("award_value")),
        "currency": lead.get("currency", ""),
        "bidders": extra.get("bidders") or len(bids),
        "lowest_bid": bids[0] if bids else None,
        "highest_bid": bids[-1] if bids else None,
        "date": lead.get("closing") or lead.get("published") or lead["first_seen"][:10],
        "url": extra.get("award_report") or lead["url"],
    }


def _is_relevant(lead: dict, min_score: int) -> bool:
    return lead["score"] >= min_score or (lead.get("ai_fit") or 0) >= 6


def _number(text) -> float:
    try:
        return float(str(text or "").replace(",", ""))
    except ValueError:
        return 0.0
