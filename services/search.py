"""The Context step: fan out the generated queries to Serper's news search."""
import requests

import config


def search_news(query, num=None):
    num = num or config.SEARCH_RESULTS_PER_QUERY
    if not config.SERPER_API_KEY:
        return []
    try:
        resp = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": num},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data.get("news", [])[:num]:
        results.append({
            "query": query,
            "headline": item.get("title", ""),
            "source": item.get("source", ""),
            "date": item.get("date", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return results


def search_news_multi(queries, num_per_query=None):
    results = []
    seen_urls = set()
    for query in queries:
        for r in search_news(query, num=num_per_query):
            if r["url"] and r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            results.append(r)
    return results
