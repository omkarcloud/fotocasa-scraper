"""Cache TTL per /fotocasa/* endpoint (cache.py, keyed on the validated
params). Listings move through the day (new ads, price drops, withdrawals),
so the search views cache for hours; a listing or promotion page changes
only when the advertiser edits it; the place index, agency profiles and the
monthly price index are near-static.
"""
from datetime import timedelta

# locations/search: the site's place index — new zones appear rarely.
LOCATIONS_CACHE = timedelta(days=7)
# the slug / name lookups api.py makes on the gateway behind a typed name
# (one search row) — same cadence as the place index.
RESOLVE_CACHE = timedelta(days=7)
# properties/search + agencies/listings: one page of a search; order,
# membership and prices change through the day.
SEARCH_CACHE = timedelta(hours=6)
# properties/details + promotions/details: the advertiser edits price /
# text now and then; a withdrawn listing turns 404 — a day at most.
DETAILS_CACHE = timedelta(hours=24)
# agencies/details: the minisite profile (address, phones, counts) is
# near-static; its default listing page rides along.
AGENCY_CACHE = timedelta(days=3)
# agencies/search: the directory of a location rotates slowly.
DIRECTORY_CACHE = timedelta(days=1)
# prices/index: the site publishes one figure per month.
PRICE_INDEX_CACHE = timedelta(days=3)
