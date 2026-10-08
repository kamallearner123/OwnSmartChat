import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

MAX_CHARS = 20000
MAX_DOWNLOAD = 5 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024


class ToolError(Exception):
    pass


def _check_url(url):
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("Only http(s) URLs are supported.")
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 80)}
    except socket.gaierror:
        raise ToolError("Could not resolve host.")
    # Block loopback/private targets so the server can't be used to reach internal services
    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if not ip.is_global:
            raise ToolError("URLs pointing to private or local addresses are not allowed.")


def _truncate(text):
    text = text.strip()
    return text[:MAX_CHARS], len(text) > MAX_CHARS


def scrape_url(url):
    headers = {"User-Agent": "Mozilla/5.0 (MyOwnLLM scraper)"}
    with httpx.Client(timeout=15, headers=headers, follow_redirects=False) as client:
        for _ in range(5):
            _check_url(url)
            try:
                with client.stream("GET", url) as resp:
                    if resp.is_redirect:
                        url = urljoin(url, resp.headers.get("location", ""))
                        continue
                    if resp.status_code >= 400:
                        raise ToolError(f"Server returned HTTP {resp.status_code}.")
                    data = b""
                    for chunk in resp.iter_bytes():
                        data += chunk
                        if len(data) > MAX_DOWNLOAD:
                            break
                    encoding = resp.encoding or "utf-8"
                    break
            except httpx.HTTPError as exc:
                raise ToolError(f"Request failed: {exc}")
        else:
            raise ToolError("Too many redirects.")

    soup = BeautifulSoup(data.decode(encoding, errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else url
    lines = (ln.strip() for ln in soup.get_text("\n").splitlines())
    text, truncated = _truncate("\n".join(ln for ln in lines if ln))
    return {"title": title, "text": text, "truncated": truncated}


def parse_pdf(file):
    if file.size > MAX_PDF_BYTES:
        raise ToolError("PDF is larger than 20 MB.")
    try:
        reader = PdfReader(file)
        if reader.is_encrypted:
            raise ToolError("Encrypted PDFs are not supported.")
        pages = []
        total = 0
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            total += len(pages[-1])
            if total > MAX_CHARS:
                break
        page_count = len(reader.pages)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Could not read PDF: {exc}")
    text, truncated = _truncate("\n\n".join(pages))
    if not text:
        raise ToolError("No extractable text found (scanned PDF?).")
    return {"title": file.name, "text": text, "truncated": truncated or len(pages) < page_count, "pages": page_count}
