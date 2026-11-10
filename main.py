"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does (paged endpoints carry a
`pagination` block instead of next / previous links); results are written
to output/*.json. The schemas fill in every default, exactly as the API does.
"""
import json
import os

from fotocasa import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def params(schema_cls, **query):
    """Validate a query exactly like the API: defaults filled, links resolved."""
    return schema_cls().load(query)


if __name__ == "__main__":
    # a listing id or any fotocasa.es listing link
    save("property_159718048.json", api.property_details(
        **params(schemas.PropertyDetailsSchema, property="159718048")))

    # 30 listings per page (up to 400); a place name, location id, street slug or search link
    save("search_marbella_pools.json", api.properties_search(
        **params(schemas.PropertiesSearchSchema, location="Marbella", features="swimming_pool", sort="newest")))

    # a city or district: median sale and rent price per m², changes and monthly history
    save("price_index_marbella.json", api.price_index(
        **params(schemas.PriceIndexSchema, location="Marbella")))
