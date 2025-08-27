# services/search.py
import os
from serpapi import GoogleSearch

SERPAPI_KEY = os.getenv("SERPAPI_KEY")

def web_search(query: str) -> str:
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY
    }
    search = GoogleSearch(params)
    results = search.get_dict()

    if "organic_results" in results:
        first = results["organic_results"][0]
        title = first.get("title")
        snippet = first.get("snippet")
        link = first.get("link")
        return f"{title} — {snippet} (Source: {link})"
    else:
        return "I couldn’t find any reliable information right now."
