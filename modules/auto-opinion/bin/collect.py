#!/usr/bin/env python3
"""Collect public automotive headlines; no credentials or external dependencies."""

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
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = "WorkhubAutoOpinion/1.0 (public headline RSS reader)"
SECTIONS = {"li_auto": "理想汽车专项", "domestic": "国内车企与行业",
            "international": "国际车圈", "hot": "汽车相关热搜"}
GOOGLE_QUERIES = [
    ("li_auto", "理想汽车"),
    ("li_auto", "理想 i6 OR 理想 i8 OR 理想 MEGA"),
    ("li_auto", '"Li Auto"'),
    ("domestic", "比亚迪 OR 蔚来 OR 小鹏汽车"),
    ("domestic", "问界 OR 鸿蒙智行 OR 小米汽车"),
    ("domestic", "零跑汽车 OR 极氪 OR 哪吒汽车 OR 深蓝汽车"),
    ("domestic", "新能源汽车 销量 交付"),
    ("international", "Tesla"),
    ("international", "electric vehicle"),
    ("international", "BYD"),
]
RISK_TERMS = {
    "high": ["召回", "自燃", "起火", "爆炸", "致死", "碰撞", "失控", "维权", "诉讼", "造假", "罚款", "禁售",
             "recall", "recalls", "recalled", "fire", "fires", "crash", "crashes", "lawsuit", "lawsuits", "probe", "death", "fatality"],
    "medium": ["降价", "价格战", "裁员", "亏损", "停工", "推迟", "延期", "投诉", "质疑", "下滑", "下跌", "减持", "做空",
               "delay", "delays", "delayed", "layoff", "layoffs", "loss", "losses", "slump", "plunge", "cut", "cuts"],
    "positive": ["创新高", "冠军", "突破", "增长", "爆单", "里程碑", "大奖", "破万", "纪录", "上市", "交付", "发布",
                 "record", "surge", "surges", "soar", "boost", "unveil", "unveils", "launch", "launches"],
}
NOISE = ["tokenized", "币价", "实时价格", "e-bike", "e-bikes", "power station", "solar panel",
         "snow blower", "cranberry", "kids electric"]
CAR_WORDS = ["汽车", "理想", "比亚迪", "蔚来", "小鹏", "问界", "智行", "小米", "特斯拉", "丰田", "大众", "奔驰", "宝马",
             "奥迪", "极氪", "零跑", "哪吒", "深蓝", "阿维塔", "电动", "充电", "电池", "提车", "新能源", "自动驾驶",
             "l6", "l7", "l8", "l9", "mega", "i6", "i8", "su7", "yu7", "增程"]
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
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
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
    config = {"window_days": 3, "timezone": "Asia/Shanghai", "workers": 4, "timeout_seconds": 15,
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
                                   ("retries", 0, 2), ("max_items_per_source", 1, 100)]:
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
        {"id": "electrek", "name": "Electrek", "section": "international", "url": "https://electrek.co/feed/", "kind": "rss", "international": True},
        {"id": "carscoops", "name": "Carscoops", "section": "international", "url": "https://www.carscoops.com/feed/", "kind": "rss", "international": True},
        {"id": "baidu", "name": "百度汽车相关热搜", "section": "hot", "url": "https://top.baidu.com/api/board?platform=wise&tab=realtime", "kind": "baidu", "international": False},
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
            reject("non_vehicle_noise")
            continue
        if source["kind"] == "baidu":
            if not any(term_matches(title, word) for word in CAR_WORDS):
                reject("not_automotive")
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
    seen, items, statuses = set(), [], []
    for rows, status in results:
        count = 0
        for row in rows:
            key = normalized(row["title"])
            if not key or key in seen:
                status["rejected"]["duplicate_title"] = status["rejected"].get("duplicate_title", 0) + 1
                continue
            seen.add(key)
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
    return {"schema_version": 1, "generated_at": iso(now),
            "report_date": now.astimezone(ZoneInfo(config["timezone"])).date().isoformat(),
            "window_days": config["window_days"], "is_demo": demo,
            "coverage": {"state": state, "total_sources": len(statuses), "ok_sources": len(statuses) - errors - empty,
                         "empty_sources": empty, "error_sources": errors, "accepted_items": len(items),
                         "notice": "标题关键词仅作线索；未命中不表示没有负面事件。热搜按观察时间记录，不能据此推断发布时间。"},
            "items": items, "sources": statuses}


def demo_report(config: dict, now: datetime) -> dict:
    examples = [
        ("li_auto", "示例汽车产品发布与交付说明（虚构演示）", "positive"),
        ("domestic", "示例车企召回流程说明（虚构演示，非真实事件）", "high"),
        ("international", "Sample EV charging update — fictional demonstration", "neutral"),
        ("hot", "示例汽车热搜话题（虚构演示）", "neutral"),
    ]
    rows = []
    for n, (section, title, risk) in enumerate(examples, 1):
        rows.append({"id": f"demo-{n}", "section": section, "title": title,
                     "url": f"https://example.com/fictional-auto-story-{n}", "source": "虚构演示 / Fictional demo",
                     "published_at": None if section == "hot" else iso(now - timedelta(hours=n)),
                     "observed_at": iso(now), "time_basis": "observed" if section == "hot" else "published",
                     "risk": risk, "risk_terms": ["召回"] if risk == "high" else [], "is_demo": True})
    status = {"id": "fictional-demo", "name": "离线虚构演示", "section": "domestic", "state": "ok",
              "fetched_count": len(rows), "accepted_count": len(rows), "http_status": None, "route": "offline",
              "error_code": None, "checked_at": iso(now), "attempts": [], "rejected": {}}
    return make_report(config, now, [(rows, status)], demo=True)


def markdown(report: dict) -> str:
    coverage, items = report["coverage"], report["items"]
    label = " · 虚构演示 / FICTIONAL DEMO" if report["is_demo"] else ""
    lines = [f"# 车圈舆情日报 {report['report_date']}{label}", "", f"> 采集时间 {report['generated_at']} · RSS 精确过去 {report['window_days']} 天", "",
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


def persist(report: dict, data_dir: Path) -> None:
    ensure_data_mode(data_dir, report["is_demo"], claim=True)
    latest = data_dir / "latest.json"
    unavailable = report["coverage"]["state"] == "unavailable"
    old = None
    if latest.exists():
        try:
            old = json.loads(latest.read_text(encoding="utf-8"))
            if not isinstance(old, dict) or old.get("schema_version") != 1:
                old = None
        except (OSError, ValueError):
            pass
    report["reused_latest"] = bool(unavailable and old)
    if report["reused_latest"]:
        report["previous_generated_at"] = old.get("generated_at")
    report["published_latest"] = not unavailable
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    digest = markdown(report)
    dated = data_dir / (report["report_date"] + ".json")
    if not unavailable or not dated.exists():
        atomic_write(dated, text)
        atomic_write(data_dir / (report["report_date"] + ".md"), digest)
    if not unavailable:
        atomic_write(latest, text)
        atomic_write(data_dir / "最新日报.md", digest)
    atomic_write(data_dir / "last-run.json", text)


def ensure_data_mode(data_dir: Path, is_demo: bool, claim: bool = False) -> None:
    """Refuse both directions of demo/live mixing before any report is replaced."""
    mode = "demo" if is_demo else "live"
    marker = data_dir / ".collection-mode.json"
    if marker.exists():
        stored = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(stored, dict) or stored.get("mode") not in ("demo", "live"):
            raise ValueError("data directory mode is invalid; choose a new --data-dir")
        if stored["mode"] != mode:
            raise ValueError("demo and live collection require separate --data-dir directories")
    # Validate pre-marker data too. A failed first run has last-run but no latest.
    reports = [p for p in data_dir.iterdir() if p.name in ("latest.json", "last-run.json") or
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
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schema_version") != 1 or
                not isinstance(value.get("is_demo"), bool)):
            raise ValueError("existing report mode is unknown; choose a new --data-dir")
        if value["is_demo"] != is_demo:
            raise ValueError("demo and live collection require separate --data-dir directories")
    if claim and not marker.exists():
        atomic_write(marker, json.dumps({"schema_version": 1, "mode": mode}) + "\n")


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
                          "is_demo": report["is_demo"], "reused_latest": report["reused_latest"]}, ensure_ascii=False))
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
