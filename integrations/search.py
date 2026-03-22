import requests
from core.config import TAVILY_API_KEY


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via Tavily API. Returns list of {title, content, url}."""
    if not TAVILY_API_KEY:
        return [{"title": "Search unavailable", "content": "TAVILY_API_KEY not set in environment.", "url": ""}]
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": True,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    results = []
    if data.get("answer"):
        results.append({"title": "Direct answer", "content": data["answer"], "url": ""})
    for r in data.get("results", []):
        results.append({
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "url": r.get("url", ""),
        })
    return results
