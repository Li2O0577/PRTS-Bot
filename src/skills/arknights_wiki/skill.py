from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

import httpx
from nonebot import logger

from src.plugins.smart_reply.config import config


@dataclass(slots=True)
class WikiPage:
    title: str
    extract: str
    url: str


@dataclass(slots=True)
class WikiResult:
    query: str
    pages: list[WikiPage]

    def as_prompt_context(self) -> str:
        if not self.pages:
            return f"No wiki result found for query: {self.query}"

        chunks = [f"Wiki query: {self.query}"]
        for index, page in enumerate(self.pages, start=1):
            chunks.append(
                f"[{index}] Title: {page.title}\nURL: {page.url}\nExtract: {page.extract}"
            )
        return "\n\n".join(chunks)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def get_text(self) -> str:
        return " ".join(self.parts)


def _cn(text: str) -> str:
    return text.encode("utf-8").decode("unicode_escape")


def _page_url(title: str) -> str:
    return f"https://prts.wiki/w/{title.replace(' ', '_')}"


async def search_wiki(query: str) -> WikiResult | None:
    query = query.strip()
    if not query or not config.smart_reply_wiki_enabled:
        return None

    try:
        async with httpx.AsyncClient(timeout=config.smart_reply_wiki_timeout) as client:
            titles = await _direct_titles(client, _candidate_titles(query))
            if not titles:
                titles = await _search_titles(client, query)
            if not titles and " " in query:
                titles = await _search_titles(client, query.split()[0])
            if not titles:
                return WikiResult(query=query, pages=[])

            extract_response = await client.get(
                config.smart_reply_wiki_api_base,
                params={
                    "action": "query",
                    "format": "json",
                    "prop": "extracts",
                    "explaintext": 1,
                    "exintro": 1,
                    "redirects": 1,
                    "titles": "|".join(titles),
                },
                headers={"User-Agent": "nonebot-napcat-smart-reply/0.1"},
            )
            extract_response.raise_for_status()
            extract_data = extract_response.json()
    except Exception as exc:
        logger.warning(f"arknights_wiki search failed: {exc!r}")
        return None

    pages: list[WikiPage] = []
    raw_pages = extract_data.get("query", {}).get("pages", {})
    for page in raw_pages.values():
        title = page.get("title")
        if not title:
            continue
        extract = (page.get("extract") or "").strip()
        if not extract:
            extract = _select_relevant_text(await _parse_page_text(title), query)
        if len(extract) > config.smart_reply_wiki_extract_chars:
            extract = extract[: config.smart_reply_wiki_extract_chars].rstrip() + "..."
        pages.append(WikiPage(title=title, extract=extract, url=_page_url(title)))

    return WikiResult(query=query, pages=pages)


def _select_relevant_text(text: str, query: str) -> str:
    max_chars = config.smart_reply_wiki_extract_chars
    terms = [item for item in query.split() if item]
    skill_terms = {
        _cn("\\u4e00\\u6280\\u80fd"): _cn("\\u6280\\u80fd1"),
        "1" + _cn("\\u6280\\u80fd"): _cn("\\u6280\\u80fd1"),
        _cn("\\u6280\\u80fd\\u4e00"): _cn("\\u6280\\u80fd1"),
        _cn("\\u4e8c\\u6280\\u80fd"): _cn("\\u6280\\u80fd2"),
        "2" + _cn("\\u6280\\u80fd"): _cn("\\u6280\\u80fd2"),
        _cn("\\u6280\\u80fd\\u4e8c"): _cn("\\u6280\\u80fd2"),
        _cn("\\u4e09\\u6280\\u80fd"): _cn("\\u6280\\u80fd3"),
        "3" + _cn("\\u6280\\u80fd"): _cn("\\u6280\\u80fd3"),
        _cn("\\u6280\\u80fd\\u4e09"): _cn("\\u6280\\u80fd3"),
    }
    for marker, term in skill_terms.items():
        if marker in query:
            terms.insert(0, term)

    for term in terms:
        index = text.find(term)
        if index >= 0:
            start = max(0, index - 200)
            end = min(len(text), start + max_chars)
            return text[start:end].strip()
    return text[:max_chars].strip()


def _candidate_titles(query: str) -> list[str]:
    candidates = [query]
    if " " in query:
        candidates.append(query.split()[0])
    seen: set[str] = set()
    return [item for item in candidates if item and not (item in seen or seen.add(item))]


async def _direct_titles(client: httpx.AsyncClient, titles: list[str]) -> list[str]:
    response = await client.get(
        config.smart_reply_wiki_api_base,
        params={
            "action": "query",
            "format": "json",
            "titles": "|".join(titles),
            "redirects": 1,
        },
        headers={"User-Agent": "nonebot-napcat-smart-reply/0.1"},
    )
    response.raise_for_status()
    data = response.json()
    found: list[str] = []
    for page in data.get("query", {}).get("pages", {}).values():
        if "missing" not in page and page.get("title"):
            found.append(page["title"])
    return found


async def _search_titles(client: httpx.AsyncClient, query: str) -> list[str]:
    search_response = await client.get(
        config.smart_reply_wiki_api_base,
        params={
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": config.smart_reply_wiki_max_pages,
        },
        headers={"User-Agent": "nonebot-napcat-smart-reply/0.1"},
    )
    search_response.raise_for_status()
    search_data = search_response.json()
    return [
        item["title"]
        for item in search_data.get("query", {}).get("search", [])
        if item.get("title")
    ]


async def _parse_page_text(title: str) -> str:
    async with httpx.AsyncClient(timeout=config.smart_reply_wiki_timeout) as client:
        response = await client.get(
            config.smart_reply_wiki_api_base,
            params={
                "action": "parse",
                "format": "json",
                "page": title,
                "prop": "text",
                "disableeditsection": 1,
            },
            headers={"User-Agent": "nonebot-napcat-smart-reply/0.1"},
        )
    response.raise_for_status()
    html = response.json().get("parse", {}).get("text", {}).get("*", "")
    parser = _TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    for item in (_cn("\\u7f16\\u8f91"), _cn("\\u8ba8\\u8bba"), _cn("\\u67e5\\u770b\\u6e90\\u4ee3\\u7801"), _cn("\\u5386\\u53f2")):
        text = text.replace(item, " ")
    return " ".join(text.split())

