"""Picture search through Openverse's anonymous API. Only a search term leaves the server."""
from __future__ import annotations

import httpx

SEARCH_URL = "https://api.openverse.org/v1/images/"
PAGE_SIZE = 10


class OpenverseImageSearch:
    def __init__(self, client: httpx.Client):
        self.client = client

    def search(self, term: str, *, index: int) -> dict | None:
        response = self.client.get(SEARCH_URL, params={
            "q": term, "page_size": PAGE_SIZE, "mature": "false", "extension": "jpg,png",
        }, headers={"User-Agent": "DeepLingo notebook"})
        response.raise_for_status()
        results = response.json().get("results") or []
        if index >= len(results):
            return None
        item = results[index]
        return {
            "image_url": item["url"], "thumbnail_url": item.get("thumbnail"), "title": item.get("title"),
            "creator": item.get("creator"), "license": item.get("license"),
            "source_url": item.get("foreign_landing_url"),
        }
