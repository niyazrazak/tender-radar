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
- Currency: QAR.

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

## Candidate portals (not built yet)

Check each one with the steps in SKILL.md before you plan work. These notes
are starting points, not verified facts.

- **Kuwait CAPT** (Central Agency for Public Tenders, `capt.gov.kw`):
  publishes tenders and the official gazette.
- **Bahrain Tender Board** (`tenderboard.gov.bh`): public list of tenders.
- **Qatar entities with their own portals**: QatarEnergy, Kahramaa, Ashghal,
  Hamad Medical Corporation. Some need a supplier registration, so check for
  a login first.
- **UAE**: federal (`mof.gov.ae` / Digital Procurement Platform) and
  per-emirate portals (Abu Dhabi, Dubai eSupply). Many need registration.
