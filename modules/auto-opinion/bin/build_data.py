#!/usr/bin/env python3
"""Build a self-contained, offline dashboard from this module's JSON reports."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

MODULE = Path(__file__).resolve().parents[1]
SHANGHAI = dt.timezone(dt.timedelta(hours=8))
MAX_BYTES = 5 * 1024 * 1024
SECTIONS = {"li_auto", "domestic", "international", "hot"}
RISKS = {"high", "medium", "positive", "neutral"}


def safe_text(value, limit=500):
    return value[:limit] if isinstance(value, str) else ""


def safe_url(value):
    value = safe_text(value, 4096).strip()
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return ""
        if any(ord(c) < 32 for c in value):
            return ""
        return value
    except ValueError:
        return ""


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def clean_report(raw):
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not iso_date(raw.get("report_date")):
        raise ValueError("unsupported-report")
    items, seen = [], set()
    raw_items = raw.get("items", [])
    if not isinstance(raw_items, list):
        raise ValueError("invalid-items")
    for item in raw_items[:2000]:
        if not isinstance(item, dict) or item.get("section") not in SECTIONS:
            continue
        title = safe_text(item.get("title"), 600).strip()
        if not title:
            continue
        url = safe_url(item.get("url"))
        section = item["section"]
        # Only exact headlines/URLs within the same section collapse. Equal
        # numbers or word tokens do not establish that two events are the same.
        key = (section, url or re.sub(r"\s+", " ", title).casefold())
        if key in seen:
            continue
        seen.add(key)
        terms = item.get("risk_terms", [])
        items.append({
            "id": safe_text(item.get("id"), 120) or hashlib.sha256(repr(key).encode()).hexdigest()[:16],
            "section": section, "title": title, "url": url,
            "source": safe_text(item.get("source"), 160),
            "published_at": safe_text(item.get("published_at"), 80) or None,
            "observed_at": safe_text(item.get("observed_at"), 80) or None,
            "time_basis": safe_text(item.get("time_basis"), 24),
            "risk": item.get("risk") if item.get("risk") in RISKS else "neutral",
            "risk_terms": [safe_text(x, 60) for x in terms[:12] if isinstance(x, str)] if isinstance(terms, list) else [],
        })
    sources = []
    raw_sources = raw.get("sources", [])
    if isinstance(raw_sources, list):
        for source in raw_sources[:50]:
            if not isinstance(source, dict):
                continue
            def count(name):
                value = source.get(name, 0)
                return max(0, min(value, 100000)) if isinstance(value, int) and not isinstance(value, bool) else 0
            sources.append({
                "id": safe_text(source.get("id"), 100), "name": safe_text(source.get("name"), 180),
                "state": source.get("state") if source.get("state") in {"ok", "empty", "error"} else "error",
                "fetched_count": count("fetched_count"), "accepted_count": count("accepted_count"),
                "http_status": source.get("http_status") if isinstance(source.get("http_status"), int) else None,
                "route": source.get("route") if source.get("route") in {"direct", "proxy"} else "",
                "error_code": safe_text(source.get("error_code"), 80),
                "empty_reason": safe_text(source.get("empty_reason"), 100),
                "checked_at": safe_text(source.get("checked_at"), 80),
            })
    coverage = raw.get("coverage", {})
    coverage = coverage if isinstance(coverage, dict) else {}
    state = coverage.get("state")
    if state not in {"complete", "partial", "unavailable"}:
        state = "unavailable"
    if not sources or all(source["state"] == "error" for source in sources):
        state = "unavailable"
    elif any(source["state"] == "error" for source in sources) and state == "complete":
        state = "partial"
    return {
        "schema_version": 1, "report_date": raw["report_date"],
        "generated_at": safe_text(raw.get("generated_at"), 80),
        "window_days": raw.get("window_days") if isinstance(raw.get("window_days"), int) else 3,
        "is_demo": raw.get("is_demo") is True,
        "coverage": {"state": state}, "items": items, "sources": sources,
        "reused_latest": raw.get("reused_latest") is True,
        "previous_generated_at": safe_text(raw.get("previous_generated_at"), 80),
    }


def read_report(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("unreadable-or-oversized-report")
    return clean_report(json.loads(path.read_text(encoding="utf-8")))


def load_data(data_dir, today=None):
    today = today or dt.datetime.now(SHANGHAI).date()
    cutoff = today - dt.timedelta(days=13)
    days, diagnostics = {}, []
    # Do not interpret unrelated files, Markdown, logs or other projects.
    for path in sorted(data_dir.glob("????-??-??.json")):
        date = iso_date(path.stem)
        if not date or not cutoff <= date <= today:
            continue
        try:
            report = read_report(path)
            if report["report_date"] != path.stem:
                raise ValueError("date-mismatch")
            # A failed attempt is not a new day of news. Its health belongs to
            # last-run; retaining yesterday's usable report must select that
            # actual date rather than an empty, failed snapshot from today.
            if report["coverage"]["state"] == "unavailable" and not report["items"]:
                continue
            days[path.stem] = report
        except (OSError, ValueError, UnicodeError):
            diagnostics.append({"report_date": path.stem, "code": "report-unreadable"})
    for name in ("latest.json",):
        path = data_dir / name
        if not path.exists():
            continue
        try:
            report = read_report(path)
            if report["coverage"]["state"] == "unavailable" and not report["items"]:
                continue
            date = iso_date(report["report_date"])
            if cutoff <= date <= today:
                current = days.get(report["report_date"])
                if current is None or report["generated_at"] > current["generated_at"]:
                    days[report["report_date"]] = report
        except (OSError, ValueError, UnicodeError):
            diagnostics.append({"code": "latest-unreadable"})
    last_run = None
    path = data_dir / "last-run.json"
    if path.exists():
        try:
            last_run = read_report(path)
        except (OSError, ValueError, UnicodeError):
            diagnostics.append({"code": "last-run-unreadable"})
    reports = list(days.values()) + ([last_run] if last_run else [])
    return {"schema_version": 1, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "calendar_date": today.isoformat(), "retention_days": 14,
            "days": [days[key] for key in sorted(days, reverse=True)],
            "last_run": last_run, "diagnostics": diagnostics,
            "is_demo": bool(reports) and all(report["is_demo"] for report in reports)}


def demo_data(today=None):
    """Synthetic examples are created in memory only when --demo is explicit."""
    today = today or dt.datetime.now(SHANGHAI).date()
    days = []
    headlines = [
        ("li_auto", "high", "虚构示例：某款车型召回公告，待核对官方范围", "召回"),
        ("li_auto", "neutral", "虚构示例：理想汽车公布产品说明会安排", ""),
        ("domestic", "medium", "虚构示例：一家车企调整价格，影响仍待观察", "价格"),
        ("domestic", "positive", "虚构示例：某品牌发布月度交付数据", "交付"),
        ("international", "neutral", "Fictional example: an EV maker announces a product briefing", ""),
        ("hot", "neutral", "虚构示例：汽车充电话题进入热搜", ""),
    ]
    for offset in range(3):
        date = today - dt.timedelta(days=offset)
        stamp = date.isoformat() + "T01:00:00+00:00"
        report = {"schema_version": 1, "generated_at": stamp, "report_date": date.isoformat(),
                  "window_days": 3, "is_demo": True, "coverage": {"state": "partial"},
                  "items": [{"id": f"demo-{offset}-{i}", "section": section,
                             "title": title, "url": f"https://example.com/auto-demo/{offset}/{i}",
                             "source": "虚构演示来源", "published_at": stamp if section != "hot" else None,
                             "observed_at": stamp, "time_basis": "observed" if section == "hot" else "published",
                             "risk": risk, "risk_terms": [term] if term else []}
                            for i, (section, risk, title, term) in enumerate(headlines)],
                  "sources": [{"id": "demo-rss", "name": "演示 RSS A", "state": "ok", "fetched_count": 12, "accepted_count": 5},
                              {"id": "demo-empty", "name": "演示 RSS B", "state": "empty", "fetched_count": 4, "accepted_count": 0, "empty_reason": "filtered"},
                              {"id": "demo-error", "name": "演示 RSS C", "state": "error", "fetched_count": 0, "accepted_count": 0, "error_code": "timeout"}]}
        days.append(clean_report(report))
    return {"schema_version": 1, "generated_at": days[0]["generated_at"], "calendar_date": today.isoformat(),
            "retention_days": 14, "days": days, "last_run": days[0], "diagnostics": [], "is_demo": True}


def script_json(data):
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def build(data, output_dir):
    template = (MODULE / "site.template.html").read_text(encoding="utf-8")
    assets = {"__DATA_JSON__": script_json(data),
              "__WORKHUB_DESIGN_CSS__": (MODULE / "site/design-system.css").read_text(encoding="utf-8"),
              "__WORKHUB_THEME_JS__": (MODULE / "site/embedded-theme.js").read_text(encoding="utf-8")}
    for marker in assets:
        if template.count(marker) != 1:
            raise ValueError("template-placeholder-mismatch")
    template = re.sub("|".join(re.escape(marker) for marker in assets),
                      lambda match: assets[match.group(0)], template)
    output_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".dashboard-", suffix=".tmp", dir=output_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(template)
        os.replace(name, output_dir / "index.html")
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return output_dir / "index.html"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=MODULE / "data")
    parser.add_argument("--output-dir", type=Path, default=MODULE / "site")
    parser.add_argument("--demo", action="store_true", help="Use clearly fictional offline examples, without reading reports")
    args = parser.parse_args(argv)
    try:
        data = demo_data() if args.demo else load_data(args.data_dir.expanduser())
        build(data, args.output_dir.expanduser())
    except (OSError, ValueError, UnicodeError) as error:
        print(json.dumps({"ok": False, "error": type(error).__name__, "message": "Cannot build the dashboard; check input reports and template resources."}))
        return 1
    print(json.dumps({"ok": True, "days": len(data["days"]), "is_demo": data["is_demo"],
                      "diagnostics": len(data["diagnostics"]), "entry": "index.html"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
