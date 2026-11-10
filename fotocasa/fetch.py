"""fotocasa transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no API key. Egress: one sticky exit per thread
session (config.fotocasa_proxy(), knob FOTOCASA_EXIT); a retryable failure
drops the session, so the retry rides a fresh exit.

Every surface answered 200 to curl_cffi chrome from the pod's own IP, from
2/2 datacenter proxy ports and 2/2 Spanish residential proxy ports (pod
probe 2026-11-07, scrapers-patchright-depl-74fddd498d-rfmk6; table in
config.py's fotocasa block), so the direct tier is the default. The
Imperva wall that the competition fights guards only the Android app API,
which this module never touches.

Upstream surfaces:

  SEARCH   GET web.gw.fotocasa.es/v2/propertysearch/search?combinedLocationIds=
           724,14,28,173,0,28079,0,0,0&transactionTypeId=1&propertyTypeId=2&
           pageNumber=N&size=30..400&sortType=…&sortOrderDesc=…&<filters>
           -> JSON {count, realEstates[], promotionClassifieds[], breadcrumb,
           hrefLang, client}. A page past the end answers rows again
           (wraps), so api.py stops at ceil(count / size). A malformed
           combinedLocationIds is silently treated as all of Spain, so the
           schema validates the shape first. clientId=… narrows to one
           agency and adds its `client` block; an unknown one answers
           count 0 and client null.
  SUGGEST  GET search.gw.fotocasa.es/v1/suggest?query=<text>&culture=es-ES
           -> JSON list of places (the param must be `query`: `text`/`q` are 400).
  LIST     GET www.fotocasa.es/es/<tx>/<type>/<loc>/<zone>/l[/N]?<filters>
           and …/<type>/area/<street-slug>/l[/N] — server-rendered pages
           carrying <script id="__initial_props__"> with the same search
           answer (resultsV2.items, 30 a page, 333 pages at most); the only
           way to search a street / urbanisation slug or a pasted link. An
           unknown area slug is HTTP 404.
  DETAIL   GET www.fotocasa.es/es/comprar/vivienda/<any>/<any>/<id>/d — any
           slug redirects to the canonical one; the bare …/vivienda/<id>/d is
           a 404; a dead id, or a rental id under the sale segment, redirects
           to a list page with ?propertyNotFound (mapped to NotFound here).
  PROMO    GET www.fotocasa.es/es/comprar/obra-nueva/<loc>/<promotionId> —
           a new-development page (unknown id: 404).
  AGENCY   GET www.fotocasa.es/es/pro/<slug>/[<tx>/<type>/espana/todas-las-zonas/l[/N]]
           — the minisite (profile + 15 listings a page; unknown slug: 404).
  DIRECTORY GET www.fotocasa.es/buscar-agencias-inmobiliarias/<loc>/<zone>/l?pagina=N
           — 15 agency cards a page; an unknown location or a page past the
           end is an HTTP 200 page with no cards.
  PRICES   GET www.fotocasa.es/es/indice-precio-vivienda/<municipality>/<district|todas-las-zonas>
           — the housing price index (unknown slug: 404; neighbourhoods: 404).

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  FotocasaUpstreamError  transport failure / 5xx            — retryable
  FotocasaBlocked        403 / 429 / Imperva challenge       — retryable
  FotocasaBadRequest     upstream 400                        — never retried
  FotocasaNotFound       dead listing / agency / page        — never retried
"""
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode

import fastjson

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from fotocasa import refs

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 40        # list pages are ~1.5 MB
JSON_TIMEOUT = 30        # size=400 gateway answers are ~3.7 MB

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": refs.SITE,
    "referer": refs.SITE + "/",
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_BLOCK_MARKERS = ("Pardon Our Interruption", "_Incapsula_Resource", "Request unsuccessful. Incapsula",
                  "captcha-delivery.com")
_PROPS_MARKER = 'id="__initial_props__"'


class FotocasaUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class FotocasaBlocked(FotocasaUpstreamError, Blocked):
    """403 / 429 / Imperva challenge where HTML or JSON was expected — retryable."""


class FotocasaBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class FotocasaNotFound(NotFound):
    """Listing / promotion / agency / page does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------

_local = threading.local()


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = config.fotocasa_proxy()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
    return sess


def _drop_session():
    """Close the thread's session: a refused exit must not be reused."""
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _retrying(fn):
    """Run fn() under the shared retry policy (FotocasaUpstreamError only;
    NotFound / BadRequest surface immediately). Each retry drops the
    session, so it leaves through a fresh sticky exit."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except FotocasaUpstreamError as e:
            last = e
            _drop_session()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


# ---- classification ------------------------------------------------------------

def page_title(text):
    match = _TITLE_RE.search(text or "")
    return match.group(1).strip() if match else ""


def is_block_page(text):
    head = (text or "")[:5000]
    return any(marker in head for marker in _BLOCK_MARKERS)


def _classify(resp, label, not_found_ok=False):
    text = resp.text
    status = resp.status_code
    if status in (401, 403, 429) or is_block_page(text):
        raise FotocasaBlocked(f"HTTP {status} (anti-bot) for {label}")
    if status == 404:
        if not_found_ok:
            return text
        raise FotocasaNotFound(f"{label} not found")
    if status == 400:
        raise FotocasaBadRequest(f"fotocasa rejected the request for {label}")
    if status != 200:
        raise FotocasaUpstreamError(f"HTTP {status} for {label}")
    return text


def _url(base, path, query=None):
    url = base + path
    if query:
        url += ("&" if "?" in url else "?") + urlencode(query, doseq=True)
    return url


def _get_json(base, path, query, label):
    def once():
        try:
            resp = _session().get(_url(base, path, query), headers=JSON_HEADERS, timeout=JSON_TIMEOUT)
        except Exception as e:
            raise FotocasaUpstreamError(f"request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label)
        try:
            return fastjson.loads(text)
        except ValueError:
            raise FotocasaBlocked(f"non-JSON answer for {label}: {text[:80]!r}")
    return _retrying(once)


def _get_html(path, query, label, not_found_ok=False):
    """GET a site page, following redirects. Returns (html, final_url,
    status). A redirect onto a list page carrying ?propertyNotFound (a
    dead listing id) raises NotFound; a 404 page too unless `not_found_ok`."""
    def once():
        try:
            resp = _session().get(_url(refs.SITE, path, query), headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT,
                                  allow_redirects=True)
        except Exception as e:
            raise FotocasaUpstreamError(f"request failed: {type(e).__name__}: {e}")
        final_url = str(resp.url or "")
        if "propertyNotFound" in final_url:
            raise FotocasaNotFound(f"{label} not found")
        text = _classify(resp, label, not_found_ok=not_found_ok)
        if "<html" not in text[:3000].lower():
            raise FotocasaBlocked(f"non-HTML answer for {label}: {text[:80]!r}")
        return text, final_url, resp.status_code
    return _retrying(once)


# ---- surfaces ------------------------------------------------------------------

def fetch_search(params):
    """The gateway search JSON for one page of a search (`params` are the
    site's own query names, see api.py)."""
    payload = _get_json(refs.GATEWAY, "/v2/propertysearch/search", params, "property search")
    if not isinstance(payload, dict) or "realEstates" not in payload:
        raise FotocasaUpstreamError("unexpected search payload shape")
    return payload


def fetch_suggest(query, language=refs.DEFAULT_LANGUAGE):
    """The site's location typeahead -> list of place dicts ([] when nothing matches)."""
    payload = _get_json(refs.SEARCH_GATEWAY, "/v1/suggest",
                        {"query": query, "culture": refs.LANGUAGES.get(language, "es-ES")},
                        f"locations matching {query!r}")
    return payload if isinstance(payload, list) else []


def fetch_list_page(path, query=None):
    """A server-rendered search page (plain list or area page). Returns the
    HTML; an unknown area slug is HTTP 404 -> NotFound."""
    html, _final, _status = _get_html(path, query, f"search page {path}")
    return html


def fetch_detail(property_id):
    """The Spanish listing page under the sale segment, then the rental one
    (the site redirects a mismatched segment to ?propertyNotFound; the
    Spanish segments are the proven ones, the page's own `uris` give the
    other languages' links for fetch_page). Returns (html, canonical_url)."""
    try:
        html, final, _status = _get_html(refs.detail_path("es", property_id, "buy"), None,
                                         f"listing {property_id}")
    except FotocasaNotFound:
        html, final, _status = _get_html(refs.detail_path("es", property_id, "rent"), None,
                                         f"listing {property_id}")
    return html, final


def fetch_promotion(promotion_id):
    """The Spanish new-development page (other languages through its `uris`)."""
    html, final, _status = _get_html(refs.promotion_path("es", promotion_id), None,
                                     f"new development {promotion_id}")
    return html, final


def fetch_page(url_or_path, label):
    """Any site page by its own link (a language variant from a page's
    `uris`). Returns (html, canonical_url)."""
    path = url_or_path[len(refs.SITE):] if url_or_path.startswith(refs.SITE) else url_or_path
    html, final, _status = _get_html(path, None, label)
    return html, final


def fetch_agency(language, slug, transaction=None, property_type=None, page=1):
    """The minisite (profile + its listing); an unknown slug is a 404."""
    html, final, _status = _get_html(refs.agency_path(language, slug, transaction, property_type, page), None,
                                     f"agency {slug}")
    return html, final


def fetch_directory(location, zone=None, page=1):
    """One agencies-directory page (an unknown location is a 200 with no cards)."""
    html, final, _status = _get_html(refs.directory_path(location, zone, page), None,
                                     f"agencies in {location}")
    return html, final


def fetch_price_index(municipality, district=None):
    html, final, _status = _get_html(refs.price_index_path(municipality, district), None,
                                     f"price index of {municipality}" + (f"/{district}" if district else ""))
    return html, final
