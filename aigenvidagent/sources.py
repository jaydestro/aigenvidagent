"""Bounded public HTML intake; source text is evidence, not instructions."""

from html.parser import HTMLParser
import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
import uuid

from .schema import BriefError
from .storage import save


MAX_BYTES = 1024 * 1024
TIMEOUT = 10
MAX_REDIRECTS = 4


def public_url(url):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        if (
            parts.scheme != "https"
            or not host
            or parts.port not in {None, 443}
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or any(ord(char) <= 32 for char in url)
            or "\\" in url
            or "%" in host
            or host.endswith(".")
            or host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit(("https", authority, parts.path or "/", "", ""))
    except (ValueError, UnicodeError, AttributeError) as error:
        raise BriefError(
            "Source must be public HTTPS on port 443, "
            "without userinfo, query tokens or fragments"
        ) from error


def public_addresses(host, timeout=TIMEOUT):
    results = queue.Queue(maxsize=1)

    def resolve():
        try:
            results.put(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
        except OSError as error:
            results.put(error)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        resolved = results.get(timeout=max(timeout, 0.001))
        if isinstance(resolved, OSError):
            raise resolved
        addresses = list(dict.fromkeys(row[4][0] for row in resolved))
        if not addresses or any(
            not ipaddress.ip_address(value).is_global for value in addresses
        ):
            raise BriefError(
                "Source DNS includes a private or non-public address"
            )
        return addresses
    except BriefError:
        raise
    except queue.Empty:
        raise BriefError(
            "Public source DNS lookup timed out; stage readable text locally"
        ) from None
    except (OSError, ValueError) as error:
        raise BriefError("Cannot resolve a public source address") from error


class PublicConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(
            host, timeout=timeout, context=ssl.create_default_context()
        )
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(
                raw, server_hostname=self.host
            )
        except Exception:
            raw.close()
            raise


class ReadableHTML(HTMLParser):
    blocks = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "td"}
    ignored = {
        "script",
        "style",
        "nav",
        "footer",
        "header",
        "form",
        "iframe",
        "noscript",
        "template",
        "svg",
    }
    void = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.current = []
        self.kind = "text"
        self.rows = []
        self.title = []

    def flush(self):
        text = " ".join("".join(self.current).split())
        if text:
            self.rows.append({"kind": self.kind, "text": text})
        self.current = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        hidden = (
            any(entry[1] for entry in self.stack)
            or tag in self.ignored
            or "hidden" in attributes
            or attributes.get("aria-hidden") == "true"
        )
        if tag in self.blocks and not hidden:
            self.flush()
            self.kind = tag
        if tag == "br":
            self.current.append(" ")
        if tag not in self.void:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.blocks:
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(entry[1] for entry in self.stack):
            return
        if any(entry[0] == "title" for entry in self.stack):
            self.title.append(data)
        elif not any(entry[0] == "head" for entry in self.stack):
            self.current.append(data)


def fetch_html(url):
    original = public_url(url)
    current = original
    deadline = time.monotonic() + TIMEOUT
    try:
        for redirect in range(MAX_REDIRECTS + 1):
            current = public_url(current)
            parts = urlsplit(current)
            addresses = public_addresses(
                parts.hostname, deadline - time.monotonic()
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            connection = PublicConnection(
                parts.hostname, addresses[0], remaining
            )
            try:
                connection.request(
                    "GET",
                    parts.path,
                    headers={
                        "User-Agent": "aigenvidagent-source-intake/1",
                        "Accept": "text/html",
                        "Accept-Encoding": "identity",
                    },
                )
                transport = connection.sock
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location or redirect == MAX_REDIRECTS:
                        raise BriefError(
                            "Source redirect limit or missing Location"
                        )
                    current = public_url(urljoin(current, location))
                    continue
                if response.status != 200:
                    raise BriefError(
                        f"Source returned HTTP {response.status}; "
                        "stage readable text locally"
                    )
                content_type = response.getheader("Content-Type", "")
                if content_type.split(";", 1)[0].strip().lower() not in {
                    "text/html",
                    "application/xhtml+xml",
                }:
                    raise BriefError(
                        "Source is not readable HTML; "
                        "no file downloads are performed"
                    )
                if response.getheader(
                    "Content-Encoding", "identity"
                ).lower() not in {"identity", ""}:
                    raise BriefError(
                        "Compressed source responses are not accepted"
                    )
                length = response.getheader("Content-Length")
                if length and int(length) > MAX_BYTES:
                    raise BriefError("Source exceeds the HTML byte limit")
                body = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    if transport is not None:
                        transport.settimeout(remaining)
                    chunk = response.read1(
                        min(65536, MAX_BYTES + 1 - len(body))
                    )
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise BriefError("Source exceeds the HTML byte limit")
                charset = response.headers.get_content_charset() or "utf-8"
                document = bytes(body).decode(charset, errors="replace")
            finally:
                connection.close()
            parser = ReadableHTML()
            parser.feed(document)
            parser.flush()
            if not parser.rows:
                raise BriefError(
                    "No readable public HTML text; "
                    "provide local text or a canonical brief"
                )
            return {
                "url": original,
                "resolved_url": current,
                "title": " ".join("".join(parser.title).split()),
                "blocks": parser.rows,
                "trust": "untrusted_source_material_not_instructions",
                "bytes_read": len(body),
            }
    except (
        OSError,
        http.client.HTTPException,
        UnicodeError,
        LookupError,
        ValueError,
    ) as error:
        if isinstance(error, BriefError):
            raise
        raise BriefError(
            "Public HTML fetch failed or timed out; "
            "provide a local readable source instead"
        ) from None


def archive(store, identity, url):
    dossier = fetch_html(url)
    folder = store.project(identity) / "sources" / uuid.uuid4().hex
    save(folder / "source.json", dossier, exclusive=True)
    paragraphs = [
        row["text"]
        for row in dossier["blocks"]
        if row["kind"] in {"p", "li", "blockquote"}
    ]
    draft = "\n\n".join(
        ([dossier["title"]] if dossier["title"] else [])
        + (paragraphs or [row["text"] for row in dossier["blocks"]])[:6]
    )
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "draft.txt").open("x", encoding="utf-8") as stream:
        stream.write(draft + "\n")
    return {
        "url": dossier["url"],
        "resolved_url": dossier["resolved_url"],
        "title": dossier["title"],
        "path": (folder / "source.json").relative_to(store.root).as_posix(),
        "draft_path": (folder / "draft.txt")
        .relative_to(store.root)
        .as_posix(),
        "trust": dossier["trust"],
    }
