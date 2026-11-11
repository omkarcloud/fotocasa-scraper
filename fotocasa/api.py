"""The /fotocasa/* endpoint functions (route_glue's route_table calls them
with the schema's loaded kwargs). Caching happens here through
cache.cached_call, keyed on the validated params.

Shared upstream answers are cached once and sliced: a typed place name is
resolved through the same cached typeahead answer locations/search serves;
the slug / client-id lookups behind a name (one gateway row) are cached on
their own; agencies/details and agencies/listings read one cached minisite
parse per agency.

Search flows (fotocasa/fetch.py has the surfaces):
  * a place name or a combined location id -> the JSON gateway (any page
    size up to 400, every filter, the first 9,960 rows of a search)
  * a street / urbanisation area slug, or a pasted search link -> the
    server-rendered page that carries the same answer (30 a page, the
    link's own filters + the request's)
"""
import math
import re
from urllib.parse import urlencode

from cache import cached_call
from fotocasa import cache_config as ttl
from fotocasa import parsers, refs
from fotocasa.fetch import (FotocasaNotFound, fetch_agency, fetch_detail, fetch_directory, fetch_list_page,
                            fetch_page, fetch_price_index, fetch_promotion, fetch_search, fetch_suggest)

ITEMS_PER_PAGE = refs.ITEMS_PER_PAGE

_FILTER_KEYS = ("subtypes", "min_price", "max_price", "min_rooms", "max_rooms", "min_bathrooms", "max_bathrooms",
                "min_surface", "max_surface", "condition", "features", "published", "new_construction",
                "price_drop", "bank_owned", "with_photos", "with_video", "rental_duration", "text", "sort")


# ---- shared helpers --------------------------------------------------------------------

def _culture(language):
    return refs.LANGUAGES.get(language or refs.DEFAULT_LANGUAGE, refs.LANGUAGES[refs.DEFAULT_LANGUAGE])


def _filter_params(data):
    """The validated filters -> the site's own query names (shared by the
    gateway and the HTML pages)."""
    query = {}
    if data.get("subtypes"):
        query["propertySubtypeIds"] = ";".join(str(refs.SUBTYPES[s]) for s in data["subtypes"])
    for ours, theirs in (("min_price", "minPrice"), ("max_price", "maxPrice"), ("min_rooms", "minRooms"),
                         ("max_rooms", "maxRooms"), ("min_bathrooms", "minBathrooms"),
                         ("max_bathrooms", "maxBathrooms"), ("min_surface", "minSurface"),
                         ("max_surface", "maxSurface")):
        if data.get(ours):
            query[theirs] = str(data[ours])
    if data.get("condition"):
        query["conservationStatusIds"] = ";".join(str(refs.CONDITIONS[c]) for c in data["condition"])
    if data.get("features"):
        query["featureIds"] = ";".join(str(refs.FEATURES[f]) for f in data["features"])
    if data.get("published"):
        query["publicationDate"] = refs.PUBLISHED[data["published"]]
    if data.get("new_construction"):
        query["isNewConstruction"] = "true"
    others = [str(refs.OTHER_FLAGS[flag]) for flag, key in (("bank_owned", "bank_owned"), ("with_photos", "with_photos"),
                                                            ("with_video", "with_video"), ("price_drop", "price_drop"))
              if data.get(key)]
    if others:
        query["otherIds"] = ";".join(others)
    if data.get("rental_duration"):
        query["rentalDuration"] = refs.RENTAL_DURATIONS[data["rental_duration"]]
    if data.get("text"):
        query["text"] = data["text"]
    sort_type, desc = refs.SORTS[data.get("sort") or "relevance"]
    query["sortType"] = sort_type
    query["sortOrderDesc"] = "true" if desc else "false"
    return query


def _echo_filters(data):
    return {key: data.get(key) for key in _FILTER_KEYS if data.get(key) not in (None, False, [])} or None


def _pagination(count, page, size, cap=None):
    total_pages = math.ceil(count / size) if count and size else 0
    if cap:
        total_pages = min(total_pages, cap)
    return {"page": page, "items_per_page": size, "total_pages": total_pages, "total_count": count}


def _gateway_search(combined, transaction, property_type, page, size, language, filters, client_id=None):
    params = {
        "culture": _culture(language),
        "combinedLocationIds": combined,
        "transactionTypeId": refs.TRANSACTIONS[transaction],
        "propertyTypeId": refs.PROPERTY_TYPES[property_type],
        "pageNumber": page,
        "size": size,
    }
    if client_id:
        params["clientId"] = client_id
    params.update(_filter_params(filters))
    parsed = parsers.parse_search(fetch_search(params), language)
    if (parsed["count"] and page > math.ceil(parsed["count"] / size)) or page * size > refs.GATEWAY_WINDOW:
        # the gateway wraps past the end, and past its result window it
        # serves an unrelated fallback page
        parsed["results"] = []
    return parsed


# ---- locations/search -------------------------------------------------------------------

def _locations_search(query, language):
    results = parsers.parse_suggestions(fetch_suggest(query, language))
    return {"query": query, "count": len(results), "results": results}


def locations_search(**data):
    """Search places in Spain: municipalities, provinces, districts, neighborhoods, streets and zip codes,
    each with its level, location id (or area slug for a street) and coordinates."""
    return cached_call("fotocasa.locations", data, _locations_search, ttl.LOCATIONS_CACHE)


def _resolve_place(name, language=refs.DEFAULT_LANGUAGE):
    """A typed place name -> the first typeahead row that can be searched
    (a combined location id or an area slug), or NotFound."""
    answer = locations_search(query=name, language=language)
    for row in answer["results"]:
        if row.get("location_id") or row.get("area"):
            return row
    raise FotocasaNotFound(f"No fotocasa location matches '{name}'.")


def _location_slugs(combined):
    """A combined location id -> {name, slug, location, zone, level} from
    one gateway row (the site's own URL segments for that place)."""
    parsed = _gateway_search(combined, "buy", "homes", 1, 1, refs.DEFAULT_LANGUAGE, {})
    slugs = parsed.get("slugs") or {}
    selected = parsed.get("location") or {}
    if not slugs.get("location"):
        raise FotocasaNotFound(f"fotocasa knows no place with the location id {combined}.")
    return {
        "name": selected.get("name"),
        "level": selected.get("level"),
        "slug": selected.get("slug") or f"{slugs['location']}/{slugs.get('zone') or 'todas-las-zonas'}",
        "location": slugs["location"],
        "zone": slugs.get("zone") if slugs.get("zone") not in (None, "todas-las-zonas") else None,
        "location_id": combined,
        "listings_count": parsed.get("count"),
    }


def location_slugs(combined):
    return cached_call("fotocasa.location_slugs", {"combined": combined}, _location_slugs, ttl.RESOLVE_CACHE)


# ---- properties/search ----------------------------------------------------------------------

def _html_search(path, query, page, language, filters, location_hint=None):
    """A server-rendered search page (area slug or pasted link)."""
    html = fetch_list_page(path, query or None)
    parsed = parsers.parse_list_page(html)
    size = parsed.get("page_size") or ITEMS_PER_PAGE
    results = parsed["results"]
    if parsed["count"] and page > min(math.ceil(parsed["count"] / size), refs.HTML_MAX_PAGES):
        results = []
    location = parsed["location"]
    if location_hint:
        location = {**location, **{k: v for k, v in location_hint.items() if v}}
    return {
        "location": location,
        "transaction": parsed["transaction"],
        "property_type": parsed["property_type"],
        "filters": _echo_filters(filters),
        "link": parsed["link"],
        "title": parsed["title"],
        "results": results,
        "new_developments": parsed["new_developments"],
        "facets": parsed["facets"],
        "mean_prices": parsed["mean_prices"],
        "pagination": _pagination(parsed["count"], page, size, refs.HTML_MAX_PAGES),
    }


def _properties_search(location, transaction, property_type, page, per_page, language, **filters):
    kind, value = refs.classify_location(location)
    if kind == "link":
        path, link_query = value
        link = refs.split_list_link(path, link_query)
        if page == 1 and link["page"] > 1:
            page = link["page"]
        base = re.sub(r"/l(?:/[0-9]+)?/?$", "", path) + "/l" + (f"/{page}" if page > 1 else "")
        query = {k: v for k, v in link_query.items() if k not in ("from",)}
        extra = _filter_params(filters)
        if filters.get("sort") in (None, "relevance"):
            # the link's own sort (or the page's default) stands unless the request names one
            extra = {k: v for k, v in extra.items() if k not in ("sortType", "sortOrderDesc")}
        query.update(extra)
        return _html_search(base, query, page, link["language"], filters)
    if kind == "area":
        path = refs.list_path(language, transaction, property_type, None, area=value, page=page)
        return _html_search(path, _filter_params(filters), page, language, filters,
                            location_hint={"area": value})
    resolved = {"name": None, "level": None, "location_id": value if kind == "combined" else None, "area": None}
    if kind == "name":
        place = _resolve_place(value, language)
        if place.get("area"):
            path = refs.list_path(language, transaction, property_type, None, area=place["area"], page=page)
            return _html_search(path, _filter_params(filters), page, language, filters,
                                location_hint={"name": place["name"], "level": place["level"], "area": place["area"]})
        resolved = {"name": place["name"], "level": place["level"], "location_id": place["location_id"],
                    "area": None}
    parsed = _gateway_search(resolved["location_id"], transaction, property_type, page, per_page, language, filters)
    selected = parsed.get("location") or {}
    slugs = parsed.get("slugs") or {}
    return {
        "location": {
            "name": resolved["name"] or selected.get("name"),
            "level": resolved["level"] or selected.get("level"),
            "location_id": resolved["location_id"],
            "slug": selected.get("slug") or ("/".join(s for s in (slugs.get("location"), slugs.get("zone")) if s)
                                             or None),
            "area": None,
        },
        "transaction": transaction,
        "property_type": property_type,
        "filters": _echo_filters(filters),
        "link": refs.absolute(refs.list_path(language, transaction, property_type, slugs.get("location"),
                                             slugs.get("zone"), page=page)) if slugs.get("location") else None,
        "title": None,
        "results": parsed["results"],
        "new_developments": parsed["new_developments"],
        "facets": parsed["facets"],
        "mean_prices": None,
        "pagination": _pagination(parsed["count"], page, per_page, refs.GATEWAY_WINDOW // per_page),
    }


def properties_search(**data):
    """Search homes, garages, land, premises and offices for sale or rent: price and price drop, rooms,
    bathrooms, size, floor, address with coordinates, photos and advertiser (30 per page by default, up to
    400), plus location facets with listing counts."""
    return cached_call("fotocasa.search", data, _properties_search, ttl.SEARCH_CACHE)


# ---- properties/details ---------------------------------------------------------------------

def _in_language(record, language, parse, label):
    """A record parsed from the Spanish page -> the same page in `language`
    (its own link from the page's `uris`), when the site publishes one."""
    link = (record.get("links") or {}).get(language)
    if language == refs.DEFAULT_LANGUAGE or not link:
        return record
    html, final_url = fetch_page(link, label)
    try:
        localized = parse(html, canonical_url=final_url)
    except ValueError:
        return record
    localized["link"] = link
    return localized


def _property_details(property, language):
    html, final_url = fetch_detail(property)
    try:
        record = parsers.parse_detail(html, property, canonical_url=final_url)
    except ValueError:
        raise FotocasaNotFound(f"listing {property} not found")
    return _in_language(record, language, lambda h, canonical_url: parsers.parse_detail(h, property, canonical_url),
                        f"listing {property} ({language})")


def property_details(**data):
    """Get one listing: price and price drop, rooms, bathrooms, size, floor, orientation, condition, age,
    energy certificate, amenities, description, every photo, address with coordinates and the advertiser
    with phone and reference."""
    return cached_call("fotocasa.details", data, _property_details, ttl.DETAILS_CACHE)


# ---- promotions/details ----------------------------------------------------------------------

def _promotion_details(promotion, language):
    html, final_url = fetch_promotion(promotion)
    try:
        record = parsers.parse_promotion(html, promotion, canonical_url=final_url)
    except ValueError:
        raise FotocasaNotFound(f"new development {promotion} not found")
    return _in_language(record, language,
                        lambda h, canonical_url: parsers.parse_promotion(h, promotion, canonical_url),
                        f"new development {promotion} ({language})")


def promotion_details(**data):
    """Get one new-build development: price, room and size ranges, every unit with its price, floor and
    amenities, energy rating, photos, virtual tour, address and the developer with phone."""
    return cached_call("fotocasa.promotion", data, _promotion_details, ttl.DETAILS_CACHE)


# ---- the agency minisite (shared page) ---------------------------------------------------------

def _agency_page(slug, language, transaction=None, property_type=None, page=1):
    html, final_url = fetch_agency(language, slug, transaction, property_type, page)
    try:
        return parsers.parse_agency(html, canonical_url=final_url)
    except ValueError:
        raise FotocasaNotFound(f"agency {slug} not found")


def _agency_page_cached(slug, language):
    return cached_call("fotocasa.agency_page", {"slug": slug, "language": language}, _agency_page, ttl.AGENCY_CACHE)


def _client_slug(client_id):
    """A numeric client id -> its minisite slug through one gateway row
    (the `client` block); an unknown id answers no client at all."""
    parsed = _gateway_search("724,0,0,0,0,0,0,0,0", "buy", "homes", 1, 1, refs.DEFAULT_LANGUAGE, {},
                             client_id=client_id)
    agency = parsed.get("agency")
    if not agency:
        # an agency that only rents answers no sale rows; try the rental side
        parsed = _gateway_search("724,0,0,0,0,0,0,0,0", "rent", "homes", 1, 1, refs.DEFAULT_LANGUAGE, {},
                                 client_id=client_id)
        agency = parsed.get("agency")
    if not agency:
        raise FotocasaNotFound(f"agency {client_id} not found")
    return agency


def client_summary(client_id):
    return cached_call("fotocasa.client", {"client_id": client_id}, _client_slug, ttl.AGENCY_CACHE)


def _resolve_agency(agency):
    """The schema's {slug} | {client_id} -> (slug, client_id, gateway summary)."""
    if agency.get("slug"):
        return agency["slug"], None, None
    summary = client_summary(agency["client_id"])
    if not summary.get("slug"):
        raise FotocasaNotFound(f"agency {agency['client_id']} has no fotocasa page")
    return summary["slug"], agency["client_id"], summary


# ---- agencies/details -----------------------------------------------------------------------

def agency_details(agency, language):
    """Get one real estate agency: address, phones, email, website, coordinates, member-since date,
    listing counts by type and its latest listings."""
    slug, _client_id, summary = _resolve_agency(agency)
    page = _agency_page_cached(slug, language)
    profile = dict(page["profile"])
    if summary:
        profile["id"] = profile.get("id") or summary.get("id")
    listing = page["listing"]
    profile["latest_listings"] = listing["results"][:refs.AGENCY_PAGE_ITEMS] or None
    return profile


# ---- agencies/listings ----------------------------------------------------------------------

def _agency_listings(agency, transaction, property_type, location, page, per_page, language, **filters):
    slug, client_id, summary = _resolve_agency(agency)
    profile = _agency_page_cached(slug, language)["profile"]
    client_id = client_id or profile.get("id")
    combined = location or "724,0,0,0,0,0,0,0,0"
    if client_id:
        parsed = _gateway_search(combined, transaction, property_type, page, per_page, language, filters,
                                 client_id=client_id)
        results, count, size = parsed["results"], parsed["count"], per_page
        agency_block = parsed.get("agency")
    else:
        # a minisite with no listing rows carries no client id: nothing to list
        results, count, size, agency_block = [], 0, per_page, None
    return {
        "agency": {
            "id": client_id,
            "slug": slug,
            "name": profile.get("name"),
            "link": profile.get("link"),
            "listings_count": profile.get("listings_count"),
            **({"email": agency_block.get("email"), "phones": agency_block.get("phones"),
                "website": agency_block.get("website")} if agency_block else {}),
        },
        "transaction": transaction,
        "property_type": property_type,
        "location": location,
        "filters": _echo_filters(filters),
        "results": results,
        "pagination": _pagination(count, page, size, refs.GATEWAY_WINDOW // size),
    }


def agency_listings(**data):
    """List one agency's properties for sale or rent with every search filter, plus the agency's email,
    phones and website (30 per page by default, up to 400)."""
    return cached_call("fotocasa.agency_listings", data, _agency_listings, ttl.SEARCH_CACHE)


# ---- agencies/search (the directory) --------------------------------------------------------

def _directory_slugs(location):
    kind, value = refs.resolve_directory_location(location)
    if kind == "slugs":
        return {"location": value[0], "zone": value[1], "name": None, "location_id": None}
    if kind == "name":
        place = _resolve_place(value)
        if not place.get("location_id"):
            raise FotocasaNotFound(f"'{value}' is a street or urbanisation; the agencies directory lists "
                                   "municipalities, districts and neighbourhoods.")
        value = place["location_id"]
    slugs = location_slugs(value)
    return {"location": slugs["location"], "zone": slugs["zone"], "name": slugs["name"], "location_id": value}


def _agencies_search(location, page):
    slugs = _directory_slugs(location)
    html, final_url = fetch_directory(slugs["location"], slugs["zone"], page)
    parsed = parsers.parse_directory(html, canonical_url=final_url)
    if page == 1 and not parsed["results"] and not (parsed["totals"] or {}).get("for_sale_agencies"):
        raise FotocasaNotFound(f"fotocasa has no agencies directory for '{location}'.")
    return {
        "location": {
            "name": slugs["name"] or (parsed["title"] or "").replace("Inmobiliarias en ", "", 1) or None,
            "slug": "/".join(s for s in (slugs["location"], slugs["zone"]) if s),
            "location_id": slugs["location_id"],
        },
        "title": parsed["title"],
        "link": refs.absolute(refs.directory_path(slugs["location"], slugs["zone"], page)),
        "agencies_count": parsed["totals"],
        "results": parsed["results"],
        "pagination": {
            "page": page,
            "items_per_page": refs.DIRECTORY_ITEMS_PER_PAGE,
            "has_next": len(parsed["results"]) >= refs.DIRECTORY_ITEMS_PER_PAGE,
            "total_pages": None,
            "total_count": None,
        },
    }


def agencies_search(**data):
    """Find the real estate agencies of a city, district or neighborhood: name, logo, listing counts,
    lowest price and profile link (15 per page)."""
    return cached_call("fotocasa.agencies", data, _agencies_search, ttl.DIRECTORY_CACHE)


# ---- prices/index ---------------------------------------------------------------------------------

def _price_index_slugs(location):
    kind, value = refs.resolve_price_index_location(location)
    if kind == "slugs":
        return value
    if kind == "name":
        place = _resolve_place(value)
        if not place.get("location_id"):
            raise FotocasaNotFound(f"'{value}' is a street or urbanisation; the price index covers municipalities "
                                   "and districts.")
        value = place["location_id"]
    slugs = location_slugs(value)
    if slugs.get("level") not in (None, "municipality", "district", "locality"):
        raise FotocasaNotFound(f"The price index covers municipalities and districts; '{slugs.get('name')}' is a "
                               f"{slugs.get('level')}.")
    return slugs["location"], slugs["zone"]


def _price_index(location):
    municipality, district = _price_index_slugs(location)
    try:
        html, final_url = fetch_price_index(municipality, district)
    except FotocasaNotFound:
        raise FotocasaNotFound(f"fotocasa publishes no price index for '{location}' (municipalities and districts only).")
    try:
        return parsers.parse_price_index(html, canonical_url=final_url)
    except ValueError:
        raise FotocasaNotFound(f"fotocasa publishes no price index for '{location}'.")


def price_index(**data):
    """Get the housing price index of a municipality or district: median sale and rent price per m²,
    1/3/6/12-month changes, market temperature, monthly history since 2020 and every sub-zone's prices."""
    return cached_call("fotocasa.price_index", data, _price_index, ttl.PRICE_INDEX_CACHE)
