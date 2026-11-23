import html
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

EXCEL_COLUMNS = [
    ("Score", "score"), ("Country", "country"), ("Status", "status"), ("Title", "title_en"),
    ("Buyer", "buyer_en"), ("Ref No", "ref_no"), ("Published", "published"), ("Closing", "closing"),
    ("Doc fee", "doc_fee"), ("Bond", "bond"), ("Currency", "currency"),
    ("Winner", "winner"), ("Award value", "award_value"), ("Bidders", "bidders"), ("Category", "category_en"),
    ("Activities", "activities_en"), ("Brief", "brief_en"), ("Matched keywords", "matched"),
    ("Title (original)", "title"), ("Buyer (original)", "buyer"), ("Brief (original)", "brief"),
    ("Link", "url"), ("First seen", "first_seen"),
]


class LeadReport:
    """Writes the lead list as an HTML dashboard and an Excel sheet."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

    def write(self, leads: list[dict], new_keys: set) -> tuple[Path, Path]:
        stem = f"leads-{date.today().isoformat()}"
        html_path = self.out_dir / f"{stem}.html"
        xlsx_path = self.out_dir / f"{stem}.xlsx"
        for lead in leads:
            lead.update(_award_fields(lead))
        html_path.write_text(self._html(leads, new_keys), encoding="utf-8")
        self._excel(leads, xlsx_path)
        return html_path, xlsx_path

    def _excel(self, leads: list[dict], path: Path):
        book = Workbook()
        sheet = book.active
        sheet.title = "Leads"
        sheet.append([title for title, _ in EXCEL_COLUMNS])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for lead in leads:
            sheet.append([lead.get(field, "") for _, field in EXCEL_COLUMNS])
            link = sheet.cell(row=sheet.max_row, column=len(EXCEL_COLUMNS) - 1)
            link.hyperlink = lead["url"]
        sheet.freeze_panes = "A2"
        book.save(path)

    def _html(self, leads: list[dict], new_keys: set) -> str:
        rows = "\n".join(self._row(lead, lead["key"] in new_keys) for lead in leads)
        countries = sorted({lead["country"] for lead in leads})
        options = "".join(f"<option>{_e(c)}</option>" for c in countries)
        summary = f"{len(leads)} leads · {len(new_keys & {lead['key'] for lead in leads})} new this run"
        return PAGE.format(today=date.today().isoformat(), summary=summary, options=options, rows=rows)

    def _row(self, lead: dict, is_new: bool) -> str:
        badge = '<span class="new">NEW</span> ' if is_new else ""
        status = "" if lead["status"] == "open" else f'<span class="tag">{_e(lead["status"])}</span> '
        detail = " · ".join(_e(x) for x in (_en(lead, "category"), _en(lead, "activities")) if x)
        original = lead["title"] if _en(lead, "title") != lead["title"] else ""
        brief = _en(lead, "brief")
        money = f'Fee {_e(lead["doc_fee"])} {_e(lead["currency"])}' if lead["doc_fee"] else ""
        return f"""<tr data-country="{_e(lead['country'])}" data-new="{int(is_new)}">
<td class="score">{lead['score']}</td>
<td>{badge}{status}<a href="{_e(lead['url'])}" target="_blank" dir="auto">{_e(_en(lead, 'title'))}</a>
<div class="ar" dir="rtl">{_e(original)}</div><div class="sub" dir="auto">{detail}</div>
{f'<details><summary>Brief</summary><div class="brief">{_e(brief)}</div></details>' if brief else ''}
<div class="kw">{_e(lead['matched'])}</div>{_award_line(lead)}</td>
<td dir="auto">{_e(_en(lead, 'buyer'))}<div class="sub">{_e(lead['country'])} · {_e(lead['ref_no'])}</div></td>
<td>{_e(lead['published'])}</td><td class="closing">{_e(lead['closing'])}</td><td>{money}</td></tr>"""


def _award_fields(lead: dict) -> dict:
    """Flat award columns from the award report kept in `extra` (Monaqasat only for now)."""
    extra = lead.get("extra") or {}
    return {
        "winner": "; ".join(w["company"] for w in extra.get("winners", [])),
        "award_value": extra.get("award_value", ""),
        "bidders": extra.get("bidders", ""),
    }


def _award_line(lead: dict) -> str:
    if not lead.get("winner"):
        return ""
    value = f' · {_e(lead["award_value"])} {_e(lead["currency"])}' if lead.get("award_value") else ""
    bidders = f' · {lead["bidders"]} bidders' if lead.get("bidders") else ""
    return f'<div class="award" dir="auto">Won by {_e(lead["winner"])}{value}{bidders}</div>'


def _en(lead: dict, field: str) -> str:
    """English version when the report added one, else the original text."""
    return lead.get(f"{field}_en") or lead.get(field) or ""


def _e(value) -> str:
    return html.escape(str(value or ""))


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Tender leads {today}</title>
<style>
body{{font:14px/1.45 -apple-system,Segoe UI,Tahoma,sans-serif;margin:24px;color:#1d2433;background:#f6f7f9}}
h1{{font-size:20px;margin:0 0 4px}} .meta{{color:#667;margin-bottom:16px}}
.bar{{display:flex;gap:8px;margin-bottom:12px}}
input,select{{padding:7px 10px;border:1px solid #ccd;border-radius:6px;font:inherit}}
input{{flex:1}} table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden}}
th{{text-align:left;background:#eef0f4;padding:8px;font-weight:600;font-size:12px;text-transform:uppercase;color:#556}}
td{{padding:8px;border-top:1px solid #eceef2;vertical-align:top}}
a{{color:#1450c8;text-decoration:none;font-weight:600}}
.sub{{color:#667;font-size:12px;margin-top:2px}} .kw{{color:#2a7a4b;font-size:11px;margin-top:2px}}
.score{{font-weight:700;font-size:16px;text-align:center}} .closing{{white-space:nowrap;font-weight:600}}
.new{{background:#1450c8;color:#fff;font-size:10px;padding:1px 5px;border-radius:4px}}
.ar{{color:#889;font-size:12px;margin-top:2px}} .brief{{color:#445;font-size:12px;max-width:760px;white-space:pre-wrap}}
summary{{color:#1450c8;font-size:12px;cursor:pointer;margin-top:3px}}
.tag{{background:#f0e2c0;font-size:10px;padding:1px 5px;border-radius:4px}}
.award{{color:#7a4b00;font-size:12px;margin-top:3px}}
</style></head><body>
<h1>Tender &amp; RFQ leads</h1><div class="meta">{today} · {summary}</div>
<div class="bar"><input id="q" placeholder="Filter by any word, e.g. ERP, mobile app, AI…">
<select id="c"><option value="">All countries</option>{options}</select>
<select id="n"><option value="">All leads</option><option value="1">New only</option></select></div>
<table><thead><tr><th>Score</th><th>Tender</th><th>Buyer</th><th>Published</th><th>Closing</th><th>Fee</th></tr></thead>
<tbody id="rows">{rows}</tbody></table>
<script>
const q=document.getElementById('q'),c=document.getElementById('c'),n=document.getElementById('n');
function f(){{const t=q.value.toLowerCase();for(const r of document.querySelectorAll('#rows tr')){{
r.style.display=(!t||r.innerText.toLowerCase().includes(t))&&(!c.value||r.dataset.country===c.value)&&(!n.value||r.dataset.new===n.value)?'':'none'}}}}
[q,c,n].forEach(e=>e.addEventListener('input',f));
</script></body></html>"""
