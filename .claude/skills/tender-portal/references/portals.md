# Portal notes

Facts about each portal that the code does not explain. Update this file when
you learn something new about a portal (a changed label, a new quirk).

## Monaqasat — Qatar (`sources/monaqasat.py`)

- Owner: Ministry of Finance, Qatar. Base: `https://monaqasat.mof.gov.qa`.
- Public pages. `robots.txt` allows all.
- Read as server-rendered HTML with BeautifulSoup.
- **TLS:** the server offers only plain-RSA cipher suites, which Python's
  default list drops, so the firewall resets the connection. The fix is
  `context.set_ciphers("DEFAULT")`. The server also does not send its
  intermediate certificate. The project ships it in
  `tender_radar/certs/intermediates.pem`. When the certificate is renewed,
  the intermediate can change, and the error comes back as
  `CERTIFICATE_VERIFY_FAILED`.
- **List pages** (page number at the end, starts at 1):
  - open: `/TendersOnlineServices/AvailableMinistriesTenders/{page}`
  - future: `/TendersOnlineServices/FutureTenders/{page}`
  - awarded: `/TendersOnlineServices/AwardedTenders/{page}`
- Past the last page the portal does not return an error. It repeats
  tenders, so paging stops when a page brings no unseen key.
- **List card:** each tender is a `div.custom-cards`. The title link is
  `.card-title a[href]`, and the last part of its href is the tender id
  (`source_id`). The reference number is `.col-header .card-label`. Other
  fields are `.cards-row` blocks of `.card-label` (Arabic label) +
  `.card-title` (value), mapped by `CARD_FIELDS`. The closing date is in the
  `.circle-container` whose label contains `الإغلاق`; the last `span` is the date.
- **Dates** are `DD/MM/YYYY`.
- **Detail page:** three kinds of `<table>`:
  - activity table, header `كود النشاط | اسم النشاط` → `lead.activities`
  - name/value table, header `الاسم | القيمة`
  - header-row tables (first row = labels, second row = values)
  Useful labels: `نبذة مختصرة` (brief), `تاريخ الاقفال` (closing),
  `رقم المناقصة لدى الجهة`, `أنواع مقدمي العطاءات المستهدفين`,
  `مكان التنفيذ أو التسليم`, `مدة العقد (عدد الأشهر)`, `نظام المظاريف`.
- Labels mix hamza forms (`الإغلاق` on the card, `الاقفال` on the detail
  page). When a field goes empty, check the hamza first.
- **Award report** (public, no login):
  `/TendersOnlineServices/TenderCompaniesDetails/{id}`, the "التقرير" button
  on an awarded card. Same id as the tender. Tables, told apart by header:
  - winners: `اسم الشركة | رقم السجل التجاري | القيمة الموافق عليها | ...`
    (approved value as `284,050.00 رق`; can list more than one winner)
  - technical opening: exactly `اسم الشركة | رقم السجل التجاري`, one row per
    bidder. Missing for single-envelope tenders.
  - financial opening: `... | قيمة العطاء | نسبة القيمة المحلية |
    النتيجة المالية | ملاحظات`; `مستبعد` in the notes = excluded bid.
  Stored in `lead.extra` as `winners`, `award_value`, `bidders`, `bids`,
  `award_report`. Fetched once, when a tender is first seen as awarded,
  including tenders stored earlier as open (the id does not change).
- The awarded list is newest first, about 20 a page and 1-2 days a page.
  1,243 pages in total.
- Monaqasat already carries the tenders of Kahramaa, Ashghal, HMC, Qatar
  Foundation, Qatar University and most ministries (checked 2026-11-23).
  Separate sources for them would only add duplicates.
- Currency: QAR.

## Mwani Qatar — Qatar (`sources/mwani.py`)

- Qatar Ports Management. Not on Monaqasat.
- `robots.txt` blocks only `/_layouts/`, `/_vti_bin/`, `/_catalogs/`.
- The page `/English/Procurement/Pages/TendersAuctions.aspx` is filled by
  JavaScript from the anonymous SharePoint REST endpoint
  `/_api/web/lists/GetByTitle('Tenders%20and%20Auctions')/items`
  (`Accept: application/json;odata=verbose`). `$top` and `$orderby` work.
  `$skip` is not supported for list items; at 2-3 items a month, the newest
  `max_items` (50) is enough.
- Fields: `Id` (stable), `Title`, `Arabic_x0020_Title` (often the same
  English text), `Tender_x0020_Number`, `Category` (`Tender;مناقصة` or
  `Auction;مزاد علني`; auctions are skipped), `Start_x0020_Date`,
  `Closing_x0020_Date`, `Tender_x0020_Fee`, `Tender_x0020_Bond_x0020_Value`,
  `Submission_x0020_Method`. The "content" fields hold only a contact email.
- Dates are Qatar midnight stored in UTC (`2026-11-11T21:00:00Z` =
  2026-11-12). Add 3 hours before taking the date.
- No detail page, no category; `url` is the list page.

## Qatar Football Association — Qatar (`sources/qfa.py`)

- Not on Monaqasat. About 11 tenders a year, several IT and digital.
- `robots.txt` allows generic agents, blocks named AI crawlers, and sets
  `Content-Signal: search=yes,ai-train=no,use=reference`. tender-radar keeps
  a link back to the list (reference use). Never use QFA content for training.
- List: `GET /en/tenders?page={page}`, 4 tenders a page, newest first,
  about 33 pages. Past the last page the list is empty.
- Each tender is a `.tender-box`: `.tender-heading p` (title, often with the
  tender number), `.tender-desc` (bond text), `.tag` x2 (type, category),
  `p.text-primary` labels `Issue Date` / `Closing Date` with an `h4` value
  (`DD-MM-YYYY`), `h6` = document fee in QR.
- The id is the tender number, written `T/10/2026` or `T\11/2026`,
  normalized to `T/NN/YYYY`. A few older tenders have none; the id is then
  issue date + title.
- The bond wording varies ("bond in the amount of 25,000 QR",
  "15,000 QR Tender Bond", or only "30,000 QR"). Contact emails are hidden
  by Cloudflare (`[email protected]`) and are stripped.
- Auctions (title starts with "Auction") are skipped.

## Sidra Medicine — Qatar (`sources/sidra.py`)

- Linked from `https://www.sidra.org/procurement-and-contracts/` ("active
  tenders", a bit.ly link). The list is Sidra's Oracle Fusion
  `NegotiationAbstracts?prcBuId=300000003054324` on
  `fa-epxn-saasfaprod1.fa.ocs.oraclecloud.com`. Public, no login. sidra.org
  robots.txt allows all; the Oracle host has no robots.txt (404). Checked
  2026-11-23.
- **Oracle ADF loopback:** the first GET returns only a script. Take the id
  from `_addParam(query, "_afrLoop", "<id>")` and GET the same URL again with
  `&_afrLoop=<id>&_afrWindowMode=0&_afrWindowId=null` in the same session
  (cookies `JSESSIONID`, `ORA_FUSION_PREFS`). That returns server HTML.
- **Rows:** `tr[_afrrk]` (ADF row key). The CSS classes (`xem`, `x2ey`) are
  generated; do not use them. Cells: negotiation number, title, type
  (RFQ/RFI/...), status (Active/Closed), posting, open and close dates.
- **Dates:** `11/23/26 8:11 AM`, M/D/YY in UTC (the page says "Coordinated
  Universal Time"). Add 3 h for the Qatar date.
- **Ids:** amendments change the number (`20731,1`, `20442-2`).
- About 25 rows, newest first; `_rowCount="-1"`. Further rows and the
  "Details" buttons are ADF partial-page requests, not URLs. Not collected.
- Mostly medical and research supplies; about 10% IT (RFIs for systems,
  Oracle). Large facilities contracts go to Monaqasat under Qatar Foundation.

## WOQOD — Qatar (`sources/woqod.py`)

- Qatar Fuel. Not on Monaqasat. Page: `/website/en/tenders-and-supplier/all-tenders`
  (Angular). It reads `GET /fo_api_website/api/Tenders/getAllTenderDetails
  ?PageSize=50&PageIndex=1&TenderStatus=0` anonymously. `TenderStatus` 0 = open,
  1 = closed (177 on 2026-11-23), 2 = awarded (always empty).
- **robots.txt:** the F5 firewall answers "Request Rejected" for `/robots.txt`
  to every client, a real browser too, so there are no readable rules. The
  terms (`/website/en/pages/woqodtermsandconditions`) forbid only interfering
  with or loading the service. The source makes one request per check. A
  plain `curl` is rejected; the project client works.
- **Double JSON:** the body is a JSON string holding `{"status", "data":
  {"totalCount", "pageItems": [...]}}`. Decode it twice.
- **Item:** `tenderDetailsID` (GUID, stable id), `titleEN`, `tenderNumber`
  (trailing spaces), `fee`, `tenderBond`, `isPaid`, `startingDate`,
  `closingDate` (`2026-11-24T00:00:00`, Qatar date), `pageURL` (append to
  `/website/en`), `isCanceled`. `scopeOfWorkEN` and `descriptionEN` are
  usually null.
- **`detailsEN` is the same bid instructions on every tender** ("obtain the
  document on the website / portal"). Do not score it: "website" and
  "portal" then match every tender. It is kept in `extra.instructions`.
- `fee` 0 with `isPaid` false means free documents (often "send CR and a
  letter of interest by email"). `tenderBond` 0 means none stated.

## QAFCO — Qatar (`sources/qafco.py`)

- Qatar Fertiliser Company. Not on Monaqasat. Page:
  `https://www.qafco.qa/en/suppliers/` (WordPress, Elementor). robots.txt
  blocks only `/wp-admin/`. Bids go through QAFCO's SAP Ariba; the list and
  PDFs are public. Checked 2026-11-23.
- **List:** each RFQ is a `.elementor-widget-icon-box` whose text is
  `RFQ 6000006977 <title>` and whose link is the "Invitation to Tender" PDF
  under `/wp-content/uploads/YYYY/MM/`. The page repeats some RFQs and keeps
  old ones for months (2025/11 still listed in 2026/11), so the source opens
  only PDFs uploaded in the last `max_age_days` (default 120).
- **PDF** (2 pages, text layer; read with pypdf through
  `PoliteClient.get_pdf_text`, so fixtures store text): an English table, then
  "GENERAL INSTRUCTIONS", then Arabic. In the table the fee is `500/-`, the bond
  is `QAR 52,000 (...)`, `32,000 (...)` or `Not applicable` (stored as 0), then
  the fee-receipt dates and last the closing date. Dates are `13.12.2026` or
  `31/08/2026`.
- About 1 RFQ in 20 is IT (e.g. "Implementation of SAP Ariba Spend Control
  Tower", 2026/03). QAFAC is checked and not built: see "Candidate portals".

## Etimad — Saudi Arabia (`sources/etimad.py`)

- Owner: Ministry of Finance, Saudi Arabia. Base: `https://tenders.etimad.sa`.
- Read through the JSON feed behind the public visitor page:
  `GET /Tender/AllSupplierTendersForVisitorAsync`. It needs
  `X-Requested-With: XMLHttpRequest` (`PoliteClient.get_json` sends it).
- Params: `PageSize` (24), `PageNumber` (from 1), `PublishDateId`,
  `TenderCategory=2` (active tenders), `IsSearch=true`,
  `sort=SubmitionDate`, `sortDirection=DESC`.
- `PublishDateId` values: 2 = last 2 days, 3 = last week, 4 = last month,
  5 = last 3 months. `config.json` sets this with `publish_window`.
- Response: `{"data": [...], "totalCount": N}`. Stop when a page has fewer
  than `PageSize` rows or the total is reached.
- Field names keep Etimad's own spelling: `submitionDate`,
  `condetionalBookletPrice`, `lastEnqueriesDate`. Do not "fix" them.
- `tenderId` (number) is the stable id. `tenderIdString` is an encrypted id
  used only in the detail URL.
- Detail URL: `/Tender/DetailsForVisitor?STenderId=...`, or
  `DetailsTenderAnnouncement` when `tenderTypeId == 15`. Tenders with
  `isUGRP` use `ugrpRfxUrl` instead.
- Dates are ISO date-times; the first 10 characters are the date.
- Currency: SAR. No detail pages are fetched now; `tenderActivityName`
  gives the category for scoring.

## Oman Tender Board — Oman (`sources/oman_tender_board.py`)

- Owner: Secretariat General of the Tender Board (system name "Esnad").
  Base: `https://etendering.tenderboard.gov.om/product`.
- No `robots.txt` (404). The "new tenders" list is public, no login.
- No TLS problems with the default `PoliteClient`.
- **List:** `GET /publicDash?viewFlag=NewTenders&pageNo={page}`, 50 rows a
  page. The page's own paging is a form POST through `submitPage()`, but a
  plain GET with `pageNo` works.
- **Paging trap:** past the last page the portal does not fail. It serves
  old tenders (2018). Read the page count from
  `<input type='hidden' name='hidMax' value='41'>` and stop there.
- The same tender can show on two pages while the list changes; dedupe by id.
- **Row:** the tender table is the second `table.display`. Cells: serial,
  ref no, title, buyer, category `[grades]`, type `[Local]`, dates, fee,
  bond, actions. The id is in `onclick="getNit('102040')"`.
- Long title and category are cut to `.....` in the cell. The full text is in
  the cell's `onmouseover="Tip('...')"`. A hidden
  `input#tendDesc{n}` holds a longer description, used as `brief`.
- Dates cell: `Sales EndDate:29-11-2026-Bid Closing Date:09-12-2026`
  (`DD-MM-YYYY`). Fee and bond are `N/A` when empty.
- The bond column header is `الضمان البنكي (%/value)`: the cell holds a bare
  number that is either a percent of the bid (1, 2, 5) or an OMR amount
  (200, 10000). The source stores numbers up to 10 as `"1%"`.
- No published date in the list.
- **Detail page** (`/nitParameterView?mode=public&tenderNo=...`) needs a URL
  signed by `getFinalURL()` (`encparam`/`hashval`). A plain GET returns
  "You are unable to access the requested page", even with the session
  cookie. The source does not fetch details, and `lead.url` points to the
  public list. Users find the tender there by its ref no.
- Other public lists exist and are not collected yet:
  `viewFlag=InProcessTenders`, `/CompletedTendersForPublic`,
  `/CanceledTendersForPublic`, `viewFlag=SubContractTenders`.
- **Completed (awarded) list, `/CompletedTendersForPublic` ("المسندة"):
  not collected on purpose.** The dashboard opens it with `submitPage()`,
  which signs the form (`createFormHash` in `FormValidate.js` fills
  `encparam`/`hashval`). A GET or POST without the hash, even with the
  session cookie and Referer, returns the generic "Security Page". The user
  decided (2026-11-23) not to copy the signing and not to add a headless
  browser. The plan is to ask the Tender Board for an open-data feed or for
  permission. Do not work around the hash without a new decision from the
  user.
- **In-process list** `viewFlag=InProcessTenders` ("المفتوحة", bids opened):
  collected as `status="opened"`, `in_process_pages` pages (default 10). Same
  GET, paging, `hidMax` guard and columns as the new list, except the dates
  cell holds the actual opening time (`DD-MM-YYYY HH:MM`), kept in
  `extra["opened_at"]`; `closing` is empty. Newest openings first, about half
  a day per page, so 10 pages cover about a week. About 423 pages in all.
  No winner and no award value. A tender keeps its id when it moves from the
  new list to this one, so its stored row changes status to `opened`.
- Currency: OMR. A full run is about 41 requests (about 3 minutes at a
  1-second delay).

## Kuwait CAPT — Kuwait (`sources/kuwait_capt.py`)

- Owner: Central Agency for Public Tenders (CAPT). Base: `https://capt.gov.kw`
  (`www.` serves the same site). The root redirects to `/ar/`.
- `robots.txt` is empty (HTTP 200, 0 bytes): allows all. The open list is
  public, no login. Only the tender documents (كراسة الشروط) and "buy tender"
  need a supplier login; the source does not touch them.
- No TLS problems with the default `PoliteClient`.
- Read as server-rendered HTML (Django, `django-el-pagination`).
- **List:** "مناقصات مطروحة" = `GET /ar/tenders/opening-tenders/?page={page}`,
  10 tenders a page, about 5 pages (50 tenders on 2026-11-23). An English
  copy exists at `/en/...` with the same Arabic data.
- **Paging trap:** past the last page the portal serves page 1 again, so
  paging stops when a page brings no unseen key.
- **Row:** each tender is a visible `.content-box` summary (number, request
  date, buyer, subject) followed by a hidden `.content-box.tender-info` panel
  with all fields. The source reads only the panel: `.detail-list ul`, each
  `ul` = `li` label + `li` value. Labels: `الرقم`, `الجهة`, `الموضوع`,
  `تاريخ الطلب` (published), `اخر موعد للعطاء` (closing, no hamza on اخر),
  `النوع` (always `عامة` so far), `العروض البديلة`, `التجزئة`, `ملاحظات`
  (brief), `السعر` (doc fee), `التأمين` (bond).
- **No numeric id.** The tender number repeats across buyers (`1/2026/2027`),
  so `source_id` is `ministry_code:tender_no`. The ministry code is in the
  "buy" button `data-ministry-code`, and also at the end of the
  `data-popup-url` (`...--30`).
- **Per-tender link:** the list filters by
  `?ministry_code=30&tender_no=2/2026/2027` (URL-encoded) and then shows only
  that tender. `lead.url` uses this.
- Tender numbers that start with `ممارسة` are "practices" (a smaller,
  limited procurement); the source sets `tender_type` to `ممارسة` for them.
- **Dates** are Arabic month names: `نوفمبر 22, 2026` (Month D, YYYY).
- **Amounts:** `1000.000 د.ك`, `15,000.000 د.ك` (KWD, 3 decimals). The source
  keeps `1,000` / `15,000`.
- No category or activity on the list, so scoring uses title and notes only.
  No detail pages are fetched. A full run is about 6 requests.
- Other public lists, not collected yet: `pre-tenders` (الطرح المسبق),
  `closing-tenders` (فض العطاءات, bid opening), `winning-bids` (الترسيات),
  `postponement` (تأجيل المناقصات), `qualifications`, `warranties`.

## Bahrain Tender Board — Bahrain (`sources/bahrain_tender_board.py`)

- Owner: Tender Board, Kingdom of Bahrain. Base: `https://www.tenderboard.gov.bh`.
  The supplier e-tendering system (`etendering.tenderboard.gov.bh`) needs
  registration; the source does not use it.
- No `robots.txt`: `/robots.txt` returns the site's HTML "not found" page
  with HTTP 200. The current tenders list is public, no login.
- No TLS problems with the default `PoliteClient`.
- **List:** `/Tenders/PublicTenders/` loads its rows with JavaScript from two
  ASP.NET page methods. Both are `POST` with a JSON body, on
  `/Templates/TenderBoardWebService.aspx/`:
  `GetCurrentPublicTenderPageCount` returns `{"d": 47}` and
  `GetCurrentPublicTenderByPage` returns `{"d": "<html rows>"}`. The body is
  the page's filters with nothing selected (`ministry: "0"`,
  `publicTenderOnly: "true"`, `auctionOnly: "true"`, ...) plus `Page`
  (`"-1"` for the count, else 1-based). All values are strings.
  The source sends them with `PoliteClient.post_json` (same wait, TLS,
  headers and retries as a GET).
- 10 rows a page, newest first, 469 tenders on 2026-11-23. Past the last
  page the service returns an HTML error page, not JSON. The source reads the
  page count first and stops there.
- **Row:** `div.rows` with `div.column[data-label=...]` cells:
  `No./Tender Subject` (an `a` to the detail page; the `span` inside holds
  the purchasing authority's ref no, the rest is the title), `Tender Type`
  (`Internal` / `External`), `Purchasing Authority`, `Publish Date`,
  `Purchase Before`, `Closing Date`.
- The id is the Tender Board number from the link's `id=` query, decoded:
  `581/2026/BTB (MTT/PMA/02/2026)`.
- Dates are not consistent: `23, Nov,2026` and `08 Dec,2026` in the list,
  `Wednesday,  09 December 2026` on the detail page. One regex reads all.
- **Detail page** `/TenderDetails/?id=...` is a plain public GET. It has
  `Tender Description` (used as `brief`) and a `dl` with `Initial Bond`
  (`BD 4000`), `Tender Fees` (`BD 100`), `Invitation Method`,
  `Contract Duration`, `Opening Date`, bid validity. Fetched only for new
  leads.
- No category on the list or the detail page (the CPV line is commented out
  in the HTML), so scoring uses title and brief.
- **Awarded tenders** (`/Tenders/AwardedTenders/`) are monthly PDF reports
  (up to 16 MB each), not a list. Not collected. `OpenedBids`, `TobeOpened`
  and `ArchivedTenders` are other public pages, not checked yet.
- Currency: BHD. A first run is about 48 list requests plus one detail page
  for each of about 470 tenders (about 9 minutes at a 1-second delay). Daily
  runs fetch details only for new tenders.

## Candidate portals (not built yet)

Check each one with the steps in SKILL.md before you plan work. These notes
are starting points, not verified facts.

- **Bahrain Tender Board**: built, see above. Its awarded list is monthly PDF
  reports only, not collected.
- **QatarEnergy LNG**: not possible. Its site links "Bids" to a GEP SMART
  list at `eu.smart.gep.com/publicrfx/qatargas?oloc=215` (15 active, 433
  closed on 2026-11-23), but `eu.smart.gep.com/robots.txt` is
  `User-agent: * / Disallow: /` (checked 2026-11-23), so do not collect it,
  with or without a headless browser. The list also has no titles, only
  reference, contact and dates. `qatarenergylng.qa` rejects `/robots.txt`
  with a 403 (F5 firewall). Its `/Suppliers/Recently-Awarded-Contracts` page
  lists past awards only. The way in is supplier registration
  (`/Suppliers/New-Contractors-and-Suppliers`).
- **Not possible (login / invitation only)**: QatarEnergy (Mushtaryat,
  JAGGAER; robots.txt disallows `/esop`), Ooredoo, Qatar Airways, QF
  supplier portal.
- **Gulf Times newspaper adverts** — paused 2026-11-23, no OCR engine.
  Semi-government bodies and companies (e.g. Qatar Primary Materials
  Company, tenders AWALIA/TD/2026/43 and /44 on 2026-11-23) advertise
  tenders that are on no portal.
  - **Access:** `https://www.gulf-times.com/pdfs` lists the daily PDFs as
    `div.pdf-item` (`.pdf-title` = Main / Sport / Business) linking
    `/gulftimes/uploads/pdf/YYYY/MM/DD/<section>-YYYYMMDD-1-<ts>.pdf?ts=<ts>`.
    robots.txt allows `/pdfs` and the uploads, with `Crawl-delay: 2` for all
    agents. Main is about 18 MB and 12 pages; Business about 4 MB and 3 pages.
    `/classified` PDFs have a text layer but held only jobs and rentals.
  - **Adverts are scanned images** with no text layer. Layout: a boxed table
    (Tender No., Subject, document fee, bond, offer type, closing date), terms
    below, the buyer's contact block at the bottom. Needs OCR.
  - **Why paused:** Homebrew has no prebuilt Tesseract for macOS 26 on Intel,
    and compiling fails because the Command Line Tools are too old. Docker is
    not installed. The Python OCR packages need onnxruntime or PyTorch, which
    have no build for Python 3.14 on Intel macOS.
  - **To resume:**
    - Update the Command Line Tools, then `brew install tesseract`, or use
      Claude vision with an API key.
    - OCR in the client (`get_pdf_ocr`, pdftoppm + tesseract per page), so
      fixtures record text and CI needs no OCR tools.
    - Cache OCR per issue under `data/`: one issue a day, but four checks a day.
    - Make the source exempt from the "0 tenders = failed" alert in
      `cli.collect`, since a day with no adverts is normal.
    - Docker needs `tesseract-ocr` and `poppler-utils`.
  - Al Sharq (advert pages are images), The Peninsula (no tenders seen) and
    Al Raya (its advert lists sit under `/api/*`, which robots.txt disallows)
    were also checked and are not worth building.
- **QAFAC** (Qatar Fuel Additives, `https://www.qafac.com.qa/tenders/`):
  checked 2026-11-23, not built because it is rarely used. Public WordPress
  page, robots.txt allows all. Internet Archive snapshots: 404 in 2025-07,
  4 tenders in 2025-08 (all industrial, none IT), then "No valid tenders
  available" in 2025-09, 2025-12, 2026-01 and on 2026-11-23. The page says
  tenders also go in local Arabic and English newspapers. Format when used
  (2025-08): one `<table>` with "Tender Name" and a "Download PDF" link per
  row; the PDF format is unknown. Build it only if the page lists tenders
  again; the QAFCO source is a starting point.
- **Not needed (on Monaqasat)**: Kahramaa (JSON service, every row has a
  Monaqasat number), Ashghal (HTML, all open tenders on Monaqasat), HMC.
- **UAE**: federal (`mof.gov.ae` / Digital Procurement Platform) and
  per-emirate portals (Abu Dhabi, Dubai eSupply). Many need registration.
