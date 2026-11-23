import ssl
import time
from io import BytesIO
from pathlib import Path

import certifi
import requests
from pypdf import PdfReader
from requests.adapters import HTTPAdapter

INTERMEDIATES = Path(__file__).parent / "certs" / "intermediates.pem"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class PoliteClient:
    """HTTP session that waits between requests and retries transient failures."""

    def __init__(self, delay: float = 1.0, timeout: float = 30, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.mount("https://", GovPortalTLSAdapter())
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_call = 0.0

    def get_text(self, url: str, **kwargs) -> str:
        return self._get(url, **kwargs).text

    def get_json(self, url: str, **kwargs) -> dict:
        headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json", **kwargs.pop("headers", {})}
        return self._get(url, headers=headers, **kwargs).json()

    def post_json(self, url: str, body: dict, **kwargs) -> dict:
        """POST a JSON body and read JSON back, with the same wait and retries as a GET."""
        headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json", **kwargs.pop("headers", {})}
        return self._request("post", url, json=body, headers=headers, **kwargs).json()

    def get_pdf_text(self, url: str, **kwargs) -> str:
        """Text of a PDF. Read here, not in a source, so test fixtures record text, not binary files."""
        reader = PdfReader(BytesIO(self._get(url, **kwargs).content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def read_pdf(self, url: str, reader, **kwargs):
        """Downloads a PDF and returns `reader(file name, bytes)`. Done here, like get_pdf_text, so test
        fixtures record what was read from the PDF, not the file (a newspaper issue is about 18 MB)."""
        return reader(url.split("?")[0].rsplit("/", 1)[-1], self._get(url, **kwargs).content)

    def _get(self, url: str, **kwargs) -> requests.Response:
        return self._request("get", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error = None
        for attempt in range(self.retries):
            self._wait()
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                time.sleep(2 * (attempt + 1))
        raise last_error

    def _wait(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_call = time.monotonic()


class GovPortalTLSAdapter(HTTPAdapter):
    """TLS settings that some GCC government portals need. Verification stays on.

    - Monaqasat only offers plain-RSA ciphers, which Python's default list drops,
      so its firewall closes the connection. OpenSSL's DEFAULT list still has them.
    - Monaqasat does not send its intermediate certificate, so we ship it.
    """

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_verify_locations(INTERMEDIATES)
        context.set_ciphers("DEFAULT")
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)
