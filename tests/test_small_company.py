from tender_radar.small_company import assess, upfront_usd


def lead(**fields):
    return {"tender_type": "", "ref_no": "", "doc_fee": "", "bond": "", "currency": "QAR"} | fields


def test_oman_sme_tender_is_reserved():
    result = assess(lead(tender_type="مؤسسات صغيرة و المتوسطة [ Local]", currency="OMR"))
    assert result["sme_reserved"] and result["fits"]


def test_monaqasat_small_value_label_reads_the_limit():
    assert assess(lead(tender_type="ممارسة اقل من 200.000"))["small_value"] == "Under QAR 200,000"


def test_direct_purchase_and_rfq_are_small_value():
    assert assess(lead(tender_type="شراء مباشر", currency="SAR"))["small_value"] == "Direct purchase"
    assert assess(lead(tender_type="RFQ"))["small_value"] == "Request for quotation"


def test_upfront_cost_in_dollars():
    assert upfront_usd(lead(doc_fee="364", bond="3,276")) == 1000.0
    assert upfront_usd(lead(doc_fee="100", bond="0", currency="BHD")) == round(100 / 0.376, 2)


def test_unknown_upfront_cost_when_bond_is_a_percent_or_missing():
    assert upfront_usd(lead(doc_fee="10", bond="2%", currency="OMR")) is None
    assert upfront_usd(lead(doc_fee="500")) is None


def test_public_tender_with_a_large_bond_does_not_fit():
    result = assess(lead(tender_type="مناقصة عامة", doc_fee="800", bond="80,000.00"), max_upfront_usd=2000)
    assert not result["fits"]
    assert assess(lead(tender_type="مناقصة عامة", doc_fee="500", bond="0"), max_upfront_usd=2000)["fits"]


def test_awarded_tender_does_not_fit():
    assert not assess(lead(tender_type="RFQ", status="awarded"))["fits"]
