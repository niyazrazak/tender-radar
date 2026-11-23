from tender_radar.market import market_report


def awarded(key, score, buyer, winners, bids=()):
    return {
        "key": key, "status": "awarded", "score": score, "ai_fit": None, "title": key, "buyer": buyer,
        "currency": "QAR", "closing": "2026-10-01", "published": "", "first_seen": "2026-10-01 00:00:00", "url": "u",
        "extra": {
            "winners": [{"company": name, "value": value} for name, value in winners],
            "award_value": f"{sum(float(v.replace(',', '')) for _, v in winners):,.2f}",
            "bids": [{"company": name, "value": value, "result": "", "note": ""} for name, value in bids],
        },
    }


def test_competitors_win_rate_and_relevance():
    leads = [
        awarded("a", 5, "Ministry A", [("Alpha", "100,000.00")], [("Alpha", "100,000.00"), ("Beta", "120,000.00")]),
        awarded("b", 0, "Ministry B", [("Beta", "50,000.00")], [("Alpha", "60,000.00"), ("Beta", "50,000.00")]),
        {"key": "c", "status": "open", "score": 9, "extra": {}},
    ]
    report = market_report(leads, min_score=3)
    by_name = {row["company"]: row for row in report["competitors"]}
    assert report["awarded"] == 2 and report["relevant_awarded"] == 1
    assert (by_name["Alpha"]["wins"], by_name["Alpha"]["bids"], by_name["Alpha"]["relevant_wins"]) == (1, 2, 1)
    assert by_name["Alpha"]["win_rate"] == 0.5
    assert report["competitors"][0]["company"] == "Alpha"  # relevant wins rank first
    assert report["recent"][0]["lowest_bid"] == 100000.0 and report["recent"][0]["highest_bid"] == 120000.0


def test_single_envelope_winner_counts_as_a_bid():
    report = market_report([awarded("a", 5, "M", [("Solo", "10.00")])], min_score=3)
    assert report["competitors"][0]["bids"] == 1


def test_partners_rank_winners_by_value_in_your_field():
    leads = [
        awarded("a", 5, "M", [("Big Co", "900,000.00")]),
        awarded("b", 5, "M", [("Mid Co", "100,000.00")]),
        awarded("c", 0, "M", [("Other Co", "5,000,000.00")]),
    ]
    partners = market_report(leads, min_score=3)["partners"]
    assert [p["company"] for p in partners] == ["Big Co", "Mid Co"]
    assert partners[0]["largest"] == {"title": "a", "value": 900000.0}
