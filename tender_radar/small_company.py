"""Small company mode: which tenders a small company can bid on without much money up front.

Three signals, from what the portals publish:
- Reserved for SMEs: the tender type says so (Oman labels "مؤسسات صغيرة و المتوسطة").
- Small value: procurement types for small purchases, which usually have a small bond or none:
  Monaqasat "ممارسة / اتفاق مباشر اقل من 200.000", practices (ممارسة), Etimad direct purchase,
  RFQs. Qatar also waives document fees and can waive bonds for SMEs below set limits.
- Up-front cost: document fee + bid bond in US dollars, when the portal lists both as amounts.
  A bond given as a percent of the bid, or not listed, leaves the cost unknown.
"""

import re

# Gulf currencies are pegged to the US dollar (Kuwait's to a basket, so its rate is approximate).
# Same rates as the dashboard (app.js USD_PER).
USD_PER = {"QAR": 1 / 3.64, "SAR": 1 / 3.75, "OMR": 1 / 0.3845, "AED": 1 / 3.6725, "KWD": 3.25, "BHD": 1 / 0.376}

FREELANCER_OPEN = re.compile(r"صاحب عمل حر|freelanc", re.I)  # Oman's tender type for licensed freelancers
SME_RESERVED = re.compile(r"صغيرة\s*و\s*ال?متوسطة|\bSMEs?\b|small and medium", re.I)
SMALL_VALUE = [
    (re.compile(r"اقل من ([\d.,]+)"), "Under QAR {0}"),
    (re.compile(r"ممارسة"), "Practice (limited purchase)"),
    (re.compile(r"شراء مباشر|اتفاق مباشر|الإسناد المباشر"), "Direct purchase"),
    (re.compile(r"\bRFQ\b", re.I), "Request for quotation"),
]
DEFAULT_MAX_UPFRONT_USD = 2000
BIDDABLE = ("open", "future")


def assess(lead: dict, max_upfront_usd: float = DEFAULT_MAX_UPFRONT_USD) -> dict:
    """{"sme_reserved", "small_value" (label or ""), "upfront_usd" (None = unknown), "fits"}."""
    kind = f"{lead.get('tender_type', '')} {lead.get('ref_no', '')}"
    upfront = upfront_usd(lead)
    sme_reserved = bool(SME_RESERVED.search(kind))
    small_value = _small_value(kind)
    affordable = sme_reserved or bool(small_value) or (upfront is not None and upfront <= max_upfront_usd)
    fits = affordable and lead.get("status", "open") in BIDDABLE  # awarded or opened: too late to bid
    return {
        "sme_reserved": sme_reserved, "small_value": small_value, "upfront_usd": upfront, "fits": fits,
        "freelancer_open": bool(FREELANCER_OPEN.search(kind)),
    }


def upfront_usd(lead: dict) -> float | None:
    """Document fee + bid bond in US dollars. None when either is unlisted or the bond is a percent."""
    fee, bond = _amount(lead.get("doc_fee")), _amount(lead.get("bond"))
    if fee is None or bond is None:
        return None
    return round((fee + bond) * USD_PER.get(lead.get("currency", ""), 1), 2)


def _small_value(kind: str) -> str:
    for pattern, label in SMALL_VALUE:
        match = pattern.search(kind)
        if match:
            # Monaqasat writes thousands with a dot: "200.000" is 200,000.
            return label.format(*(group.replace(".", ",") for group in match.groups()))
    return ""


def _amount(text) -> float | None:
    text = str(text if text is not None else "").strip()
    if not text or text.endswith("%"):
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None
