"""Offline tests for the /fotocasa/* request schemas.

    python -m pytest fotocasa/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fotocasa import refs, schemas  # noqa: E402


def _errors(schema, data):
    with pytest.raises(ValidationError) as info:
        schema().load(data)
    return info.value.normalized_messages()


# ---- locations/search -----------------------------------------------------------------------

def test_locations_search_schema():
    assert schemas.LocationsSearchSchema().load({"query": " Madrid "}) == {"query": "Madrid", "language": "es"}
    assert schemas.LocationsSearchSchema().load({"query": "x", "language": "EN"})["language"] == "en"
    assert "query" in _errors(schemas.LocationsSearchSchema, {})
    assert "language" in _errors(schemas.LocationsSearchSchema, {"query": "x", "language": "fr"})
    assert "q" in _errors(schemas.LocationsSearchSchema, {"query": "x", "q": "y"})


# ---- properties/search ----------------------------------------------------------------------

def test_properties_search_defaults():
    loaded = schemas.PropertiesSearchSchema().load({"location": "Madrid"})
    assert loaded["location"] == "Madrid"
    assert (loaded["transaction"], loaded["property_type"], loaded["page"], loaded["per_page"], loaded["language"]) == \
        ("buy", "homes", 1, 30, "es")
    assert loaded["sort"] == "relevance" and loaded["min_price"] is None and loaded["features"] is None


def test_properties_search_accepts_every_location_form():
    for value in ("724,14,28,173,0,28079,0,0,0", "calle-serrano-madrid-capital", "Barrio de Salamanca, Madrid",
                  "https://www.fotocasa.es/es/comprar/viviendas/madrid-capital/todas-las-zonas/l?maxPrice=300000"):
        assert schemas.PropertiesSearchSchema().load({"location": value})["location"] == value


def test_properties_search_filters_map():
    loaded = schemas.PropertiesSearchSchema().load({
        "location": "Madrid", "transaction": "Rent", "property_type": "homes", "subtypes": "flat, penthouse,flat",
        "min_price": "500", "max_price": "1500", "min_rooms": "2", "max_rooms": "3", "min_bathrooms": "1",
        "min_surface": "50", "max_surface": "120", "condition": "very_good,good", "features": "lift,terrace",
        "published": "last_week", "new_construction": "false", "price_drop": "true", "bank_owned": "1",
        "with_photos": "yes", "with_video": "no", "rental_duration": "long_term", "text": "ático",
        "sort": "price_asc", "page": "2", "per_page": "100", "language": "en"})
    assert loaded["transaction"] == "rent" and loaded["subtypes"] == ["flat", "penthouse"]
    assert (loaded["min_price"], loaded["max_price"], loaded["min_rooms"], loaded["max_rooms"]) == (500, 1500, 2, 3)
    assert loaded["condition"] == ["very_good", "good"] and loaded["features"] == ["lift", "terrace"]
    assert loaded["published"] == "last_week" and loaded["price_drop"] is True and loaded["with_video"] is False
    assert loaded["rental_duration"] == "long_term" and loaded["text"] == "ático" and loaded["sort"] == "price_asc"
    assert (loaded["page"], loaded["per_page"], loaded["language"]) == (2, 100, "en")


@pytest.mark.parametrize("data,field", [
    ({}, "location"),
    ({"location": ""}, "location"),
    ({"location": "https://example.com/x"}, "location"),
    ({"location": "Madrid", "transaction": "sale"}, "transaction"),
    ({"location": "Madrid", "property_type": "rooms"}, "property_type"),
    ({"location": "Madrid", "subtypes": "castle"}, "subtypes"),
    ({"location": "Madrid", "condition": "ruin"}, "condition"),
    ({"location": "Madrid", "features": "helipad"}, "features"),
    ({"location": "Madrid", "published": "yesterday"}, "published"),
    ({"location": "Madrid", "sort": "cheapest"}, "sort"),
    ({"location": "Madrid", "min_price": "500", "max_price": "100"}, "max_price"),
    ({"location": "Madrid", "min_rooms": "4", "max_rooms": "2"}, "max_rooms"),
    ({"location": "Madrid", "min_rooms": "11"}, "min_rooms"),
    ({"location": "Madrid", "page": "0"}, "page"),
    ({"location": "Madrid", "page": "334"}, "page"),
    ({"location": "Madrid", "per_page": "401"}, "per_page"),
    ({"location": "Madrid", "price_drop": "maybe"}, "price_drop"),
    ({"location": "Madrid", "url": "x"}, "url"),
])
def test_properties_search_rejects(data, field):
    assert field in _errors(schemas.PropertiesSearchSchema, data)


# ---- properties/details -----------------------------------------------------------------------

def test_property_details_schema():
    assert schemas.PropertyDetailsSchema().load({"property": "184433815"}) == {"property": "184433815", "language": "es"}
    loaded = schemas.PropertyDetailsSchema().load(
        {"property": "https://www.fotocasa.es/en/buy/home/madrid/x/184433815/d", "language": "en"})
    assert loaded == {"property": "184433815", "language": "en"}
    errors = _errors(schemas.PropertyDetailsSchema, {"property": "piso"})
    assert "property" in errors and "listing id" in errors["property"][0]
    assert "id" in _errors(schemas.PropertyDetailsSchema, {"property": "184433815", "id": "184433815"})


# ---- promotions/details ------------------------------------------------------------------------

def test_promotion_details_schema():
    assert schemas.PromotionDetailsSchema().load({"promotion": "20678485"})["promotion"] == "20678485"
    assert schemas.PromotionDetailsSchema().load(
        {"promotion": "https://www.fotocasa.es/es/comprar/obra-nueva/madrid-capital/20678485"})["promotion"] == "20678485"
    assert "promotion" in _errors(schemas.PromotionDetailsSchema, {"promotion": "azores"})


# ---- agencies ----------------------------------------------------------------------------------

def test_agency_details_schema():
    assert schemas.AgencyDetailsSchema().load({"agency": "fortuny-madrid-real-estate"})["agency"] == {
        "slug": "fortuny-madrid-real-estate"}
    assert schemas.AgencyDetailsSchema().load({"agency": "9202757120653"})["agency"] == {"client_id": "9202757120653"}
    assert schemas.AgencyDetailsSchema().load(
        {"agency": "https://www.fotocasa.es/es/pro/fortuny-madrid-real-estate/"})["agency"] == {
        "slug": "fortuny-madrid-real-estate"}
    assert "agency" in _errors(schemas.AgencyDetailsSchema, {"agency": "https://example.com/pro/x/"})
    assert "agency" in _errors(schemas.AgencyDetailsSchema, {})


def test_agency_listings_schema():
    loaded = schemas.AgencyListingsSchema().load({"agency": "fortuny-madrid-real-estate", "transaction": "rent",
                                                  "location": "724,14,28,173,0,28079,0,0,0", "max_price": "2000"})
    assert loaded["agency"] == {"slug": "fortuny-madrid-real-estate"} and loaded["transaction"] == "rent"
    assert loaded["location"] == "724,14,28,173,0,28079,0,0,0" and loaded["max_price"] == 2000
    assert loaded["page"] == 1 and loaded["per_page"] == 30
    errors = _errors(schemas.AgencyListingsSchema, {"agency": "x", "location": "Madrid"})
    assert "location" in errors and "location id" in errors["location"][0]
    assert "location" in _errors(schemas.AgencyListingsSchema, {"agency": "x", "location": "https://example.com/x"})


def test_agencies_search_schema():
    assert schemas.AgenciesSearchSchema().load({"location": "Madrid"}) == {"location": "Madrid", "page": 1}
    assert schemas.AgenciesSearchSchema().load({"location": "madrid-capital/barrio-de-salamanca", "page": "3"})["page"] == 3
    assert schemas.AgenciesSearchSchema().load(
        {"location": "https://www.fotocasa.es/buscar-agencias-inmobiliarias/madrid-capital/todas-las-zonas/l"})["page"] == 1
    assert "location" in _errors(schemas.AgenciesSearchSchema, {"location": "https://www.fotocasa.es/es/pro/x/"})
    assert "location" in _errors(schemas.AgenciesSearchSchema, {})


# ---- prices/index --------------------------------------------------------------------------------

def test_price_index_schema():
    for value in ("Madrid", "madrid-capital", "madrid-capital/barrio-de-salamanca", "724,14,28,173,0,28079,0,0,0",
                  "https://www.fotocasa.es/es/indice-precio-vivienda/madrid-capital/barrio-de-salamanca"):
        assert schemas.PriceIndexSchema().load({"location": value})["location"] == value
    assert "location" in _errors(schemas.PriceIndexSchema, {"location": "https://www.fotocasa.es/es/pro/x/"})
    assert "location" in _errors(schemas.PriceIndexSchema, {"location": "a/b/c"})
    assert "transaction" in _errors(schemas.PriceIndexSchema, {"location": "Madrid", "transaction": "rent"})


# ---- the public vocabularies are the site's ---------------------------------------------------------

def test_vocabularies_are_consistent():
    assert set(refs.TRANSACTIONS) == {"buy", "rent", "share", "rent_to_buy", "transfer"}
    assert refs.TRANSACTIONS["rent"] == 3 and refs.PROPERTY_TYPES["homes"] == 2
    assert all(isinstance(v, int) for v in refs.FEATURES.values())
    assert len(set(refs.FEATURES.values())) == len(refs.FEATURES)
    assert refs.SORTS["price_asc"] == ("price", False) and refs.SORTS["newest"] == ("publicationDate", True)
