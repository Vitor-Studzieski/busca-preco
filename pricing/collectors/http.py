import json
import re
import socket
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from http.client import HTTPException, HTTPSConnection
from ipaddress import ip_address
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener


class CollectionError(ValueError):
    def __init__(self, message: str, *, status: int | None = None, temporary=False):
        super().__init__(message)
        self.status = status
        self.temporary = temporary or status in {408, 429} or (status is not None and status >= 500)


CONFIANCA_PRODUCT_PATH = re.compile(r"p/((?:[a-zA-Z0-9_-]|%[a-fA-F0-9]{2})+)/([a-zA-Z0-9_-]+)")
STOREFRONTS = {
    "pompeia": (
        {"onlinesim.com.br", "www.onlinesim.com.br"},
        {"/pompeia"},
        re.compile(r"(?:details/[0-9]{1,32}|search/(?:[A-Za-z0-9._~-]|%[a-fA-F0-9]{2})+)"),
    ),
    "lider": (
        {"smlider.com.br", "www.smlider.com.br"},
        {"/1", "/2"},
        re.compile(r"produto/m/[a-zA-Z0-9_-]+"),
    ),
    "tauste": (
        {"tauste.com.br", "www.tauste.com.br"},
        {"/marilia"},
        re.compile(r"[a-zA-Z0-9_-]+\.html"),
    ),
    "confianca": (
        {"confianca.com.br", "www.confianca.com.br"},
        {"/marilia"},
        CONFIANCA_PRODUCT_PATH,
    ),
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEADLINE = ContextVar("market_deadline", default=None)
LAST_REQUEST = {}
REQUEST_LOCK = Lock()


def pace_http(host, deadline):
    with REQUEST_LOCK:
        now = monotonic()
        earliest = LAST_REQUEST.get(host, now)
        if deadline is not None and earliest >= deadline:
            raise CollectionError("A loja não respondeu no tempo disponível.", temporary=True)
        delay = max(0, earliest - now)
        LAST_REQUEST[host] = now + delay + 0.2
    if delay:
        sleep(delay)


def connect_public(address, timeout=None, source_address=None):
    host, port = address
    resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not resolved or any(not ip_address(row[4][0].split("%")[0]).is_global for row in resolved):
        raise CollectionError("O endereço da loja não resolveu para um destino público.")
    failure = None
    for family, kind, protocol, _, target in resolved:
        sock = socket.socket(family, kind, protocol)
        try:
            deadline = DEADLINE.get()
            sock.settimeout(timeout if deadline is None else min(timeout, remaining_time(deadline)))
            if source_address:
                sock.bind(source_address)
            sock.connect(target)
            return sock
        except OSError as error:
            sock.close()
            failure = error
        except CollectionError:
            sock.close()
            raise
    raise failure or OSError("Endereço de loja indisponível")


class PublicHTTPSConnection(HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = connect_public


class PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        return self.do_open(PublicHTTPSConnection, req, context=self._context)



@contextmanager
def storefront_deadline(deadline):
    token = DEADLINE.set(deadline)
    try:
        yield
    finally:
        DEADLINE.reset(token)


def remaining_time(deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise CollectionError("A loja não respondeu no tempo disponível.", temporary=True)
    return remaining


def read_html(response, deadline):
    if deadline is None:
        return response.read(MAX_RESPONSE_BYTES + 1)
    data = bytearray()
    while len(data) <= MAX_RESPONSE_BYTES:
        remaining_time(deadline)
        part = response.read1(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - len(data)))
        if not part:
            break
        data.extend(part)
    return data


def split_storefront_url(url: str, allowed_hosts: set[str]):
    if not isinstance(url, str) or not url or len(url) > 2048 or re.search(r"[\s\x00-\x1f\x7f\\]", url):
        raise CollectionError("O endereço precisa ser uma URL HTTPS válida.")
    try:
        parts = urlsplit(url)
    except ValueError as error:
        raise CollectionError("O endereço precisa ser uma URL HTTPS válida.") from error
    if parts.scheme != "https" or parts.netloc.lower() not in allowed_hosts:
        raise CollectionError("O endereço precisa pertencer à loja cadastrada.")
    return parts


def storefront_config(retailer: str):
    if retailer not in STOREFRONTS:
        raise CollectionError("Rede sem coletor cadastrado.")
    return STOREFRONTS[retailer]


def validate_store_url(retailer: str, url: str, *, store_path: str = "") -> str:
    allowed_hosts, allowed_paths, _ = storefront_config(retailer)
    store = split_storefront_url(url, allowed_hosts)
    path = store.path.removesuffix("/")
    if path not in allowed_paths or (store_path and path != store_path):
        raise CollectionError("O endereço precisa pertencer à unidade cadastrada.")
    return urlunsplit((store.scheme, store.netloc.lower(), store.path, "", ""))


def validate_product_url(retailer: str, store_url: str, product_url: str) -> str:
    allowed_hosts, _, product_path = storefront_config(retailer)
    store = urlsplit(validate_store_url(retailer, store_url))
    product = split_storefront_url(product_url, allowed_hosts)
    store_path = store.path.removesuffix("/")
    prefix = f"{store_path}/"
    path = product.path.removesuffix("/")
    if not path.startswith(prefix):
        raise CollectionError("O endereço do produto precisa pertencer à unidade cadastrada.")
    match = product_path.fullmatch(path.removeprefix(prefix))
    if not match:
        raise CollectionError("Informe o endereço público da página individual do produto.")
    normalized_path = product.path
    if retailer == "confianca":
        try:
            slug = unquote(match[1], errors="strict")
        except UnicodeError as error:
            raise CollectionError("O endereço do produto tem um nome inválido.") from error
        if not re.fullmatch(r"[\w-]+", slug):
            raise CollectionError("O endereço do produto tem um nome inválido.")
        trailing_slash = "/" if product.path.endswith("/") else ""
        normalized_path = f"{prefix}p/{quote(slug)}/{match[2]}{trailing_slash}"
    return urlunsplit((product.scheme, product.netloc.lower(), normalized_path, "", ""))


class StorefrontRedirectHandler(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def __init__(self, validate_url: Callable[[str], str]):
        self.validate_url = validate_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        deadline = DEADLINE.get()
        if deadline is not None:
            remaining_time(deadline)
        url = self.validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, url)


def fetch_html(page_url: str, validate_url: Callable[[str], str]) -> tuple[str, str]:
    page_url = validate_url(page_url)
    deadline = DEADLINE.get()
    opener = build_opener(ProxyHandler({}), StorefrontRedirectHandler(validate_url), PublicHTTPSHandler())
    request = Request(
        page_url,
        headers={"Accept": "text/html", "User-Agent": "Pompeia-PriceMonitor/0.1"},
    )
    try:
        return open_html(opener, request, validate_url, deadline)
    except CollectionError as error:
        if (deadline is None or error.status not in {500, 502, 503, 504}
                or deadline - monotonic() < 1.5):
            raise
        sleep(0.2)
        return open_html(opener, request, validate_url, deadline)


def fetch_json(page_url: str, validate_url: Callable[[str], str], *, body: dict,
               headers: dict[str, str]) -> dict:
    """Fetch a bounded JSON response from a validated public HTTPS endpoint."""
    page_url = validate_url(page_url)
    deadline = DEADLINE.get()
    opener = build_opener(ProxyHandler({}), StorefrontRedirectHandler(validate_url), PublicHTTPSHandler())
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "BuscaPreco/0.1",
        **headers,
    }
    request = Request(page_url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers=request_headers, method="POST")
    pace_http(urlsplit(request.full_url).hostname, deadline)
    timeout = 12 if deadline is None else min(5, remaining_time(deadline))
    try:
        with opener.open(request, timeout=timeout) as response:
            validate_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise CollectionError("A loja não retornou dados de preço em JSON.")
            data = read_html(response, deadline)
            if len(data) > MAX_RESPONSE_BYTES:
                raise CollectionError("A resposta da loja excedeu o tamanho aceito.")
            try:
                value = json.loads(data.decode(response.headers.get_content_charset() or "utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise CollectionError("A loja retornou dados de preço inválidos.") from error
            if not isinstance(value, dict):
                raise CollectionError("A loja retornou dados de preço inválidos.")
            return value
    except HTTPError as error:
        if error.code in {401, 403, 429}:
            message = f"A loja limitou ou recusou o acesso (HTTP {error.code})."
        else:
            message = f"A loja respondeu com HTTP {error.code}."
        error.close()
        raise CollectionError(message, status=error.code) from error
    except TimeoutError as error:
        raise CollectionError("A loja não respondeu no tempo disponível.", temporary=True) from error
    except (OSError, HTTPException, LookupError) as error:
        raise CollectionError("Não foi possível abrir o catálogo da loja.", temporary=True) from error


def open_html(opener, request, validate_url, deadline):
    pace_http(urlsplit(request.full_url).hostname, deadline)
    timeout = 12 if deadline is None else min(5, remaining_time(deadline))
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = validate_url(response.geturl())
            if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
                raise CollectionError("A loja não retornou uma página HTML.")
            data = read_html(response, deadline)
            if len(data) > MAX_RESPONSE_BYTES:
                raise CollectionError("A página da loja excedeu o tamanho aceito.")
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace"), final_url
    except HTTPError as error:
        if error.code in {401, 403, 429}:
            message = f"A loja limitou ou recusou o acesso (HTTP {error.code})."
        else:
            message = f"A loja respondeu com HTTP {error.code}."
        error.close()
        raise CollectionError(message, status=error.code) from error
    except TimeoutError as error:
        raise CollectionError("A loja não respondeu no tempo disponível.", temporary=True) from error
    except (OSError, HTTPException, LookupError) as error:
        raise CollectionError("Não foi possível abrir o catálogo da loja.", temporary=True) from error
