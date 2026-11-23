"""Upwork freelance jobs posted by clients in Qatar (or other countries set in config). Upwork's own
visitor GraphQL search, the one its public job search page calls. No Upwork account is needed.

NOT ROBOTS.TXT-COMPLIANT. Upwork's robots.txt disallows job search, and its Cloudflare front blocks plain
HTTP clients. This source is the one exception to the project rule: it reads with curl_cffi, which sends
a browser's TLS fingerprint, and gets a visitor token the same way the page does. The approach comes from
github.com/omkarcloud/upwork-scraper (MIT). The user chose to turn it on and accepts that Upwork may block
it at any time; `"enabled": false` in config.json turns it off.

Jobs have no closing date, so `closing` stays empty. The budget is in USD.
"""

import json
import time

from tender_radar.lead import Lead

SITE = "https://www.upwork.com"
GRAPHQL_URL = SITE + "/api/graphql/v1?alias=visitorJobSearch"
# A public page that sets the visitor token cookie the job search GraphQL call needs.
TOKEN_PAGE = SITE + "/nx/search/talent/?q=design"
TOKEN_COOKIE = "UniversalSearchNuxt_vt"
# Safari's TLS fingerprint passes Cloudflare where Chrome's is sometimes challenged.
IMPERSONATIONS = ("safari", "chrome")
PAGE_SIZE = 50

JOB_SEARCH = """
query VisitorJobSearch($requestVariables: VisitorJobSearchV1Request!) {
  search { universalSearchNuxt { visitorJobSearchV1(request: $requestVariables) {
    paging { total offset count }
    results {
      id title description
      ontologySkills { prefLabel }
      jobTile { job {
        id ciphertext: cipherText jobType contractorTier publishTime
        hourlyBudgetMin hourlyBudgetMax weeklyRetainerBudget
        fixedPriceAmount { isoCurrencyCode amount }
        hourlyEngagementDuration { label }
        fixedPriceEngagementDuration { label }
      } }
    }
  } } }
}
"""

JOB_TYPES = {"HOURLY": "Upwork hourly job", "FIXED": "Upwork fixed-price job"}
EXPERIENCE = {"EntryLevel": "entry", "IntermediateLevel": "intermediate", "ExpertLevel": "expert"}


class UpworkClient:
    """The browser-like HTTP client Upwork needs. Same post_json shape as PoliteClient, so the test
    recorder can record and replay it."""

    def __init__(self, delay: float = 1.0, timeout: float = 60, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._attempt = 0
        self._session = None
        self._last_call = 0.0

    def post_json(self, url: str, body: dict, **kwargs) -> dict:
        last_error = None
        for _ in range(self.retries):
            try:
                return self._post(url, body)
            except Exception as error:  # blocked or token expired: a fresh session gets a new token
                last_error = error
                self._session = None
                time.sleep(2)
        raise last_error

    def _post(self, url: str, body: dict) -> dict:
        session = self._session or self._new_session()
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": SITE,
            "referer": SITE + "/nx/search/jobs/",
            "authorization": f"Bearer {session.cookies.get(TOKEN_COOKIE)}",
        }
        self._wait()
        response = session.post(url, headers=headers, data=json.dumps(body), timeout=self.timeout)
        if response.status_code != 200:
            raise ConnectionError(f"Upwork answered HTTP {response.status_code}")
        answer = response.json()
        if answer.get("errors"):
            raise ValueError(f"Upwork GraphQL error: {answer['errors'][0].get('message', '')[:200]}")
        return answer

    def _new_session(self):
        from curl_cffi import requests as curl  # only this source needs it

        impersonate = IMPERSONATIONS[self._attempt % len(IMPERSONATIONS)]
        self._attempt += 1
        session = curl.Session(impersonate=impersonate)
        self._wait()
        session.get(TOKEN_PAGE, timeout=self.timeout)
        if not session.cookies.get(TOKEN_COOKIE):
            raise ConnectionError("Upwork set no visitor token (blocked by Cloudflare?)")
        self._session = session
        return session

    def _wait(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_call = time.monotonic()


class UpworkSource:
    name = "upwork"
    own_client = UpworkClient  # cli and the test recorder pass this client instead of PoliteClient
    may_be_empty = True  # a small country can have no open jobs on a day

    def __init__(self, client, settings: dict):
        self.client = client
        self.countries = settings.get("client_countries", ["Qatar"])
        self.max_pages = settings.get("max_pages", 4)

    def collect(self, known_keys: dict) -> list[Lead]:
        leads, seen = [], set()
        for country in self.countries:
            found = [lead for lead in self._collect_country(country) if lead.key not in seen]
            seen.update(lead.key for lead in found)
            leads += found
            print(f"  upwork/{country}: {len(found)} jobs")
        return leads

    def _collect_country(self, country: str) -> list[Lead]:
        leads = []
        for page in range(self.max_pages):
            request = {
                "sort": "recency",
                "highlight": False,
                "paging": {"offset": page * PAGE_SIZE, "count": PAGE_SIZE},
                "location": [country],
            }
            body = {"query": JOB_SEARCH, "variables": {"requestVariables": request}}
            answer = self.client.post_json(GRAPHQL_URL, body)
            results = answer["data"]["search"]["universalSearchNuxt"]["visitorJobSearchV1"]["results"] or []
            leads += [lead for result in results if (lead := self._parse_job(result, country))]
            if len(results) < PAGE_SIZE:
                break
        return leads

    def _parse_job(self, result: dict, country: str) -> Lead | None:
        job = (result.get("jobTile") or {}).get("job") or {}
        job_id = str(job.get("id") or result.get("id") or "")
        ciphertext = job.get("ciphertext") or (f"~02{job_id}" if job_id else "")
        if not job_id or not result.get("title"):
            return None
        duration = job.get("hourlyEngagementDuration") or job.get("fixedPriceEngagementDuration") or {}
        return Lead(
            source=self.name,
            source_id=job_id,
            country=country,
            title=_clean(result["title"]),
            url=f"{SITE}/jobs/{ciphertext}",
            buyer=f"Upwork client ({country})",
            category=_skills(result),
            tender_type=JOB_TYPES.get(job.get("jobType"), "Upwork job"),
            published=(job.get("publishTime") or "")[:10],
            currency="USD",
            brief=_clean(result.get("description")),
            extra={
                "budget": _budget(job),
                "experience": EXPERIENCE.get(job.get("contractorTier"), ""),
                "duration": duration.get("label") or "",
            },
        )


def _skills(result: dict) -> str:
    names = (skill.get("prefLabel") for skill in result.get("ontologySkills") or [])
    return ", ".join(name for name in names if name)


def _budget(job: dict) -> str:
    """'500' for a fixed price, '25-50/hr' for an hourly range, '' when the client gave none."""
    if job.get("jobType") == "FIXED":
        amount = (job.get("fixedPriceAmount") or {}).get("amount")
        return _number(amount) if amount and float(amount) else ""
    low, high = job.get("hourlyBudgetMin"), job.get("hourlyBudgetMax")
    if not (low or high):
        return ""
    return f"{_number(low)}-{_number(high)}/hr" if low and high else f"{_number(low or high)}/hr"


def _number(value) -> str:
    return f"{float(value):g}"


def _clean(text) -> str:
    return " ".join((text or "").split())
