#!/usr/bin/env python3
"""Fetch live posts from curated security blogs using feed discovery with homepage fallback."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

try:
    from normalize_sources import dedupe, read_rows
except ImportError as exc:  # pragma: no cover
    raise SystemExit(f"Unable to import normalize_sources.py: {exc}")


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
COMMON_FEED_SUFFIXES = [
    "feed",
    "feed/",
    "rss",
    "rss/",
    "rss.xml",
    "feed.xml",
    "atom.xml",
    "index.xml",
    "blog/feed",
    "blog/rss.xml",
]
ARTICLE_HINTS = ("blog", "post", "article", "articles", "news", "research", "labs", "threat", "report", "reports")
BAD_LINK_HINTS = (
    "tag",
    "category",
    "author",
    "page/",
    "privacy",
    "contact",
    "about",
    "login",
    "signup",
    "subscribe",
    "search",
    "platform",
    "pricing",
    "product",
    "products",
    "solutions",
    "docs",
    "wp-content",
)
DATE_RE = re.compile(r"/20\d{2}/|/20\d{2}-\d{2}-\d{2}|/20\d{2}/\d{2}/\d{2}")
SUMMARY_PREVIEW_LIMIT = 280
DEFAULT_SINCE_DAYS = 30
DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1"
DEFAULT_PACKY_API_URL = "https://www.packyapi.com/v1"
DEFAULT_LLM_MODEL = "gpt-5.4"
DEFAULT_LLM_TIMEOUT = 45
DEFAULT_LLM_BATCH_SIZE = 25
DEFAULT_AI_KEYWORDS = [
    "ai security",
    "agent",
    "agentic",
    "llm",
    "mcp",
    "model context protocol",
    "prompt injection",
    "indirect prompt injection",
    "copilot",
    "chatgpt",
    "claude",
    "gemini",
    "openai",
    "anthropic",
    "genai",
    "generative ai",
    "jailbreak",
    "rag",
    "ai",
]
KNOWN_FEED_URLS = {
    "www.darkreading.com": ["https://www.darkreading.com/rss.xml"],
    "therecord.media": ["https://therecord.media/feed/"],
}
CHALLENGE_MARKERS = (
    b"aliyun_waf_aa",
    b"aliyun_waf_bb",
    b"cf-mitigated",
    b"Just a moment",
    b"ERROR: The request could not be satisfied",
)
AI_RELEVANCE_RULES = """You classify whether a security or technology article is relevant to the AI/agent ecosystem.

Mark relevant=true if the article is materially about any of:
- AI, LLM, GenAI, model security, jailbreaks, prompt injection, data exfiltration through models
- AI agents, coding agents, copilots, autonomous workflows, tool use, memory, planning, reasoning engines
- MCP / Model Context Protocol, agent frameworks, workflow engines, orchestration layers
- RAG, embeddings, vector databases, vector stores, retrieval systems used for AI/LLM apps
- infrastructure, vulnerabilities, incidents, benchmarks, or research affecting the AI/agent stack

Mark relevant=false for generic cyber, cloud, appsec, malware, or product marketing with no meaningful AI/agent angle.

Return strict JSON only:
{"results":[{"id":"...", "relevant":true, "keywords":["kw1","kw2"]}]}

Rules for keywords:
- 0 to 5 short lowercase tags
- prefer tags like agent, agentic, llm, mcp, prompt injection, copilot, chatgpt, claude, gemini, vector database, rag, reasoning engine, workflow, framework, inference
"""


@dataclass
class FetchResult:
    url: str
    final_url: str
    content_type: str
    body: bytes


@dataclass
class LLMConfig:
    provider: str
    api_url: str
    api_key: str
    model: str


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate_text(text: str, limit: int = SUMMARY_PREVIEW_LIMIT) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def local_name(tag: str) -> str:
    if "}" in tag:
        tag = tag.rsplit("}", 1)[1]
    if ":" in tag:
        tag = tag.rsplit(":", 1)[1]
    return tag.lower()


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def origin_of(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_url(url: str, timeout: int, headers: dict[str, str] | None = None) -> FetchResult:
    request_headers = dict(REQUEST_HEADERS)
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
        result = FetchResult(url=url, final_url=final_url, content_type=content_type, body=body)
        if should_retry_with_curl(result):
            curl_result = curl_fetch_url(url, timeout, request_headers)
            if curl_result is not None:
                return curl_result
        return result
    except Exception as exc:
        curl_result = curl_fetch_url(url, timeout, request_headers)
        if curl_result is not None:
            return curl_result
        raise exc


def curl_fetch_url(url: str, timeout: int, headers: dict[str, str]) -> FetchResult | None:
    curl_bin = shutil.which("curl")
    if not curl_bin:
        return None

    marker = b"\n__CODEX_CURL_META__\n"
    command = [
        curl_bin,
        "-sL",
        "--max-time",
        str(timeout),
        "-A",
        headers.get("User-Agent", USER_AGENT),
    ]
    for key, value in headers.items():
        if key.lower() == "user-agent":
            continue
        command.extend(["-H", f"{key}: {value}"])
    command.extend(
        [
            "-w",
            "\n__CODEX_CURL_META__\n%{url_effective}\n%{content_type}\n%{http_code}\n",
            url,
        ]
    )
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        return None

    stdout = result.stdout
    index = stdout.rfind(marker)
    if index == -1:
        return None

    body = stdout[:index]
    meta = stdout[index + len(marker) :].decode("utf-8", "ignore").splitlines()
    if len(meta) < 3:
        return None

    final_url = meta[0].strip() or url
    content_type = meta[1].strip()
    try:
        http_code = int(meta[2].strip())
    except ValueError:
        return None
    if http_code >= 400:
        return None
    return FetchResult(url=url, final_url=final_url, content_type=content_type, body=body)


def should_retry_with_curl(result: FetchResult) -> bool:
    content_type = result.content_type.lower()
    if "html" not in content_type:
        return False
    body = result.body[:12000]
    return any(marker in body for marker in CHALLENGE_MARKERS)


def resolve_llm_config(provider: str, model_override: str | None) -> LLMConfig | None:
    model = (model_override or os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL).strip()

    def build(name: str, api_key_env: str, api_url_env: str, default_url: str) -> LLMConfig | None:
        api_key = os.getenv(api_key_env, "").strip()
        if not api_key:
            return None
        api_url = os.getenv(api_url_env, default_url).strip().rstrip("/")
        return LLMConfig(provider=name, api_url=api_url, api_key=api_key, model=model)

    if provider == "openai":
        return build("openai", "OPENAI_API_KEY", "OPENAI_API_URL", DEFAULT_OPENAI_API_URL)
    if provider == "packy":
        return build("packy", "PACKY_API_KEY", "PACKY_API_URL", DEFAULT_PACKY_API_URL)

    return (
        build("openai", "OPENAI_API_KEY", "OPENAI_API_URL", DEFAULT_OPENAI_API_URL)
        or build("packy", "PACKY_API_KEY", "PACKY_API_URL", DEFAULT_PACKY_API_URL)
    )


def extract_json_payload(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("LLM response did not contain JSON")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM JSON payload was not an object")
    return payload


def request_llm_completion(config: LLMConfig, messages: list[dict[str, str]], timeout: int, use_json_mode: bool = True) -> str:
    url = f"{config.api_url}/chat/completions"
    body: dict[str, object] = {
        "model": config.model,
        "temperature": 0,
        "messages": messages,
    }
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}

    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        if use_json_mode and exc.code in (400, 404, 415, 422):
            return request_llm_completion(config, messages, timeout, use_json_mode=False)
        raise

    choices = payload.get("choices", [])
    if not choices:
        raise ValueError("LLM response had no choices")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return "\n".join(text_parts)
    return str(content)


def classify_articles_with_llm(
    articles: list[dict[str, object]],
    config: LLMConfig,
    timeout: int,
    batch_size: int = DEFAULT_LLM_BATCH_SIZE,
) -> dict[str, dict[str, object]]:
    decisions: dict[str, dict[str, object]] = {}
    for start in range(0, len(articles), batch_size):
        batch = articles[start : start + batch_size]
        prompt_items = [
            {
                "id": article["id"],
                "title": article.get("title", ""),
                "summary": article.get("summary", ""),
                "source": article.get("source", ""),
                "url": article.get("url", ""),
            }
            for article in batch
        ]
        messages = [
            {"role": "system", "content": AI_RELEVANCE_RULES},
            {"role": "user", "content": json.dumps({"articles": prompt_items}, ensure_ascii=False)},
        ]
        raw = request_llm_completion(config, messages, timeout)
        payload = extract_json_payload(raw)
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            article_id = str(item.get("id", "")).strip()
            if not article_id:
                continue
            keywords = item.get("keywords", [])
            if not isinstance(keywords, list):
                keywords = []
            decisions[article_id] = {
                "relevant": bool(item.get("relevant", False)),
                "keywords": unique_preserve_order([str(value) for value in keywords])[:5],
            }
    return decisions


def looks_like_feed(result: FetchResult) -> bool:
    content_type = result.content_type.lower()
    if any(token in content_type for token in ("rss", "atom", "xml")):
        return True
    prefix = result.body[:300].lstrip().lower()
    return prefix.startswith(b"<?xml") or prefix.startswith(b"<rss") or prefix.startswith(b"<feed") or prefix.startswith(b"<rdf:rdf")


class FeedDiscoveryParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.feed_urls: list[str] = []
        self._seen: set[str] = set()

    def _add(self, href: str) -> None:
        href = href.strip()
        if not href or href.startswith(("javascript:", "mailto:")):
            return
        absolute = urllib.parse.urljoin(self.base_url, href)
        key = canonicalize_url(absolute)
        if key not in self._seen:
            self._seen.add(key)
            self.feed_urls.append(absolute)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "link":
            rel = data.get("rel", "").lower()
            type_value = data.get("type", "").lower()
            href = data.get("href", "")
            if href and (
                any(token in type_value for token in ("rss+xml", "atom+xml", "xml"))
                or ("alternate" in rel and any(token in href.lower() for token in ("rss", "feed", "atom")))
            ):
                self._add(href)
        elif tag.lower() == "a":
            href = data.get("href", "")
            if href and any(token in href.lower() for token in ("rss", "feed", "atom")):
                self._add(href)


class ArticleLinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "img" and self._href is not None:
            data = {key.lower(): value or "" for key, value in attrs}
            for field in ("alt", "title", "aria-label"):
                if data.get(field):
                    self._text_parts.append(data[field])
            return

        if tag_name != "a":
            return
        data = {key.lower(): value or "" for key, value in attrs}
        href = data.get("href", "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            return
        self._href = urllib.parse.urljoin(self.base_url, href)
        self._text_parts = []
        for field in ("title", "aria-label"):
            if data.get(field):
                self._text_parts.append(data[field])

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = clean_text(" ".join(self._text_parts))
        self.links.append({"url": self._href, "title": text})
        self._href = None
        self._text_parts = []


class ArticleMetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, list[str]] = {}
        self.title_parts: list[str] = []
        self.paragraphs: list[str] = []
        self.time_values: list[str] = []
        self._in_title = False
        self._in_paragraph = False
        self._paragraph_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key.lower(): (value or "").strip() for key, value in attrs}
        tag_name = tag.lower()
        if tag_name == "meta":
            key = (data.get("name") or data.get("property") or data.get("itemprop") or "").lower()
            content = data.get("content", "")
            if key and content:
                self.meta.setdefault(key, []).append(content)
        elif tag_name == "title":
            self._in_title = True
        elif tag_name == "p":
            self._in_paragraph = True
            self._paragraph_parts = []
        elif tag_name == "time":
            datetime_value = data.get("datetime", "")
            if datetime_value:
                self.time_values.append(datetime_value)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_paragraph:
            self._paragraph_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "title":
            self._in_title = False
        elif tag_name == "p" and self._in_paragraph:
            paragraph = clean_text(" ".join(self._paragraph_parts))
            if paragraph:
                self.paragraphs.append(paragraph)
            self._in_paragraph = False
            self._paragraph_parts = []


def extract_attr_text(fragment: str) -> str:
    for field in ("alt", "title", "aria-label"):
        match = re.search(rf'{field}=["\']([^"\']+)["\']', fragment, re.IGNORECASE)
        if match:
            text = clean_text(match.group(1))
            if text:
                return text
    return ""


def regex_extract_links(base_url: str, html_text: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    pattern = re.compile(r"<a\b([^>]*?)href=[\"']([^\"']+)[\"']([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html_text):
        prefix_attrs, href, suffix_attrs, inner_html = match.groups()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        title = clean_text(inner_html)
        if not title:
            title = extract_attr_text(inner_html) or extract_attr_text(prefix_attrs + " " + suffix_attrs)
        links.append({"url": urllib.parse.urljoin(base_url, href.strip()), "title": title})
    return links


def unique_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = clean_text(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def first_meta(meta: dict[str, list[str]], keys: tuple[str, ...]) -> str:
    for key in keys:
        values = meta.get(key.lower(), [])
        for value in values:
            cleaned = clean_text(value)
            if cleaned:
                return cleaned
    return ""


def all_meta(meta: dict[str, list[str]], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(meta.get(key.lower(), []))
    return unique_preserve_order(values)


def parse_json_ld_blocks(html_text: str) -> list[object]:
    blocks: list[object] = []
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html_text, re.IGNORECASE | re.DOTALL):
        payload = raw.strip()
        if not payload:
            continue
        try:
            blocks.append(json.loads(unescape(payload)))
        except Exception:
            continue
    return blocks


def find_json_ld_values(obj: object, target_keys: tuple[str, ...]) -> list[object]:
    results: list[object] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in target_keys:
                results.append(value)
            results.extend(find_json_ld_values(value, target_keys))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_json_ld_values(item, target_keys))
    return results


def extract_author_name(value: object) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            return clean_text(name)
    if isinstance(value, list):
        authors = [extract_author_name(item) for item in value]
        authors = [item for item in authors if item]
        if authors:
            return ", ".join(authors[:3])
    return ""


def first_json_ld_value(blocks: list[object], target_keys: tuple[str, ...]) -> str:
    values = find_json_ld_values(blocks, target_keys)
    for value in values:
        if target_keys == ("author",):
            author = extract_author_name(value)
            if author:
                return author
        elif isinstance(value, str):
            cleaned = clean_text(value)
            if cleaned:
                return cleaned
    return ""


def split_keyword_values(raw_values: list[str]) -> list[str]:
    parts: list[str] = []
    for value in raw_values:
        for item in re.split(r"[,|/]", value):
            cleaned = clean_text(item)
            if cleaned:
                parts.append(cleaned)
    return unique_preserve_order(parts)


def keyword_present(text: str, keyword: str) -> bool:
    if not text or not keyword:
        return False
    escaped = re.escape(keyword.lower())
    if re.fullmatch(r"[a-z0-9\+\-]+", keyword.lower()):
        pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
        return re.search(pattern, text.lower()) is not None
    return keyword.lower() in text.lower()


def one_sentence_summary(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[\.\!\?。！？])\s+", cleaned)
    sentence = parts[0].strip() if parts else cleaned
    if len(sentence) < 40 and len(parts) > 1:
        sentence = f"{sentence} {parts[1].strip()}".strip()
    return truncate_text(sentence, limit=220)


def summary_quality_ok(text: str) -> bool:
    cleaned = clean_text(text).lower()
    if len(cleaned) < 24:
        return False
    bad_markers = (
        "blog min read by",
        "download now",
        "read more",
        "learn more",
        "all rights reserved",
    )
    return not any(marker in cleaned for marker in bad_markers)


def infer_keywords(title: str, summary: str, meta_keywords: list[str], page_text: str) -> list[str]:
    combined = " ".join([title, summary, page_text, " ".join(meta_keywords)]).lower()
    found: list[str] = []
    cves = re.findall(r"\bCVE-\d{4}-\d{4,}\b", combined.upper())
    found.extend(cves)
    for keyword in DEFAULT_AI_KEYWORDS:
        if keyword_present(combined, keyword):
            found.append(keyword)
    found.extend(meta_keywords[:8])
    return unique_preserve_order(found)[:8]


def enrich_article_entry(entry: dict[str, str], source_name: str, timeout: int) -> dict[str, str | list[str]]:
    enriched: dict[str, str | list[str]] = {
        "title": entry.get("title", "").strip(),
        "url": entry.get("url", "").strip(),
        "published": entry.get("published", "").strip(),
        "summary": clean_text(entry.get("summary", "")),
        "author": "",
        "keywords": [],
        "source": source_name,
    }

    url = str(enriched["url"])
    if not url:
        enriched["summary"] = one_sentence_summary(str(enriched["summary"]))
        return enriched

    try:
        result = fetch_url(url, timeout)
    except Exception:
        enriched["summary"] = one_sentence_summary(str(enriched["summary"]))
        return enriched

    html_text = result.body.decode("utf-8", "ignore")
    parser = ArticleMetadataParser()
    parser.feed(html_text)
    json_ld_blocks = parse_json_ld_blocks(html_text)

    meta_summary = first_meta(parser.meta, ("description", "og:description", "twitter:description", "parsely-excerpt"))
    meta_author = first_meta(parser.meta, ("author", "article:author", "parsely-author", "sailthru.author", "dc.creator", "dcterms.creator"))
    json_ld_author = first_json_ld_value(json_ld_blocks, ("author",))
    meta_published = first_meta(
        parser.meta,
        ("article:published_time", "og:published_time", "published_time", "publish-date", "pubdate", "date", "datepublished", "parsely-pub-date"),
    )
    json_ld_published = first_json_ld_value(json_ld_blocks, ("datepublished", "datecreated", "datemodified"))
    meta_keywords = split_keyword_values(
        all_meta(parser.meta, ("keywords", "news_keywords", "article:tag", "parsely-tags"))
    )
    page_title = clean_text(" ".join(parser.title_parts))
    page_text = " ".join(parser.paragraphs[:3])

    if not enriched["title"]:
        enriched["title"] = page_title
    if not enriched["published"]:
        enriched["published"] = meta_published or json_ld_published or (parser.time_values[0] if parser.time_values else "")
    summary_candidates = [str(enriched["summary"]), meta_summary, page_text]
    best_summary = next((item for item in summary_candidates if summary_quality_ok(item)), "")
    if not best_summary:
        best_summary = next((item for item in summary_candidates if clean_text(item)), "")
    enriched["summary"] = one_sentence_summary(best_summary)
    enriched["author"] = meta_author or json_ld_author
    enriched["keywords"] = infer_keywords(str(enriched["title"]), str(enriched["summary"]), meta_keywords, page_text)
    return enriched


def build_feed_candidates(page_url: str, html_text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        key = canonicalize_url(url)
        if key not in seen:
            seen.add(key)
            candidates.append(url)

    parser = FeedDiscoveryParser(page_url)
    parser.feed(html_text)
    for url in parser.feed_urls:
        add(url)

    for url in known_feed_candidates(page_url):
        add(url)

    parsed = urllib.parse.urlsplit(page_url)
    root_url = f"{parsed.scheme}://{parsed.netloc}/"
    page_base = page_url if page_url.endswith("/") else page_url + "/"
    for suffix in COMMON_FEED_SUFFIXES:
        add(urllib.parse.urljoin(root_url, suffix))
        add(urllib.parse.urljoin(page_base, suffix))

    return candidates


def known_feed_candidates(page_url: str) -> list[str]:
    netloc = urllib.parse.urlsplit(page_url).netloc.lower()
    return list(KNOWN_FEED_URLS.get(netloc, []))


def parse_date(value: str) -> tuple[str, datetime | None]:
    text = clean_text(value)
    if not text:
        return "", None
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc).isoformat(), parsedate_to_datetime(text).astimezone(timezone.utc)
    except Exception:
        pass
    normalized = text.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T", 1)):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(), dt.astimezone(timezone.utc)
        except Exception:
            continue
    return text, None


def first_child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(node):
        if local_name(child.tag) in names:
            text = clean_text("".join(child.itertext()))
            if text:
                return text
    return ""


def first_atom_link(node: ET.Element) -> str:
    for child in list(node):
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        rel = child.attrib.get("rel", "alternate").strip().lower()
        if href and rel in ("", "alternate"):
            return href
    return ""


def parse_feed_entries(result: FetchResult) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(result.body)
    except ET.ParseError:
        return []

    root_name = local_name(root.tag)
    entries: list[dict[str, str]] = []

    if root_name == "rss":
        channel = next((child for child in list(root) if local_name(child.tag) == "channel"), root)
        nodes = [child for child in list(channel) if local_name(child.tag) == "item"]
        for node in nodes:
            date_text, _ = parse_date(first_child_text(node, ("pubdate", "date", "updated")))
            entries.append(
                {
                    "title": first_child_text(node, ("title",)),
                    "url": first_child_text(node, ("link",)),
                    "published": date_text,
                    "summary": first_child_text(node, ("description", "encoded", "summary", "content")),
                }
            )
    elif root_name == "feed":
        nodes = [child for child in list(root) if local_name(child.tag) == "entry"]
        for node in nodes:
            date_text, _ = parse_date(first_child_text(node, ("published", "updated", "date")))
            entries.append(
                {
                    "title": first_child_text(node, ("title",)),
                    "url": first_atom_link(node),
                    "published": date_text,
                    "summary": first_child_text(node, ("summary", "content")),
                }
            )
    elif root_name == "rdf":
        nodes = [child for child in list(root) if local_name(child.tag) == "item"]
        for node in nodes:
            date_text, _ = parse_date(first_child_text(node, ("date", "pubdate")))
            entries.append(
                {
                    "title": first_child_text(node, ("title",)),
                    "url": first_child_text(node, ("link",)),
                    "published": date_text,
                    "summary": first_child_text(node, ("description", "summary")),
                }
            )

    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        url = entry.get("url", "").strip()
        title = entry.get("title", "").strip()
        if not url and not title:
            continue
        key = canonicalize_url(url) if url else title.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            {
                "title": title,
                "url": url,
                "published": entry.get("published", "").strip(),
                "summary": entry.get("summary", "").strip(),
            }
        )
    return cleaned


def same_site(base_url: str, candidate_url: str) -> bool:
    base_netloc = urllib.parse.urlsplit(base_url).netloc.lower()
    target_netloc = urllib.parse.urlsplit(candidate_url).netloc.lower()
    return target_netloc == base_netloc or target_netloc.endswith("." + base_netloc) or base_netloc.endswith("." + target_netloc)


def score_article_link(source_url: str, candidate_url: str, title: str) -> int:
    source_path = urllib.parse.urlsplit(source_url).path.lower()
    if not same_site(source_url, candidate_url):
        return -100
    parsed = urllib.parse.urlsplit(candidate_url)
    path = parsed.path.lower()
    if not path or path == "/" or any(token in path for token in BAD_LINK_HINTS):
        return -50
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip)$", path):
        return -50

    score = 0
    if DATE_RE.search(path):
        score += 5
    if any(token in path for token in ARTICLE_HINTS):
        score += 3
    if "/blog" in source_path and "/blog" not in path and not DATE_RE.search(path):
        score -= 4
    if 12 <= len(title) <= 180:
        score += 3
    elif title:
        score += 1
    if parsed.query:
        score -= 1
    if path.count("/") <= 1:
        score -= 2
    return score


def enrich_title(url: str, timeout: int) -> str:
    try:
        result = fetch_url(url, timeout)
    except Exception:
        return ""
    html_text = result.body.decode("utf-8", "ignore")
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)',
        r"<title>(.*?)</title>",
    ):
        match = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
        if match:
            return clean_text(match.group(1))
    return ""


def parse_homepage_articles(source_url: str, html_text: str, timeout: int, per_source: int) -> list[dict[str, str]]:
    parser = ArticleLinkParser(source_url)
    parser.feed(html_text)
    raw_links = list(parser.links)
    if len(raw_links) < per_source:
        raw_links.extend(regex_extract_links(source_url, html_text))
    ranked: list[tuple[int, dict[str, str]]] = []
    seen: set[str] = set()
    for link in raw_links:
        url = canonicalize_url(link["url"])
        if url in seen or canonicalize_url(source_url) == url:
            continue
        seen.add(url)
        score = score_article_link(source_url, url, link["title"])
        if score <= 0:
            continue
        ranked.append((score, {"title": link["title"], "url": url, "published": "", "summary": ""}))

    ranked.sort(key=lambda item: (-item[0], item[1]["url"]))
    items = [entry for _, entry in ranked[:per_source]]
    for entry in items:
        if not entry["title"]:
            entry["title"] = enrich_title(entry["url"], timeout)
    return [entry for entry in items if entry["title"] or entry["url"]]


def matches_keywords(entry: dict[str, str], keywords: list[str]) -> bool:
    if not keywords:
        return True
    keyword_values = entry.get("keywords", [])
    keyword_text = " ".join(keyword_values) if isinstance(keyword_values, list) else str(keyword_values)
    summary_preview = truncate_text(entry.get("summary", ""), limit=320)
    haystack = " ".join((entry.get("title", ""), summary_preview, entry.get("url", ""), keyword_text)).lower()
    return any(keyword_present(haystack, keyword) for keyword in keywords)


def within_since_days(entry: dict[str, str], since_days: int | None) -> bool:
    if since_days is None:
        return True
    published = entry.get("published", "")
    if not published:
        return True
    _, dt = parse_date(published)
    if dt is None:
        return True
    return dt >= now_utc() - timedelta(days=since_days)


def filter_entries(entries: list[dict[str, str]], keywords: list[str], since_days: int | None, limit: int) -> list[dict[str, str]]:
    filtered = [entry for entry in entries if matches_keywords(entry, keywords) and within_since_days(entry, since_days)]
    filtered.sort(key=lambda entry: entry.get("published", ""), reverse=True)
    return filtered[:limit]


def enrich_entries(entries: list[dict[str, str]], source_name: str, timeout: int) -> list[dict[str, str | list[str]]]:
    return [enrich_article_entry(entry, source_name, timeout) for entry in entries]


def select_recent_entries(entries: list[dict[str, str]], since_days: int | None, limit: int) -> list[dict[str, str]]:
    filtered = [entry for entry in entries if within_since_days(entry, since_days)]
    filtered.sort(key=lambda entry: entry.get("published", ""), reverse=True)
    return filtered[:limit]


def apply_topic_filter(
    results: list[dict[str, object]],
    keywords: list[str],
    classifier_mode: str,
    llm_config: LLMConfig | None,
    llm_timeout: int,
    per_source: int,
) -> tuple[str, str]:
    effective_mode = classifier_mode
    if effective_mode == "auto":
        effective_mode = "llm" if llm_config else "keyword"
    if effective_mode == "llm" and llm_config is None:
        raise SystemExit("Topic classifier mode 'llm' requires OPENAI_API_KEY or PACKY_API_KEY")

    article_refs: list[dict[str, object]] = []
    for result_index, result in enumerate(results):
        for entry_index, entry in enumerate(result["entries"]):
            article_refs.append(
                {
                    "id": f"{result_index}:{entry_index}",
                    "result_index": result_index,
                    "entry_index": entry_index,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "url": entry.get("url", ""),
                    "source": result.get("source", ""),
                    "keywords": entry.get("keywords", []),
                }
            )

    relevant_ids: set[str] = set()
    if effective_mode == "keyword":
        for ref in article_refs:
            if matches_keywords(ref, keywords):
                relevant_ids.add(str(ref["id"]))
    else:
        ambiguous: list[dict[str, object]] = []
        for ref in article_refs:
            if matches_keywords(ref, keywords):
                relevant_ids.add(str(ref["id"]))
            else:
                ambiguous.append(ref)
        decisions = classify_articles_with_llm(ambiguous, llm_config, llm_timeout) if ambiguous and llm_config else {}
        for ref in ambiguous:
            decision = decisions.get(str(ref["id"]))
            if not decision or not decision.get("relevant"):
                continue
            relevant_ids.add(str(ref["id"]))
            result = results[int(ref["result_index"])]
            entry = result["entries"][int(ref["entry_index"])]
            existing_keywords = entry.get("keywords", [])
            llm_keywords = decision.get("keywords", [])
            if isinstance(existing_keywords, list) and isinstance(llm_keywords, list):
                entry["keywords"] = unique_preserve_order([str(value) for value in existing_keywords + llm_keywords])[:8]

    for result_index, result in enumerate(results):
        filtered_entries = []
        for entry_index, entry in enumerate(result["entries"]):
            if f"{result_index}:{entry_index}" in relevant_ids:
                filtered_entries.append(entry)
        filtered_entries.sort(key=lambda entry: entry.get("published", ""), reverse=True)
        result["entries"] = filtered_entries[:per_source]
        if not result["entries"] and not result.get("error"):
            result["error"] = "no matching articles"

    provider_name = llm_config.provider if llm_config else "none"
    return effective_mode, provider_name


def collect_source(source: dict[str, str], timeout: int, per_source: int, since_days: int | None) -> dict[str, object]:
    name = source.get("Platform", "").strip() or "Unknown"
    url = source.get("Portal", "").strip()
    category = source.get("Category", "").strip() or "Uncategorized"
    notes = source.get("Notes", "").strip()

    if not url:
        return {
            "source": name,
            "category": category,
            "url": "",
            "notes": notes,
            "method": "skipped",
            "feed_url": "",
            "entries": [],
            "error": "missing source URL",
        }

    for feed_url in known_feed_candidates(url):
        try:
            feed_result = fetch_url(
                feed_url,
                timeout,
                headers={"Accept": "application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8"},
            )
        except Exception:
            continue
        if not looks_like_feed(feed_result):
            continue
        raw_entries = parse_feed_entries(feed_result)
        candidate_limit = max(per_source * 3, 8)
        entries = select_recent_entries(raw_entries, since_days, candidate_limit)
        entries = enrich_entries(entries, name, timeout)
        if entries:
            return {
                "source": name,
                "category": category,
                "url": url,
                "notes": notes,
                "method": "feed",
                "feed_url": feed_result.final_url,
                "entries": entries,
                "error": "",
            }

    try:
        homepage = fetch_url(url, timeout)
    except urllib.error.HTTPError as exc:
        return {
            "source": name,
            "category": category,
            "url": url,
            "notes": notes,
            "method": "error",
            "feed_url": "",
            "entries": [],
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # pragma: no cover
        return {
            "source": name,
            "category": category,
            "url": url,
            "notes": notes,
            "method": "error",
            "feed_url": "",
            "entries": [],
            "error": str(exc),
        }

    if looks_like_feed(homepage):
        raw_entries = parse_feed_entries(homepage)
        candidate_limit = max(per_source * 3, 8)
        entries = select_recent_entries(raw_entries, since_days, candidate_limit)
        entries = enrich_entries(entries, name, timeout)
        return {
            "source": name,
            "category": category,
            "url": homepage.final_url,
            "notes": notes,
            "method": "feed",
            "feed_url": homepage.final_url,
            "entries": entries,
            "error": "",
        }

    html_text = homepage.body.decode("utf-8", "ignore")
    for candidate in build_feed_candidates(homepage.final_url, html_text):
        try:
            feed_result = fetch_url(candidate, timeout, headers={"Accept": "application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.8"})
        except Exception:
            continue
        if not looks_like_feed(feed_result):
            continue
        raw_entries = parse_feed_entries(feed_result)
        candidate_limit = max(per_source * 3, 8)
        entries = select_recent_entries(raw_entries, since_days, candidate_limit)
        entries = enrich_entries(entries, name, timeout)
        if entries:
            return {
                "source": name,
                "category": category,
                "url": homepage.final_url,
                "notes": notes,
                "method": "feed",
                "feed_url": feed_result.final_url,
                "entries": entries,
                "error": "",
            }

    candidate_limit = max(per_source * 3, 6)
    raw_entries = parse_homepage_articles(homepage.final_url, html_text, timeout, candidate_limit)
    enriched_entries = enrich_entries(raw_entries, name, timeout)
    entries = select_recent_entries(enriched_entries, since_days, candidate_limit)
    return {
        "source": name,
        "category": category,
        "url": homepage.final_url,
        "notes": notes,
        "method": "homepage",
        "feed_url": "",
        "entries": entries,
        "error": "" if entries else "no feed or article links found",
    }


def flatten_articles(results: list[dict[str, object]]) -> list[dict[str, object]]:
    articles: list[dict[str, object]] = []
    for result in results:
        for entry in result["entries"]:
            article = dict(entry)
            article["source"] = result["source"]
            article["source_url"] = result["url"]
            article["category"] = result["category"]
            articles.append(article)
    articles.sort(key=lambda article: article.get("published", ""), reverse=True)
    return articles


def render_markdown(
    results: list[dict[str, object]],
    generated_at: str,
    keywords: list[str],
    since_days: int | None,
    topic_classifier: str,
    llm_provider: str,
) -> str:
    parts = [
        "# Security Blog Digest",
        "",
        f"Generated: {generated_at}",
        "",
    ]

    processed = sum(1 for result in results if result["method"] != "skipped")
    with_entries = sum(1 for result in results if result["entries"])
    skipped = sum(1 for result in results if result["method"] == "skipped")
    articles = flatten_articles(results)
    parts.append(f"Processed sources: {processed}")
    parts.append(f"Sources with entries: {with_entries}")
    parts.append(f"Skipped sources: {skipped}")
    parts.append(f"Article count: {len(articles)}")
    parts.append(f"Since days: {since_days if since_days is not None else 'all'}")
    parts.append(f"Keywords: {', '.join(keywords) if keywords else 'all topics'}")
    parts.append(f"Topic classifier: {topic_classifier}")
    parts.append(f"LLM provider: {llm_provider}")
    parts.append("")

    parts.append("## Articles")
    parts.append("")
    for article in articles:
        title = str(article.get("title", "")).strip() or str(article.get("url", "")).strip()
        published = str(article.get("published", "")).strip() or "undated"
        source = str(article.get("source", "")).strip()
        author = str(article.get("author", "")).strip() or "unknown"
        entry_url = str(article.get("url", "")).strip()
        summary = truncate_text(str(article.get("summary", "")), limit=220)
        keyword_list = article.get("keywords", [])
        keyword_text = ", ".join(keyword_list) if isinstance(keyword_list, list) and keyword_list else "none"
        parts.append(f"### {title}")
        parts.append("")
        parts.append(f"- Time: {published}")
        parts.append(f"- Source: {source}")
        parts.append(f"- Author: {author}")
        parts.append(f"- Link: {entry_url}")
        parts.append(f"- Summary: {summary or 'none'}")
        parts.append(f"- Keywords: {keyword_text}")
        parts.append("")

    failures = [result for result in results if not result["entries"]]
    if failures:
        parts.append("## Source Issues")
        parts.append("")
        for result in failures:
            parts.append(f"- {result['source']}: {result['error'] or 'no matching articles'}")
    return "\n".join(parts).rstrip() + "\n"


def load_sources(input_paths: list[Path]) -> list[dict[str, str]]:
    rows = read_rows(input_paths)
    return dedupe(rows)


def parse_args() -> argparse.Namespace:
    default_csv = Path(__file__).resolve().parent.parent / "references" / "default-sources.csv"
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", type=Path, help="Input CSV file. Can be used multiple times.")
    parser.add_argument("--use-default-sources", action="store_true", help="Use the skill's built-in curated source list.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write output to a file instead of stdout.")
    parser.add_argument("--keywords", help="Comma-separated keyword filter for title, summary, or URL.")
    parser.add_argument("--all-topics", action="store_true", help="Disable the default AI-security topic filter.")
    parser.add_argument("--topic-classifier", choices=("auto", "keyword", "llm"), default="auto", help="Use keyword rules, LLM classification, or auto-detect based on available API keys.")
    parser.add_argument("--llm-provider", choices=("auto", "openai", "packy"), default="auto", help="Choose which API credentials and base URL to use for LLM topic classification.")
    parser.add_argument("--llm-model", help="Override LLM model. Defaults to LLM_MODEL or gpt-5.4.")
    parser.add_argument("--llm-timeout", type=int, default=DEFAULT_LLM_TIMEOUT, help="Timeout in seconds for LLM API requests.")
    parser.add_argument("--since-days", type=int, default=DEFAULT_SINCE_DAYS, help="Only keep entries within the last N days when the source provides dates.")
    parser.add_argument("--per-source", type=int, default=5, help="Maximum number of entries per source.")
    parser.add_argument("--limit-sources", type=int, help="Limit how many sources to process.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--workers", type=int, default=6, help="Number of concurrent fetch workers.")
    parser.add_argument("--source-filter", help="Only process sources whose name or URL contains this substring.")
    args = parser.parse_args()

    input_paths = list(args.input or [])
    if args.use_default_sources or not input_paths:
        input_paths.insert(0, default_csv)
    args.input_paths = input_paths
    return args


def main() -> int:
    args = parse_args()
    if args.all_topics:
        keywords: list[str] = []
    elif args.keywords:
        keywords = [item.strip().lower() for item in args.keywords.split(",") if item.strip()]
    else:
        keywords = list(DEFAULT_AI_KEYWORDS)
    sources = load_sources(args.input_paths)
    llm_config = None if args.all_topics else resolve_llm_config(args.llm_provider, args.llm_model)

    if args.source_filter:
        needle = args.source_filter.strip().lower()
        sources = [
            source
            for source in sources
            if needle in source.get("Platform", "").lower() or needle in source.get("Portal", "").lower()
        ]
    if args.limit_sources:
        sources = sources[: args.limit_sources]

    results: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(args.workers, 1)) as executor:
        futures = [
            executor.submit(collect_source, source, args.timeout, args.per_source, args.since_days)
            for source in sources
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: (str(item["category"]), str(item["source"])))
    if not args.all_topics:
        effective_topic_classifier, llm_provider = apply_topic_filter(
            results,
            keywords,
            args.topic_classifier,
            llm_config,
            args.llm_timeout,
            args.per_source,
        )
    else:
        effective_topic_classifier, llm_provider = ("all", llm_config.provider if llm_config else "none")
    generated_at = now_utc().isoformat()
    payload: str
    if args.format == "json":
        articles = flatten_articles(results)
        payload = json.dumps(
            {
                "generated_at": generated_at,
                "inputs": [str(path) for path in args.input_paths],
                "since_days": args.since_days,
                "keywords": keywords,
                "topic_classifier": effective_topic_classifier,
                "llm_provider": llm_provider,
                "llm_model": llm_config.model if llm_config else "",
                "articles": articles,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    else:
        payload = render_markdown(
            results,
            generated_at,
            keywords,
            args.since_days,
            effective_topic_classifier,
            llm_provider,
        )

    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
