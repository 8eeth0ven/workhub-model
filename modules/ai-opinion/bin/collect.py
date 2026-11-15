#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect public AI product headlines and bounded per-run deltas."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import html
from http.client import HTTPException, IncompleteRead
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = "WorkhubAIOpinion/1.0 (public headline RSS reader)"
MODULE_ID = "ai-opinion"
SEEN_DAYS = 14
MAX_SEEN_ITEMS = 10000
MAX_ALIASES = 8
MAX_STATE_BYTES = 24 * 1024 * 1024
SECTIONS = {'domestic': '国内 AI 产品与大模型',
 'international': '国际 AI 产品',
 'hardware': 'AI 硬件与机器人',
 'voices': 'AI 人物发言',
 'hot': 'AI 相关热搜'}
GOOGLE_QUERIES = [('domestic', 'DeepSeek OR 深度求索'),
 ('domestic', '通义千问 OR 豆包 OR 字节跳动 AI'),
 ('domestic', '月之暗面 OR Kimi OR 智谱 OR 智谱清言'),
 ('domestic', '文心一言 OR 腾讯混元 OR 腾讯元宝 OR 讯飞星火'),
 ('domestic', 'MiniMax OR 阶跃星辰 OR 零一万物 OR 百川智能 OR 快手可灵'),
 ('domestic', 'AI大模型 OR 国产大模型 OR 人工智能大模型'),
 ('domestic', 'AI智能体 OR AI Agent OR Manus'),
 ('international', 'OpenAI OR ChatGPT'),
 ('international', 'Anthropic OR Claude'),
 ('international', 'Google Gemini OR DeepMind'),
 ('international', 'xAI OR Grok'),
 ('international', 'Sora OR Veo OR Midjourney'),
 ('international', 'Cursor OR GitHub Copilot OR AI coding'),
 ('international', '英伟达 OR Nvidia'),
 ('hardware', 'AI眼镜 OR AI硬件 OR AI玩具'),
 ('hardware', '人形机器人 OR 具身智能 OR 宇树 OR 智元'),
 ('voices', '(马斯克 OR "Elon Musk") (AI OR 人工智能) (发文 OR 表态 OR 发言 OR 演讲)'),
 ('voices', '(奥特曼 OR "Sam Altman") (AI OR 人工智能) (发言 OR 演讲 OR 警告)'),
 ('voices', '(黄仁勋 OR "Jensen Huang") (AI OR 人工智能) (发言 OR 演讲 OR 观点)'),
 ('voices', '(梁文锋 OR 杨植麟 OR 王兴兴) (AI OR 人工智能 OR 机器人) (发言 OR 表态 OR 演讲)'),
 ('voices', '(李彦宏 OR 周鸿祎 OR 王小川) (AI OR 人工智能) (言论 OR 发言 OR 演讲)'),
 ('voices',
  '("Bill Gates" OR "Jensen Huang" OR "Sundar Pichai") (AI OR 人工智能) (says OR warns OR speech OR '
  'interview)'),
 ('voices', '(扎克伯格 OR 贝索斯 OR 库克) (AI OR 人工智能) (表态 OR 发言 OR 演讲)')]
RISK_TERMS = {'high': ['泄露',
          '数据安全',
          '诈骗',
          '自杀',
          '宕机',
          '瘫痪',
          '侵权',
          '抄袭',
          '诉讼',
          '起诉',
          '被盗',
          '黑客',
          '漏洞',
          '禁购',
          '禁售',
          '驱逐',
          '封禁',
          'recall',
          'breach',
          'outage',
          'lawsuit',
          'sued',
          'copyright',
          'leak',
          'hack',
          'scam',
          'exploit',
          'ban',
          'breaches',
          'outages',
          'lawsuits',
          'leaks',
          'leaked',
          'hacked',
          'exploits',
          'banned'],
 'medium': ['裁员',
            '亏损',
            '推迟',
            '延期',
            '难产',
            '下架',
            '停服',
            '争议',
            '质疑',
            '翻车',
            '降价',
            '反垄断',
            '被查',
            '禁令',
            '道歉',
            '刷屏翻车',
            'layoff',
            'loss',
            'delay',
            'backlash',
            'ban',
            'slump',
            'plunge',
            'criticism',
            'layoffs',
            'losses',
            'delays',
            'delayed'],
 'positive': ['发布',
              '上线',
              '开源',
              '融资',
              '破纪录',
              '登顶',
              '第一',
              '夺冠',
              '突破',
              '爆火',
              '刷榜',
              '里程碑',
              '纪录',
              'launched',
              'launch',
              'unveil',
              'release',
              'open-source',
              'open source',
              'funding',
              'record',
              'top',
              'surge',
              'soar',
              'SOTA']}
NOISE = ['Tokenized',
 '币价',
 '实时价格',
 '招聘',
 '校招',
 '社招',
 '实习',
 '彩金',
 '售楼',
 '楼市',
 '四大AI预测',
 'app送',
 '营销中心',
 '热销中',
 '@豆包AI热搜',
 '@AI豆包热搜',
 '奇博体育',
 '网页版登陆',
 '若曦说泰语',
 'A片',
 '做爰']
HOT_WORDS = ['AI',
 '人工智能',
 '大模型',
 'OpenAI',
 'ChatGPT',
 'DeepSeek',
 '豆包',
 '通义',
 'Kimi',
 '智谱',
 '文心',
 'Gemini',
 'Claude',
 'Grok',
 'Sora',
 '英伟达',
 '机器人',
 '智能体',
 '具身',
 'Manus',
 'GPT',
 '算力',
 '芯片',
 'Anthropic',
 'Copilot',
 'Midjourney']
ICONS = {"high": "🔴", "medium": "🟡", "positive": "🟢", "neutral": "⚪"}


class FetchFailure(Exception):
    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code, self.status = code, status


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def term_matches(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9 -]+", term, re.I):
        return re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I) is not None
    return term.casefold() in text.casefold()


def classify(title: str) -> tuple[str, list[str]]:
    for risk, terms in RISK_TERMS.items():
        matches = [term for term in terms if term_matches(title, term)]
        if matches:
            return risk, matches
    return "neutral", []


def normalized(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.casefold())


def public_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        if len(value) > 4096 or parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            return ""
        if any(ch in value for ch in "\r\n\t"):
            return ""
        return value.strip()
    except ValueError:
        return ""


def publication(value: str, now: datetime, days: int) -> tuple[str | None, str | None]:
    try:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError):
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None, "unknown_date"
        dt = dt.astimezone(UTC)
        if dt > now:
            return None, "future_date"
        if dt < now - timedelta(days=days):
            return None, "outside_window"
        return iso(dt), None
    except (ValueError, TypeError, OverflowError, AttributeError):
        return None, "unknown_date"


def load_config(path: Path | None) -> dict:
    config = {"window_days": 2, "timezone": "Asia/Shanghai", "workers": 4, "timeout_seconds": 15,
              "retries": 1, "proxy": "", "proxy_fallback_direct": False, "max_items_per_source": 25}
    if path:
        supplied = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(supplied, dict):
            raise ValueError("configuration must be a JSON object")
        unknown = set(supplied) - (set(config) | {"enabled_sources"})
        if unknown:
            raise ValueError("configuration contains unsupported fields")
        config.update(supplied)
    for key, minimum, maximum in [("window_days", 1, 30), ("workers", 1, 8), ("timeout_seconds", 1, 60),
                                   ("retries", 0, 2), ("max_items_per_source", 1, 25)]:
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
            raise ValueError("invalid numeric configuration: " + key)
        if key != "timeout_seconds" and not isinstance(value, int):
            raise ValueError("integer required: " + key)
    if not isinstance(config["proxy_fallback_direct"], bool):
        raise ValueError("proxy_fallback_direct must be boolean")
    proxy = config["proxy"]
    if not isinstance(proxy, str):
        raise ValueError("proxy must be a string")
    if proxy:
        parsed = urlsplit(proxy)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or
                parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise ValueError("proxy must be an HTTP(S) origin without credentials")
    if not isinstance(config["timezone"], str):
        raise ValueError("timezone must be a string")
    ZoneInfo(config["timezone"])
    return config


def sources(config: dict) -> list[dict]:
    result = []
    for n, (section, query) in enumerate(GOOGLE_QUERIES, 1):
        params = urlencode({"q": query + f" when:{config['window_days']}d", "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
        result.append({"id": f"google-{n:02d}", "name": "Google News · " + query, "section": section,
                       "url": "https://news.google.com/rss/search?" + params, "kind": "rss", "international": True})
    result.extend([
        {"id": "techcrunch-ai", "name": "TechCrunch AI", "section": "international", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "kind": "rss", "international": True},
        {"id": "baidu", "name": "百度 AI 相关热搜", "section": "hot", "url": "https://top.baidu.com/api/board?platform=wise&tab=realtime", "kind": "baidu", "international": False},
    ])
    selected = config.get("enabled_sources")
    if selected is not None:
        ids = {s["id"] for s in result}
        if (not isinstance(selected, list) or not selected or any(not isinstance(i, str) or i not in ids for i in selected)):
            raise ValueError("enabled_sources must contain known source IDs")
        result = [s for s in result if s["id"] in selected]
    return result


def read_response(source: dict, proxy: str, timeout: float) -> tuple[bytes, int]:
    # ProxyHandler({}) deliberately ignores ambient *_PROXY settings. Routes are explicit.
    handler = ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    request = Request(source["url"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, application/json;q=0.9, */*;q=0.2"})
    deadline = time.monotonic() + timeout
    try:
        with build_opener(handler).open(request, timeout=timeout) as response:
            if response.status != 200:
                raise FetchFailure("http_status", response.status)
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchFailure("timeout", response.status)
                # read() may wait for an entire buffer while a peer trickles bytes.
                # read1() returns after at most one underlying read, so the deadline
                # is checked even when a remote source never stops sending slowly.
                transport = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if transport is not None:
                    transport.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise FetchFailure("response_too_large", response.status)
            if not size:
                raise FetchFailure("empty_response", response.status)
            return b"".join(chunks), response.status
    except HTTPError as error:
        raise FetchFailure("http_status", error.code) from None
    except IncompleteRead:
        raise FetchFailure("incomplete_response") from None
    except HTTPException:
        raise FetchFailure("http_protocol_error") from None
    except FetchFailure:
        raise
    except (TimeoutError, socket.timeout):
        raise FetchFailure("timeout") from None
    except URLError as error:
        code = "timeout" if isinstance(error.reason, (TimeoutError, socket.timeout)) else "network_error"
        raise FetchFailure(code) from None
    except (OSError, ValueError):
        raise FetchFailure("network_error") from None


def xml_text(element: ET.Element, name: str) -> str:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == name:
            return "".join(child.itertext()).strip()
    return ""


def parse_rss(raw: bytes, source: dict) -> list[dict]:
    if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
        raise FetchFailure("unsafe_xml")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise FetchFailure("xml_parse_error") from None
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag not in ("rss", "feed", "rdf"):
        raise FetchFailure("not_a_feed")
    result = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        title = html.unescape(xml_text(element, "title"))
        origin = xml_text(element, "source") or source["name"]
        if source["id"].startswith("google-") and title.endswith(" - " + origin):
            title = title[:-(len(origin) + 3)].strip()
        link = xml_text(element, "link")
        if not link:
            for child in element:
                if child.tag.rsplit("}", 1)[-1] == "link" and child.get("rel", "alternate") == "alternate":
                    link = child.get("href", "")
                    break
        result.append({"title": title, "url": link, "source": origin,
                       "date": xml_text(element, "pubDate") or xml_text(element, "published") or xml_text(element, "updated") or xml_text(element, "date")})
        if len(result) >= 1000:
            break
    return result


def parse_baidu(raw: bytes) -> list[dict]:
    try:
        payload = json.loads(raw)
    except RecursionError:
        raise FetchFailure("json_structure_limit") from None
    except (ValueError, UnicodeError):
        raise FetchFailure("json_parse_error") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), (dict, list)):
        raise FetchFailure("unexpected_json_schema")
    result, stack = [], [payload["data"]]
    visited = 0
    while stack:
        obj = stack.pop()
        visited += 1
        if visited > 20000:
            raise FetchFailure("json_structure_limit")
        if isinstance(obj, dict):
            word = obj.get("word")
            if isinstance(word, str) and word.strip():
                result.append({"title": word.strip(), "url": "https://www.baidu.com/s?wd=" + quote(word.strip()),
                               "source": "百度热搜", "rank": obj.get("index")})
            stack.extend(reversed(list(obj.values())))
        elif isinstance(obj, list):
            stack.extend(reversed(obj))
    return result


def fetch_source(source: dict, config: dict, now: datetime) -> tuple[list[dict], dict]:
    status = {"id": source["id"], "name": source["name"], "section": source["section"], "state": "error",
              "fetched_count": 0, "accepted_count": 0, "http_status": None, "route": "direct",
              "error_code": None, "checked_at": iso(now), "attempts": [], "rejected": {}}
    routes = [config["proxy"]] if source["international"] and config["proxy"] else [""]
    if routes[0] and config["proxy_fallback_direct"]:
        routes.append("")
    raw = None
    for route in routes:
        for attempt in range(config["retries"] + 1):
            label = "proxy" if route else "direct"
            try:
                raw, http_status = read_response(source, route, config["timeout_seconds"])
                status.update(http_status=http_status, route=label, error_code=None)
                parsed = parse_baidu(raw) if source["kind"] == "baidu" else parse_rss(raw, source)
                status["attempts"].append({"route": label, "http_status": http_status, "result": "parsed"})
                break
            except FetchFailure as error:
                http_status = status["http_status"] if raw is not None else error.status
                status.update(http_status=http_status, route=label, error_code=error.code)
                status["attempts"].append({"route": label, "http_status": http_status, "result": error.code})
                raw = None
                # Malformed documents and permanent client errors do not benefit from repeating the same request.
                if error.code not in ("network_error", "timeout", "empty_response", "incomplete_response", "http_protocol_error") and error.status not in (429, 500, 502, 503, 504):
                    break
                if attempt < config["retries"]:
                    time.sleep(min(0.25 * (attempt + 1), 0.5))
        if raw is not None:
            break
    if raw is None:
        return [], status
    status["fetched_count"] = len(parsed)
    accepted = []

    def reject(reason: str) -> None:
        status["rejected"][reason] = status["rejected"].get(reason, 0) + 1

    for row in parsed:
        title = re.sub(r"\s+", " ", row["title"]).strip()[:1000]
        link = public_url(row["url"])
        if not title or not link:
            reject("invalid_title_or_url")
            continue
        if any(term_matches(title, word) for word in NOISE):
            reject("excluded_noise")
            continue
        if source["kind"] == "baidu":
            if not any(term_matches(title, word) for word in HOT_WORDS):
                reject("not_ai_related")
                continue
            published_at, time_basis = None, "observed"
        else:
            published_at, reason = publication(row["date"], now, config["window_days"])
            if reason:
                reject(reason)
                continue
            time_basis = "published"
        risk, terms = classify(title)
        item = {"id": hashlib.sha256((normalized(title) + "\0" + link).encode()).hexdigest()[:20],
                "section": source["section"], "title": title, "url": link, "source": row["source"][:200],
                "published_at": published_at, "observed_at": iso(now), "time_basis": time_basis,
                "risk": risk, "risk_terms": terms}
        if source["kind"] == "baidu" and isinstance(row.get("rank"), (str, int)):
            item["rank"] = str(row["rank"])[:20]
        accepted.append(item)
        if len(accepted) >= config["max_items_per_source"]:
            break
    status["state"] = "ok" if accepted else "empty"
    status["accepted_count"] = len(accepted)
    if not accepted:
        status["empty_reason"] = "no_entries" if not parsed else "no_eligible_entries"
    return accepted, status


def make_report(config: dict, now: datetime, results: list[tuple[list[dict], dict]], demo: bool = False) -> dict:
    seen, seen_urls, items, statuses = set(), set(), [], []
    for rows, status in results:
        count = 0
        for row in rows:
            key = normalized(row["title"])
            url_key = item_aliases(row)[0]
            if not key or key in seen or url_key in seen_urls:
                status["rejected"]["duplicate_title"] = status["rejected"].get("duplicate_title", 0) + 1
                continue
            seen.add(key)
            seen_urls.add(url_key)
            items.append(row)
            count += 1
        status["accepted_count"] = count
        if status["state"] == "ok" and not count:
            status.update(state="empty", empty_reason="duplicate_only")
        if demo:
            status["is_demo"] = True
        statuses.append(status)
    errors = sum(s["state"] == "error" for s in statuses)
    empty = sum(s["state"] == "empty" for s in statuses)
    state = "unavailable" if errors == len(statuses) else ("partial" if errors else "complete")
    return {"schema_version": 1, "module_id": MODULE_ID, "run_id": uuid.uuid4().hex, "generated_at": iso(now),
            "report_date": now.astimezone(ZoneInfo(config["timezone"])).date().isoformat(),
            "window_days": config["window_days"], "is_demo": demo,
            "coverage": {"state": state, "total_sources": len(statuses), "ok_sources": len(statuses) - errors - empty,
                         "empty_sources": empty, "error_sources": errors, "accepted_items": len(items),
                         "notice": "标题关键词仅作线索；未命中不表示没有负面事件。热搜按观察时间记录，不能据此推断发布时间。"},
            "items": items, "sources": statuses}


def demo_report(config: dict, now: datetime) -> dict:
    examples = [
        ("domestic", "虚构示例：某 AI 产品发布模型说明", "positive"),
        ("international", "Fictional example: an AI service outage report awaiting confirmation", "high"),
        ("hardware", "虚构示例：机器人产品开放演示预约", "neutral"),
        ("voices", "虚构示例：某研究者谈 AI 评测边界", "neutral"),
        ("hot", "虚构示例：AI 产品话题进入热搜", "neutral"),
    ]
    rows = []
    for n, (section, title, risk) in enumerate(examples, 1):
        rows.append({"id": f"demo-{n}", "section": section, "title": title,
                     "url": f"https://example.com/fictional-ai-story-{n}", "source": "虚构演示 / Fictional demo",
                     "published_at": None if section == "hot" else iso(now - timedelta(hours=n)),
                     "observed_at": iso(now), "time_basis": "observed" if section == "hot" else "published",
                     "risk": risk, "risk_terms": ["outage"] if risk == "high" else [], "is_demo": True})
    status = {"id": "fictional-demo", "name": "离线虚构演示", "section": "domestic", "state": "ok",
              "fetched_count": len(rows), "accepted_count": len(rows), "http_status": None, "route": "offline",
              "error_code": None, "checked_at": iso(now), "attempts": [], "rejected": {}}
    return make_report(config, now, [(rows, status)], demo=True)


def markdown(report: dict) -> str:
    coverage, items = report["coverage"], report["items"]
    label = " · 虚构演示 / FICTIONAL DEMO" if report["is_demo"] else ""
    lines = [f"# AI 产品舆情日报 {report['report_date']}{label}", "", f"> 采集时间 {report['generated_at']} · RSS 精确过去 {report['window_days']} 天", "",
             f"源覆盖：{coverage['state']}；可用 {coverage['ok_sources']}，无新增 {coverage['empty_sources']}，失败 {coverage['error_sources']}。", "",
             "标题关键词仅提示待核实线索，不构成事件属实或风险结论。未命中不表示没有负面事件。", "",
             "## ⚠️ 负面线索", ""]

    def row(item: dict) -> str:
        title = item["title"].replace("[", "\\[").replace("]", "\\]")
        url = item["url"].replace("(", "%28").replace(")", "%29").replace(" ", "%20")
        date = item["published_at"] or ("观察于 " + item["observed_at"])
        origin = item["source"].replace("\n", " ").replace("\r", " ")
        return f"- {ICONS[item['risk']]} [{title}]({url}) — {origin} · {date}"

    negative = [i for i in items if i["risk"] in ("high", "medium")]
    if negative:
        lines.extend(row(i) for i in sorted(negative, key=lambda i: 0 if i["risk"] == "high" else 1))
    elif coverage["state"] != "complete":
        lines.append("- 本轮覆盖不足，不能判断是否存在负面线索；先检查源状态并人工核对专项条目。")
    else:
        lines.append("- 当前已收集标题未命中负面词，仍需人工核对专项内容，不能推断不存在负面事件。")
    for section, title in SECTIONS.items():
        lines.extend(["", "## " + title, ""])
        selected = [i for i in items if i["section"] == section]
        lines.extend([row(i) for i in selected] or ["- 本轮没有可展示条目；详见源状态。"])
    lines.extend(["", "## 源状态", ""])
    for source in report["sources"]:
        lines.append(f"- {source['name']}：{source['state']}；原始 {source['fetched_count']}，收录 {source['accepted_count']}；"
                     f"HTTP {source['http_status'] if source['http_status'] is not None else '—'}；路由 {source['route']}；"
                     f"原因 {source.get('error_code') or source.get('empty_reason') or '—'}")
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    if len(content.encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("output exceeds bounded state size; reduce collection scope")
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


@contextmanager
def collection_lock(data_dir: Path):
    lock = data_dir / ".collect.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("collection already running or stale .collect.lock; verify no collector is active before removing it") from None
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def timestamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("state timestamp requires a timezone")
    return stamp.astimezone(UTC)


def read_state_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
        raise ValueError("state requires manual review; choose a new --data-dir")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError, UnicodeError):
        raise ValueError("state JSON is invalid; choose a new --data-dir") from None
    if not isinstance(value, dict):
        raise ValueError("state must be a JSON object")
    return value


def valid_snapshot(value: object, is_demo: bool) -> bool:
    if (not isinstance(value, dict) or value.get("schema_version") != 1 or
            value.get("module_id") != MODULE_ID or value.get("is_demo") is not is_demo or
            not isinstance(value.get("run_id"), str) or
            not re.fullmatch(r"[0-9a-f]{32}", value["run_id"]) or
            not isinstance(value.get("items"), list) or len(value["items"]) > 2500 or
            not isinstance(value.get("coverage"), dict) or
            value.get("coverage", {}).get("state") not in ("complete", "partial")):
        return False
    for item in value["items"]:
        if (not isinstance(item, dict) or item.get("section") not in SECTIONS or
                not isinstance(item.get("title"), str) or not item["title"] or len(item["title"]) > 1000 or
                not isinstance(item.get("url"), str) or not public_url(item["url"]) or
                item.get("risk") not in ICONS or not isinstance(item.get("risk_terms"), list) or
                any(not isinstance(term, str) for term in item["risk_terms"])):
            return False
    try:
        timestamp(value["generated_at"])
        datetime.strptime(value["report_date"], "%Y-%m-%d")
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    return True


def item_aliases(item: dict) -> list[str]:
    url = public_url(item.get("url", ""))
    parts = urlsplit(url)
    # Tracking parameters and fragments are not event identity. Preserve real
    # query parameters; the Google RSS `oc` rendering parameter is dispensable.
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.casefold().startswith("utm_") and key.casefold() not in ("gclid", "fbclid", "oc")]
    canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), ""))
    values = [("u:", canonical), ("t:", normalized(item.get("title", "")))]
    return [prefix + hashlib.sha256(value.encode()).hexdigest()[:24] for prefix, value in values if value]


def item_fingerprint(item: dict) -> str:
    value = {"title": normalized(item.get("title", "")), "risk": item.get("risk", "neutral"),
             "risk_terms": sorted({str(term).casefold() for term in item.get("risk_terms", [])})}
    # Source attribution, section, publication/observation times and ordering do
    # not establish a content change. This detects text/label changes, not facts.
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def attach_delta(report: dict, previous: dict | None, index: dict | None) -> dict:
    now = timestamp(report["generated_at"])
    unavailable = report["coverage"]["state"] == "unavailable"
    previous_time = timestamp(previous["generated_at"]) if previous and valid_snapshot(previous, report["is_demo"]) else None
    has_baseline = bool(previous_time and now - timedelta(days=SEEN_DAYS) <= previous_time <= now)
    baseline_reason = "available" if has_baseline else ("missing" if previous_time is None else "future" if previous_time > now else "expired")
    delta = {"schema_version": 1, "module_id": MODULE_ID, "is_demo": report["is_demo"],
             "run_id": report["run_id"], "has_baseline": has_baseline,
             "baseline_reason": baseline_reason,
             "baseline_run_id": previous["run_id"] if has_baseline else None,
             "baseline_generated_at": previous["generated_at"] if has_baseline else None,
             "comparison_scope": "recent_seen_14_days" if has_baseline else "first_available_run",
             "new_ids": [], "changed_ids": [], "unchanged_ids": [],
             "counts": {"new": 0, "changed": 0, "unchanged": 0, "baseline": 0},
             "comparison_skipped": unavailable,
             "notice": "Only collected headline text and keyword labels are compared; missing sources do not establish removals or real-world event changes.",
             "seen_window_days": SEEN_DAYS, "seen_item_limit": MAX_SEEN_ITEMS}
    report["delta"] = delta
    if previous_time and not has_baseline:
        delta["unusable_baseline_generated_at"] = previous["generated_at"]
        delta["notice"] += " The previous usable snapshot is outside the comparison window; current items establish a fresh baseline, not new-event claims."
    if unavailable:
        delta.update(comparison_scope="collection_unavailable", notice="Collection unavailable; usable baseline and seen history were not advanced.")
        return index or {}
    entries, reset = {}, False
    if has_baseline and index:
        try:
            if (index.get("schema_version") != 1 or index.get("module_id") != MODULE_ID or
                    index.get("is_demo") is not report["is_demo"] or
                    index.get("run_id") != previous["run_id"] or
                    not isinstance(index.get("entries"), list) or len(index["entries"]) > MAX_SEEN_ITEMS):
                raise ValueError("index mismatch")
            for record in index["entries"]:
                if (not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{20}", record.get("id", "")) or
                        not re.fullmatch(r"[0-9a-f]{64}", record.get("fingerprint", "")) or
                        not isinstance(record.get("aliases"), list) or not 1 <= len(record["aliases"]) <= MAX_ALIASES or
                        any(not isinstance(alias, str) or not re.fullmatch(r"[ut]:[0-9a-f]{24}", alias) for alias in record["aliases"])):
                    raise ValueError("invalid index")
                last_seen = timestamp(record["last_seen"])
                if now - timedelta(days=SEEN_DAYS) <= last_seen <= now:
                    entries[record["id"]] = dict(record, aliases=list(record["aliases"]))
        except (KeyError, ValueError, TypeError, AttributeError):
            entries, reset = {}, True
    if reset:
        delta["notice"] += " Seen index was invalid or out of sync; comparison was rebuilt from the last usable snapshot only."
        delta["comparison_scope"] = "previous_snapshot_after_index_reset"
    aliases = {alias: key for key, record in entries.items() for alias in record["aliases"]}

    def remember(item: dict, observed: str) -> tuple[str, dict | None]:
        keys = item_aliases(item)
        # IDs belong to canonical URLs. A known headline at a different URL may
        # suppress repetition, but must not merge two current URLs into one ID.
        url_key = next((key for key in keys if key.startswith("u:")), None)
        identifier = aliases.get(url_key) if url_key else None
        if identifier is None:
            identifier = hashlib.sha256((url_key or keys[0]).encode()).hexdigest()[:20]
        owned_record = entries.get(identifier)
        old = owned_record or next((entries[aliases[key]] for key in keys if key in aliases), None)
        owned = [key for key in keys if key not in aliases or aliases[key] == identifier]
        all_aliases = list(dict.fromkeys((owned_record or {}).get("aliases", []) + owned))[-MAX_ALIASES:]
        record = {"id": identifier, "fingerprint": item_fingerprint(item), "last_seen": observed, "aliases": all_aliases}
        entries[identifier] = record
        for key in all_aliases:
            aliases[key] = identifier
        return identifier, old

    # The checkpoint is authoritative. Seeding the previous snapshot also makes
    # a pre-checkpoint installation restartable without claiming a full history.
    if has_baseline:
        for item in previous["items"]:
            remember(item, previous["generated_at"])
    baseline_entries = {key: dict(record, aliases=list(record["aliases"])) for key, record in entries.items()}
    baseline_aliases = dict(aliases)
    for item in report["items"]:
        keys = item_aliases(item)
        prior_url = next((baseline_entries[baseline_aliases[key]] for key in keys
                          if key.startswith("u:") and key in baseline_aliases), None)
        known_title = any(key.startswith("t:") and key in baseline_aliases for key in keys)
        identifier, _ = remember(item, report["generated_at"])
        item["id"] = identifier
        # Compare against the frozen previous index, never earlier rows in this
        # run. An old headline at a new URL is repetition, not a title change at
        # the original URL, even if that original URL was retitled meanwhile.
        if not has_baseline:
            change = "baseline"
        elif prior_url is not None:
            change = "unchanged" if prior_url["fingerprint"] == item_fingerprint(item) else "changed"
        elif known_title:
            change = "unchanged"
        else:
            change = "new"
        item["change"] = change
        delta["counts"][change] += 1
        if change != "baseline":
            delta[change + "_ids"].append(identifier)
    retained = sorted((record for record in entries.values()
                       if now - timedelta(days=SEEN_DAYS) <= timestamp(record["last_seen"]) <= now),
                      key=lambda record: (record["last_seen"], record["id"]), reverse=True)
    delta["seen_history_truncated"] = len(retained) > MAX_SEEN_ITEMS
    return {"schema_version": 1, "module_id": MODULE_ID, "is_demo": report["is_demo"],
            "run_id": report["run_id"], "generated_at": report["generated_at"], "entries": retained[:MAX_SEEN_ITEMS]}


def incremental_markdown(report: dict) -> str:
    delta = report["delta"]
    lines = [f"# AI 产品增量简报 {report['report_date']}", "", f"> 本轮 {report['generated_at']} · run {report['run_id']}", ""]
    if delta["comparison_skipped"]:
        return "\n".join(lines + ["采集不可用，未推进最近可用快照或增量基线。旧资料不能作为本轮新消息。", ""])
    if not delta["has_baseline"]:
        lines.append("当前比较窗口没有可用的成功基线；下列内容作为初始资料，不宣称是新增事件。")
        selected = report["items"]
    else:
        lines.extend([f"比较基线：{delta['baseline_generated_at']}；本轮新增 {delta['counts']['new']}，标题/标签变化 {delta['counts']['changed']}，重复 {delta['counts']['unchanged']}。", "", "来源缺失不代表事件消失；标题或标签变化也不证明现实事件有新进展。"])
        selected = [item for item in report["items"] if item["change"] in ("new", "changed")]
    lines.append("")
    for item in sorted(selected, key=lambda row: (0 if row["risk"] == "high" else 1 if row["risk"] == "medium" else 2)):
        title = item["title"].replace("[", "\\[").replace("]", "\\]")
        url = item["url"].replace("(", "%28").replace(")", "%29").replace(" ", "%20")
        lines.append(f"- {ICONS[item['risk']]} [{title}]({url}) — {item['source']} · {item['change']}")
    if not selected:
        lines.append("- 本轮没有可展开的新增或标题/标签变化；请同时检查来源覆盖。")
    return "\n".join(lines) + "\n"


def write_usable_mirrors(report: dict, previous: dict | None, seen: dict, data_dir: Path) -> None:
    if previous:
        atomic_write(data_dir / "previous.json", json.dumps(previous, ensure_ascii=False, indent=2) + "\n")
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    atomic_write(data_dir / "latest.json", text)
    atomic_write(data_dir / (report["report_date"] + ".json"), text)
    digest = markdown(report)
    atomic_write(data_dir / "最新日报.md", digest)
    atomic_write(data_dir / (report["report_date"] + ".md"), digest)
    atomic_write(data_dir / "seen-index.json", json.dumps(seen, ensure_ascii=False, indent=2) + "\n")


def load_checkpoint(data_dir: Path, is_demo: bool) -> tuple[dict | None, dict | None, dict | None]:
    path = data_dir / ".collection-state.json"
    if path.exists():
        state = read_state_json(path)
        if (state.get("module_id") != MODULE_ID or state.get("is_demo") is not is_demo or
                not valid_snapshot(state.get("latest"), is_demo) or
                (state.get("previous") is not None and not valid_snapshot(state.get("previous"), is_demo)) or
                not isinstance(state.get("seen_index"), dict) or
                state["seen_index"].get("module_id") != MODULE_ID or
                state["seen_index"].get("is_demo") is not is_demo or
                state["seen_index"].get("run_id") != state["latest"]["run_id"]):
            raise ValueError("collection checkpoint is invalid; choose a new --data-dir")
        return state["latest"], state.get("previous"), state.get("seen_index")
    latest = read_state_json(data_dir / "latest.json") if (data_dir / "latest.json").exists() else None
    if latest is not None and not valid_snapshot(latest, is_demo):
        raise ValueError("latest snapshot is invalid; choose a new --data-dir")
    if latest is None and any((data_dir / name).exists() for name in ("previous.json", "seen-index.json")):
        raise ValueError("usable baseline is incomplete; choose a new --data-dir")
    seen = read_state_json(data_dir / "seen-index.json") if (data_dir / "seen-index.json").exists() else None
    if latest is not None and seen is None:
        # A legacy same-module snapshot can seed a bounded index without
        # modifying its retained delta or inventing older observation history.
        seed = json.loads(json.dumps(latest))
        seen = attach_delta(seed, None, None)
    return latest, None, seen


def persist(report: dict, data_dir: Path) -> None:
    ensure_data_mode(data_dir, report["is_demo"], claim=True)
    old, older, seen = load_checkpoint(data_dir, report["is_demo"])
    unavailable = report["coverage"]["state"] == "unavailable"
    report["reused_latest"] = bool(unavailable and old)
    if report["reused_latest"]:
        report["previous_generated_at"] = old.get("generated_at")
    report["published_latest"] = not unavailable
    updated_seen = attach_delta(report, old, seen)
    if unavailable:
        # Recover usable flat mirrors from the last atomic checkpoint, without
        # advancing either baseline. The failed attempt remains separate.
        if old:
            write_usable_mirrors(old, older, seen or {}, data_dir)
        elif not (data_dir / (report["report_date"] + ".json")).exists():
            atomic_write(data_dir / (report["report_date"] + ".json"), json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            atomic_write(data_dir / (report["report_date"] + ".md"), markdown(report))
    else:
        checkpoint = {"schema_version": 1, "module_id": MODULE_ID, "is_demo": report["is_demo"],
                      "latest": report, "previous": old, "seen_index": updated_seen}
        # One atomic checkpoint commits the successful report and seen index;
        # flat JSON/Markdown files are recoverable views for readers and tools.
        atomic_write(data_dir / ".collection-state.json", json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n")
        write_usable_mirrors(report, old, updated_seen, data_dir)
    atomic_write(data_dir / "delta.json", json.dumps(report["delta"], ensure_ascii=False, indent=2) + "\n")
    atomic_write(data_dir / "增量简报.md", incremental_markdown(report))
    atomic_write(data_dir / "last-run.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def ensure_data_mode(data_dir: Path, is_demo: bool, claim: bool = False) -> None:
    """Refuse both directions of demo/live mixing before any report is replaced."""
    mode = "demo" if is_demo else "live"
    marker = data_dir / ".collection-mode.json"
    if marker.exists():
        stored = read_state_json(marker)
        if not isinstance(stored, dict) or stored.get("module_id") != MODULE_ID or stored.get("mode") not in ("demo", "live"):
            raise ValueError("data directory mode is invalid; choose a new --data-dir")
        if stored["mode"] != mode:
            raise ValueError("demo and live collection require separate --data-dir directories")
    # Validate pre-marker data too. A failed first run has last-run but no latest.
    reports = [p for p in data_dir.iterdir() if p.name in ("latest.json", "last-run.json", "previous.json", "delta.json", "seen-index.json", ".collection-state.json") or
               re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name)]
    if not marker.exists():
        for path in data_dir.iterdir():
            if path.name == "最新日报.md":
                counterpart = data_dir / "latest.json"
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", path.name):
                counterpart = path.with_suffix(".json")
            else:
                continue
            if not counterpart.exists():
                raise ValueError("legacy report mode is unknown; choose a new --data-dir")
    for path in reports:
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("existing report requires manual review; choose a new --data-dir")
        value = read_state_json(path)
        if (not isinstance(value, dict) or value.get("schema_version") != 1 or
                not isinstance(value.get("is_demo"), bool) or value.get("module_id") != MODULE_ID):
            raise ValueError("existing report mode is unknown; choose a new --data-dir")
        if value["is_demo"] != is_demo:
            raise ValueError("demo and live collection require separate --data-dir directories")
    if claim and not marker.exists():
        atomic_write(marker, json.dumps({"schema_version": 1, "module_id": MODULE_ID, "mode": mode}) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Private JSON configuration; no environment configuration is read")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Output directory")
    parser.add_argument("--demo", action="store_true", help="Generate an explicitly fictional offline example")
    parser.add_argument("--proxy", help="Explicit HTTP(S) proxy for international sources; empty means direct")
    parser.add_argument("--timeout", type=float, help="Timeout seconds per request")
    parser.add_argument("--workers", type=int, help="Concurrent source limit (1–8)")
    parser.add_argument("--days", type=int, help="Exact freshness window in days (1–30)")
    parser.add_argument("--retries", type=int, help="Retries after a transient failure (0–2)")
    parser.add_argument("--source", action="append", help="Collect only this source ID; repeat to select several")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        for option, key in [("proxy", "proxy"), ("timeout", "timeout_seconds"), ("workers", "workers"), ("days", "window_days"), ("retries", "retries"), ("source", "enabled_sources")]:
            if getattr(args, option) is not None:
                config[key] = getattr(args, option)
        # Validate CLI overrides through the same path as file configuration, without writing a configuration file.
        for key, minimum, maximum in [("window_days", 1, 30), ("workers", 1, 8), ("timeout_seconds", 1, 60), ("retries", 0, 2)]:
            if not minimum <= config[key] <= maximum:
                raise ValueError("invalid numeric option: " + key)
        if config["proxy"]:
            parsed = urlsplit(config["proxy"])
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
                raise ValueError("proxy must be an HTTP(S) origin without credentials")
        chosen = sources(config)
        data_dir = args.data_dir.expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with collection_lock(data_dir):
            ensure_data_mode(data_dir, args.demo)
            now = datetime.now(UTC)
            if args.demo:
                report = demo_report(config, now)
            else:
                with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
                    results = list(pool.map(lambda source: fetch_source(source, config, now), chosen))
                report = make_report(config, now, results)
            persist(report, data_dir)
        print(json.dumps({"state": report["coverage"]["state"], "items": len(report["items"]), "sources": len(report["sources"]),
                          "is_demo": report["is_demo"], "reused_latest": report["reused_latest"], "run_id": report["run_id"], "delta_counts": report["delta"]["counts"]}, ensure_ascii=False))
        return 2 if report["coverage"]["state"] == "unavailable" else 0
    except (OSError, ValueError, ZoneInfoNotFoundError) as error:
        # Avoid printing input paths, proxy credentials, remote response bodies or raw network errors.
        if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError):
            print("Configuration or output error: " + str(error), file=__import__("sys").stderr)
        else:
            print("Configuration or output could not be read or written.", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
