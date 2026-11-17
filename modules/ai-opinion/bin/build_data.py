#!/usr/bin/env python3
"""Build a self-contained, offline dashboard from this module's JSON reports."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

MODULE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_ai_story_groups", MODULE / "bin/story_groups.py")
_story = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_story)
SHANGHAI = dt.timezone(dt.timedelta(hours=8))
MAX_BYTES = 5 * 1024 * 1024
SECTIONS = {"domestic", "international", "hardware", "voices", "hot"}
RISKS = {"high", "medium", "positive", "neutral"}


def safe_text(value, limit=500):
    return value[:limit] if isinstance(value, str) else ""


def safe_url(value):
    value = safe_text(value, 4096).strip()
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return ""
        if any(ord(c) < 32 for c in value) or any(c in value for c in '<>"\\'):
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


def safe_identifier(value):
    return value if (isinstance(value, str) and 0 < len(value) <= 160 and
                     re.fullmatch(r"[A-Za-z0-9_.:-]+", value)) else ""


def clean_delta(raw, run_id, items):
    """Only accept a delta bound to this exact module and snapshot."""
    fallback = {"valid": False, "reason": "delta-unavailable", "has_baseline": False,
                "comparison_skipped": True, "new_ids": [], "changed_ids": [],
                "unchanged_ids": [], "counts": {"new": 0, "changed": 0, "unchanged": 0}}
    if (not isinstance(raw, dict) or raw.get("schema_version") != 1 or
            raw.get("module_id") != "ai-opinion" or not run_id or raw.get("run_id") != run_id):
        return fallback
    if not isinstance(raw.get("has_baseline"), bool) or not isinstance(raw.get("comparison_skipped"), bool):
        return fallback
    scope = raw.get("comparison_scope")
    if scope not in {"recent_seen_14_days", "previous_snapshot_after_index_reset",
                     "first_available_run", "collection_unavailable"}:
        return fallback
    groups = {}
    for key in ("new_ids", "changed_ids", "unchanged_ids"):
        values = raw.get(key)
        if (not isinstance(values, list) or len(values) > 2000 or
                any(not safe_identifier(value) for value in values) or len(values) != len(set(values))):
            return fallback
        groups[key] = values
    assigned = groups["new_ids"] + groups["changed_ids"] + groups["unchanged_ids"]
    if len(assigned) != len(set(assigned)):
        return fallback
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        return fallback
    has_baseline = raw["has_baseline"]
    skipped = raw["comparison_skipped"]
    baseline_reason = raw.get("baseline_reason")
    if baseline_reason not in {"missing", "expired", "future", "available"}:
        baseline_reason = "unknown"
    if ((scope == "first_available_run" and (has_baseline or skipped)) or
            (scope in {"recent_seen_14_days", "previous_snapshot_after_index_reset"} and
             (not has_baseline or skipped)) or
            (scope == "collection_unavailable" and not skipped)):
        return fallback
    if has_baseline and not skipped:
        if (set(assigned) != set(ids) or not safe_identifier(raw.get("baseline_run_id")) or
                raw["baseline_run_id"] == run_id or baseline_reason in {"missing", "expired", "future"}):
            return fallback
    elif assigned:
        return fallback
    return {"valid": True, "run_id": run_id, "has_baseline": has_baseline,
            "baseline_reason": baseline_reason,
            "baseline_run_id": safe_identifier(raw.get("baseline_run_id")),
            "baseline_generated_at": safe_text(raw.get("baseline_generated_at"), 80),
            "unusable_baseline_generated_at": safe_text(raw.get("unusable_baseline_generated_at"), 80)
                if baseline_reason in {"expired", "future"} else "",
            "comparison_scope": scope, "comparison_skipped": skipped,
            **groups, "counts": {"new": len(groups["new_ids"]), "changed": len(groups["changed_ids"]),
                                  "unchanged": len(groups["unchanged_ids"]),
                                  "baseline": len(items) if not has_baseline else 0}}


def clean_report(raw):
    if (not isinstance(raw, dict) or raw.get("schema_version") != 1 or
            raw.get("module_id") != "ai-opinion" or not iso_date(raw.get("report_date"))):
        raise ValueError("unsupported-report")
    items = []
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
        # Preserve raw identities for exact delta validation; group display
        # cards separately without discarding source provenance.
        key = (section, url or re.sub(r"\s+", " ", title).casefold())
        terms = item.get("risk_terms", [])
        cleaned = {
            "id": safe_text(item.get("id"), 120) or hashlib.sha256(repr(key).encode()).hexdigest()[:16],
            "section": section, "title": title, "url": url,
            "source": safe_text(item.get("source"), 160),
            "published_at": safe_text(item.get("published_at"), 80) or None,
            "observed_at": safe_text(item.get("observed_at"), 80) or None,
            "time_basis": safe_text(item.get("time_basis"), 24),
            "risk": item.get("risk") if item.get("risk") in RISKS else "neutral",
            "risk_terms": [safe_text(x, 60) for x in terms[:12] if isinstance(x, str)] if isinstance(terms, list) else [],
        }
        mentions = item.get("mentions", [])
        if isinstance(mentions, list):
            cleaned["mentions"] = [mention for value in mentions[:100]
                                   if (mention := _story.clean_mention(value))]
        items.append(cleaned)
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
    result = {
        "schema_version": 1, "module_id": "ai-opinion", "report_date": raw["report_date"],
        "run_id": safe_identifier(raw.get("run_id")),
        "generated_at": safe_text(raw.get("generated_at"), 80),
        "window_days": raw.get("window_days") if isinstance(raw.get("window_days"), int) else 2,
        "is_demo": raw.get("is_demo") is True,
        "coverage": {"state": state}, "items": items, "sources": sources,
        "reused_latest": raw.get("reused_latest") is True,
        "previous_generated_at": safe_text(raw.get("previous_generated_at"), 80),
    }
    result["delta"] = clean_delta(raw.get("delta"), result["run_id"], items)
    result["_saved_groups"] = clean_saved_groups(raw.get("groups"), result)
    return result


def clean_saved_groups(raw, report):
    """Read bounded metadata from this snapshot, never a future index."""
    if not isinstance(raw, list):
        return {}
    date = iso_date(report["report_date"])
    cutoff = date - dt.timedelta(days=13)
    result = {}
    for group in raw[:2000]:
        if not isinstance(group, dict) or not isinstance(group.get("member_ids"), list):
            continue
        members = group["member_ids"]
        if not members or len(members) > 2000 or any(not safe_identifier(x) for x in members):
            continue
        value = group.get("history")
        if not isinstance(value, dict) or not isinstance(value.get("observed_dates"), list):
            continue
        if len(value["observed_dates"]) > 14:
            continue
        dates = sorted(set(value["observed_dates"])) if all(isinstance(x, str) for x in value["observed_dates"]) else []
        if (not dates or any(not iso_date(x) or not cutoff <= iso_date(x) <= date for x in dates)
                or dates[-1] != report["report_date"]):
            continue
        first = value.get("first_recorded_date")
        if not iso_date(first) or first > dates[0]:
            continue
        events = []
        for event in value.get("change_events", [])[:32] if isinstance(value.get("change_events"), list) else []:
            if not isinstance(event, dict) or event.get("date") not in dates:
                continue
            events.append({"date": event["date"], "generated_at": safe_text(event.get("generated_at"),80),
                           "run_id": safe_identifier(event.get("run_id")), "title": safe_text(event.get("title"),600),
                           "kind": "title_or_keyword_change"})
        streak, cursor = 0, date
        while cursor.isoformat() in dates:
            streak += 1
            cursor -= dt.timedelta(days=1)
        history = {"observed_dates": dates, "first_recorded_date": first,
                   "last_recorded_date": dates[-1], "observed_days": len(dates),
                   "consecutive_days": streak, "change_events": events,
                   "change_dates": sorted({x["date"] for x in events}), "window_days": 14,
                   "scope": "recorded_dates", "history_complete": False}
        change = group.get("change")
        if change not in {"new", "changed", "unchanged", "baseline"}:
            change = "baseline"
        result[tuple(sorted(set(members)))] = {"id": safe_identifier(group.get("id")), "history": history, "change": change}
    return result


def enrich_reports(reports):
    """Replay actual saved dates in order; historical views have no future."""
    histories = {}
    for report in sorted(reports, key=lambda x: (x["generated_at"], x["run_id"])):
        mode = report["is_demo"]
        groups, histories[mode] = _story.annotate_report(report, histories.get(mode))
        saved = report.pop("_saved_groups", {})
        for group in groups:
            original = saved.get(tuple(sorted(set(group["member_ids"]))))
            if original:
                group["history"] = original["history"]
                if original["id"]:
                    group["id"] = original["id"]
                if report["delta"]["valid"]:
                    group["change"] = original["change"]
        report["groups"] = groups
        report["coverage"]["grouped_items"] = len(groups)
    return reports


def read_report(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("unreadable-or-oversized-report")
    return clean_report(json.loads(path.read_text(encoding="utf-8")))


def load_data(data_dir, today=None):
    today = today or dt.datetime.now(SHANGHAI).date()
    cutoff = today - dt.timedelta(days=13)
    days, diagnostics, snapshots = {}, [], {}
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
            snapshots[report["run_id"] or report["generated_at"]] = report
        except (OSError, ValueError, UnicodeError):
            diagnostics.append({"report_date": path.stem, "code": "report-unreadable"})
    for name in ("previous.json", "latest.json"):
        path = data_dir / name
        if not path.exists():
            continue
        try:
            report = read_report(path)
            if report["coverage"]["state"] == "unavailable" and not report["items"]:
                continue
            date = iso_date(report["report_date"])
            if cutoff <= date <= today:
                snapshots[report["run_id"] or report["generated_at"]] = report
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
    days = {date: snapshots[report["run_id"] or report["generated_at"]] for date, report in days.items()}
    enrich_reports(list(snapshots.values()))
    if last_run:
        matching = snapshots.get(last_run["run_id"] or last_run["generated_at"])
        if matching:
            last_run = matching
        else:
            last_run.pop("_saved_groups", None)
            last_run["groups"] = []
    reports = list(days.values()) + ([last_run] if last_run else [])
    return {"schema_version": 1, "module_id": "ai-opinion", "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "calendar_date": today.isoformat(), "retention_days": 14,
            "days": [days[key] for key in sorted(days, reverse=True)],
            "last_run": last_run, "diagnostics": diagnostics,
            "is_demo": bool(reports) and all(report["is_demo"] for report in reports)}


def demo_data(today=None):
    """Create explicit fictional snapshots with their own delta baselines."""
    today = today or dt.datetime.now(SHANGHAI).date()
    days = []
    headlines = [
        ("domestic", "high", "虚构示例：某AI服务中断公告，影响仍待核验", "中断"),
        ("domestic", "neutral", "虚构示例：国内模型团队发布使用指南", ""),
        ("international", "positive", "Fictional example: an AI product announces a new model", "发布"),
        ("hardware", "medium", "虚构示例：一款AI硬件调整售价，范围待确认", "价格"),
        ("voices", "neutral", "虚构示例：研究者讨论AI应用的评估方法", ""),
        ("hot", "neutral", "虚构示例：AI眼镜话题进入热搜", ""),
    ]
    for offset in range(3):
        date = today - dt.timedelta(days=offset)
        stamp = date.isoformat() + "T01:00:00Z"
        rid = f"demo-run-{offset}"
        ids = [f"demo-{offset}-{i}" for i in range(len(headlines))]
        has_baseline = offset < 2
        delta = {"schema_version": 1, "module_id": "ai-opinion", "run_id": rid,
                 "has_baseline": has_baseline, "baseline_run_id": f"demo-run-{offset+1}" if has_baseline else None,
                 "baseline_generated_at": (date-dt.timedelta(days=1)).isoformat()+"T01:00:00Z" if has_baseline else None,
                 "comparison_scope": "recent_seen_14_days" if has_baseline else "first_available_run", "comparison_skipped": False,
                 "new_ids": [ids[0], ids[2]] if has_baseline else [],
                 "changed_ids": [ids[3]] if has_baseline else [],
                 "unchanged_ids": [ids[1], ids[4], ids[5]] if has_baseline else []}
        report = {"schema_version": 1, "module_id": "ai-opinion", "run_id": rid,
                  "generated_at": stamp, "report_date": date.isoformat(), "window_days": 2,
                  "is_demo": True, "coverage": {"state": "partial"}, "delta": delta,
                  "items": [{"id": ids[i], "section": section, "title": title,
                             "url": f"https://example.com/ai-demo/{offset}/{i}", "source": "虚构演示来源",
                             "published_at": stamp if section != "hot" else None, "observed_at": stamp,
                             "time_basis": "observed" if section == "hot" else "published",
                             "risk": risk, "risk_terms": [term] if term else []}
                            for i, (section, risk, title, term) in enumerate(headlines)],
                  "sources": [{"id": "demo-rss", "name": "演示 RSS A", "state": "ok", "fetched_count": 12, "accepted_count": 5},
                              {"id": "demo-empty", "name": "演示 RSS B", "state": "empty", "fetched_count": 4, "accepted_count": 0, "empty_reason": "filtered"},
                              {"id": "demo-error", "name": "演示 RSS C", "state": "error", "fetched_count": 0, "accepted_count": 0, "error_code": "timeout"}]}
        days.append(clean_report(report))
    enrich_reports(days)
    return {"schema_version": 1, "module_id": "ai-opinion", "generated_at": days[0]["generated_at"],
            "calendar_date": today.isoformat(), "retention_days": 14, "days": days,
            "last_run": days[0], "diagnostics": [], "is_demo": True}


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
