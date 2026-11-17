#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative headline grouping and dates observed in saved AI reports."""
from __future__ import annotations

import copy
import datetime as dt
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MODULE_ID = "ai-opinion"
WINDOW_DAYS = 14
MAX_HISTORY = 5000
RANK = {"high": 0, "medium": 1, "positive": 2, "neutral": 3}
SECTIONS = {"domestic", "international", "hardware", "voices", "hot"}
ENTITY_ALIASES = {
    "openai": ("openai", "奥特曼", "sam altman"),
    "chatgpt": ("chatgpt",), "anthropic": ("anthropic", "claude"),
    "google": ("google", "谷歌", "gemini", "deepmind"),
    "xai": ("xai", "grok"), "nvidia": ("nvidia", "英伟达", "黄仁勋", "jensen huang"),
    "deepseek": ("deepseek", "深度求索", "梁文锋"),
    "alibaba": ("阿里", "通义", "qwen"), "bytedance": ("字节", "豆包", "bytedance"),
    "moonshot": ("kimi", "月之暗面", "杨植麟"), "zhipu": ("智谱", "glm"),
    "tencent": ("腾讯", "混元", "元宝", "tencent"), "baidu": ("百度", "文心", "李彦宏"),
    "minimax": ("minimax",), "unitree": ("宇树", "unitree", "王兴兴"),
    "agibot": ("智元", "agibot"), "microsoft": ("微软", "microsoft", "copilot"),
    "cursor": ("cursor",), "meta": ("meta", "扎克伯格", "zuckerberg"),
    "apple": ("apple", "苹果", "库克"), "amazon": ("amazon", "亚马逊", "贝索斯"),
}


def canonical_url(value):
    if (not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value)
            or any(c in value for c in '<>"\\')):
        return ""
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.casefold().startswith("utm_") and k.casefold() not in {"oc", "fbclid", "gclid"}]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                           urlencode(sorted(query)), ""))
    except ValueError:
        return ""


def normalized(value):
    return re.sub(r"[\W_]+", "", html.unescape(value).casefold())


def key(value):
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def iso_date(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None
    except ValueError:
        return None


@lru_cache(maxsize=12000)
def title_features(title):
    text = html.unescape(title).casefold()
    norm = normalized(text)
    entities = frozenset(name for name, aliases in ENTITY_ALIASES.items() if any(
        (re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text)
         if re.fullmatch(r"[a-z0-9 ]+", alias) else alias in text) for alias in aliases))
    numbers = frozenset(re.findall(r"\d+(?:[.,]\d+)*", text))
    grams = frozenset(norm[i:i + 2] for i in range(len(norm) - 1))
    return norm, entities, numbers, grams


def claim_markers(title):
    """A small contradiction guard, not semantic fact verification."""
    text = html.unescape(title).casefold()
    negative = bool(re.search(r"\b(?:no|not|never|denies|denied|false|refutes|refuted)\b", text)
                    or any(term in text for term in ("否认", "并未", "尚未", "不会", "未能", "辟谣", "取消发布", "撤回发布", "停止发布")))
    actions = set()
    patterns = {
        "release": (r"\b(?:releas(?:e|es|ed|ing)|launch(?:es|ed|ing)?|unveil(?:s|ed|ing)?)\b", ("发布", "推出", "上线", "开源")),
        "withdraw": (r"\b(?:cancel(?:s|led|ed|ing)?|withdraw(?:s|n)?|discontinu(?:e|es|ed|ing))\b", ("下架", "停止", "撤回", "取消", "停用")),
        "outage": (r"\b(?:outage|disruption|downtime)\b", ("宕机", "中断", "故障")),
        "recovery": (r"\b(?:recover(?:s|ed|y|ing)?|restor(?:e|es|ed|ing))\b", ("恢复", "修复")),
    }
    for action, (pattern, words) in patterns.items():
        if re.search(pattern, text) or any(word in text for word in words):
            actions.add(action)
    return negative, actions


@lru_cache(maxsize=12000)
def event_signatures(title):
    """Only explicit, narrow topic anchors; no general event inference."""
    text = html.unescape(title).casefold()
    signatures = []
    # Filing direction matters: a company suing a state is a different topic.
    jurisdictions = {"california": ("加州", "加利福尼亚", "california"),
                     "new_york": ("纽约", "new york"), "texas": ("德州", "得克萨斯", "texas")}
    for place, aliases in jurisdictions.items():
        positions = [text.find(word) for word in aliases if word in text]
        if not positions:
            continue
        rest = text[min(positions):]
        action = re.search(r"起诉|提起诉讼|告上法庭|sues?\b|files?\s+(?:a\s+)?lawsuit\s+against\b", rest)
        if action:
            prefix = rest[:action.start()]
            if re.search(r"一名|用户|居民|家属|个人|投资者|\b(?:user|resident|investor|individual)s?\b", prefix):
                continue
            if re.search(r"考虑|计划|可能|准备|打算|或将|拟|\b(?:consider(?:s|ing)?|plan(?:s|ned|ning)?|may|might)\b", prefix):
                continue
            fragment = re.split(r"[，,:：;；]|指控|称|\bover\b|\bfor\b", rest[action.end():], maxsplit=1)[0]
            targets = title_features(fragment)[1]
            if not targets and "对" in prefix:
                targets = title_features(prefix.split("对", 1)[1])[1]
            if not targets and "将" in prefix:
                targets = title_features(prefix.split("将", 1)[1])[1]
            if not targets and re.search(r"(?:遭|被).{0,5}$", text[:min(positions)]):
                targets = title_features(text[:min(positions)])[1]
            if "openai" in targets:
                targets = targets - {"chatgpt"}
            if targets:
                signatures.append("legal:" + place + ":files-suit:" + ",".join(sorted(targets)))
        elif re.search(r"openai.{0,35}\bsued\s+by\b.{0,25}california", text):
            signatures.append("legal:" + place + ":files-suit:openai")
    if ("cursor" in text and re.search(r"fireworks\s*(?:ai)?", text)
            and re.search(r"claude\s*code", text)
            and re.search(r"扩展|\bextension\b", text)
            and re.search(r"密钥|\bkeys?\b|\bcredentials?\b", text)
            and re.search(r"泄露|被盗|\bstolen\b|\bleak(?:ed|s|age)?\b|\bexpos(?:ed|ure)\b", text)):
        signatures.append("credential-extension:cursor:fireworks:claude-code")
    return tuple(signatures)


def report_time(item):
    for field in ("published_at", "observed_at"):
        value = item.get(field)
        try:
            stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
            if stamp and stamp.tzinfo:
                return stamp.astimezone(dt.timezone.utc)
        except ValueError:
            pass
    return None


def legal_causes(title):
    text = html.unescape(title).casefold()
    terms = {"copyright": ("copyright", "版权", "著作权"),
             "minor_safety": ("teen safety", "child safety", "青少年", "未成年", "儿童保护"),
             "competition": ("antitrust", "monopoly", "垄断")}
    return {cause for cause, words in terms.items() if any(word in text for word in words)}


def event_compatible(left, right):
    a, b = left.get("title", ""), right.get("title", "")
    if not set(event_signatures(a)) & set(event_signatures(b)):
        return False
    ta, tb = report_time(left), report_time(right)
    if ta is None or tb is None or abs(ta - tb) > dt.timedelta(hours=48):
        return False
    ca, cb = legal_causes(a), legal_causes(b)
    if ca and cb and ca.isdisjoint(cb):
        return False
    na, nb = title_features(a)[2], title_features(b)[2]
    # Missing details are not a conflict. Explicit different numbers are.
    if na and nb and na != nb:
        return False
    if claim_markers(a)[0] != claim_markers(b)[0]:
        return False
    # Preserve product versions even when another headline omits detail.
    version = r"\b(gpt|claude|gemini|glm|qwen|kimi|deepseek)[\s-]*(\d+(?:[.-]\d+)*)"
    va, vb = dict(re.findall(version, a.casefold())), dict(re.findall(version, b.casefold()))
    return not any(va[name] != vb[name] for name in va.keys() & vb.keys())


def same_story(left, right):
    """Textual duplication only; shared numbers or brands are insufficient."""
    lu, ru = canonical_url(left.get("url", "")), canonical_url(right.get("url", ""))
    if lu and lu == ru:
        return True
    a, ea, na, ga = title_features(left.get("title", ""))
    b, eb, nb, gb = title_features(right.get("title", ""))
    if not a or not b:
        return False
    if a == b:
        return True
    event_a, event_b = set(event_signatures(left.get("title", ""))), set(event_signatures(right.get("title", "")))
    if event_a & event_b:
        return event_compatible(left, right)
    # Do not let generic text similarity erase an explicit legal jurisdiction
    # or direction mismatch that the narrow topic rule refused.
    if any(x.startswith("legal:") for x in event_a | event_b) and any(
            re.search(r"起诉|诉讼|\bsue(?:s|d)?\b|\blawsuit\b", title, re.I)
            for title in (left.get("title", ""), right.get("title", ""))):
        return False
    if min(len(a), len(b)) < 12 or na != nb or ea != eb:
        return False
    # No shared named subject: prefer a miss to merging unrelated generic AI
    # commentary. Exact headlines above still merge regardless of language.
    if not ea or min(len(a), len(b)) / max(len(a), len(b)) < 0.72:
        return False
    left_negative, left_actions = claim_markers(left.get("title", ""))
    right_negative, right_actions = claim_markers(right.get("title", ""))
    if (left_negative != right_negative or
            (("withdraw" in left_actions) != ("withdraw" in right_actions)) or
            (left_actions and right_actions and left_actions.isdisjoint(right_actions))):
        return False
    similarity = SequenceMatcher(None, a, b, autojunk=False).ratio()
    overlap = len(ga & gb) / len(ga | gb) if ga and gb else 0
    return similarity >= 0.86 and overlap >= 0.68


def clean_mention(raw, raw_id=""):
    if not isinstance(raw, dict):
        return None
    title = re.sub(r"\s+", " ", raw.get("title", "")).strip()[:1000] if isinstance(raw.get("title"), str) else ""
    url = canonical_url(raw.get("url", ""))
    if not title:
        return None
    section = raw.get("section") if raw.get("section") in SECTIONS else "domestic"
    terms = raw.get("risk_terms", [])
    return {"raw_id": str(raw_id)[:160], "title": title, "url": url,
            "source": raw.get("source", "")[:200] if isinstance(raw.get("source"), str) else "",
            "section": section, "published_at": raw.get("published_at") if isinstance(raw.get("published_at"), str) else None,
            "observed_at": raw.get("observed_at") if isinstance(raw.get("observed_at"), str) else None,
            "time_basis": raw.get("time_basis", ""),
            "risk": raw.get("risk") if raw.get("risk") in RANK else "neutral",
            "risk_terms": [str(term)[:60] for term in terms[:12]] if isinstance(terms, list) else []}


def merge_items(items):
    observations = []
    for item in items:
        if not isinstance(item, dict):
            continue
        main = clean_mention(item, item.get("id", ""))
        if main:
            observations.append(main)
        for mention in item.get("mentions", []) if isinstance(item.get("mentions"), list) else []:
            clean = clean_mention(mention, item.get("id", ""))
            if clean:
                observations.append(clean)
    observations.sort(key=lambda item: (canonical_url(item["url"]), normalized(item["title"]), item["source"], item["raw_id"]))
    groups, url_map, title_map, fuzzy_map, event_map = [], {}, {}, {}, {}
    for observation in observations:
        url, title_key = observation["url"], normalized(observation["title"])
        hit = url_map.get(url) if url else None
        if hit is None:
            hit = title_map.get(title_key)
        basis = "url" if hit is not None and url and url in url_map else "exact_title" if hit is not None else ""
        if hit is None:
            candidates = [g for signature in event_signatures(observation["title"]) for g in event_map.get(signature, [])]
            hit = next((g for g in candidates if event_compatible(observation, g["anchor"])
                        and all(event_compatible(observation, m) for m in g["observations"])), None)
            if hit is not None:
                basis = "explicit_topic_anchor_within_48h"
        if hit is None:
            _, entities, numbers, _ = title_features(observation["title"])
            hit = next((g for g in fuzzy_map.get((entities, numbers), []) if same_story(observation, g["anchor"])), None)
            if hit is not None:
                basis = "near_text_same_subject_and_numbers"
        if hit is None:
            hit = {"anchor": observation, "observations": [], "mention_keys": set(), "basis": set()}
            groups.append(hit)
            _, entities, numbers, _ = title_features(observation["title"])
            if entities:
                fuzzy_map.setdefault((entities, numbers), []).append(hit)
        if basis:
            hit["basis"].add(basis)
        for signature in event_signatures(observation["title"]):
            if hit not in event_map.setdefault(signature, []):
                event_map[signature].append(hit)
        marker = (url, title_key, observation["source"])
        if marker not in hit["mention_keys"]:
            hit["mention_keys"].add(marker)
            hit["observations"].append(observation)
        elif observation["raw_id"]:
            # Retain all raw IDs even when two queries observed the same source.
            duplicate = next(m for m in hit["observations"] if (m["url"], normalized(m["title"]), m["source"]) == marker)
            duplicate.setdefault("extra_ids", []).append(observation["raw_id"])
        if url:
            url_map[url] = hit
        title_map[title_key] = hit
    result = []
    for group in groups:
        mentions = group["observations"]
        representative = min(mentions, key=lambda m: (RANK[m["risk"]], -len(m["title"]), m["url"], m["source"]))
        ids = sorted({rid for m in mentions for rid in [m["raw_id"], *m.get("extra_ids", [])] if rid})
        sources = [{k: v for k, v in mention.items() if k not in {"raw_id", "extra_ids"}} for mention in mentions]
        result.append({**{k: v for k, v in representative.items() if k not in {"raw_id", "extra_ids"}},
                       "id": key(representative["url"] or normalized(representative["title"])),
                       "member_ids": ids, "sections": sorted({m["section"] for m in mentions}),
                       "source_names": sorted({m["source"] for m in mentions if m["source"]}),
                       "source_count": len(sources), "sources": sources,
                       "grouping_basis": sorted(group["basis"]) or ["single_report"],
                       "risk_terms": sorted({term for m in mentions for term in m["risk_terms"]}),
                       "change": "baseline"})
    return result


def empty_history(is_demo=False):
    return {"schema_version": 1, "module_id": MODULE_ID, "is_demo": bool(is_demo),
            "run_id": "", "window_days": WINDOW_DAYS, "scope": "recorded_dates",
            "records": [], "truncated": False}


def valid_history(value, is_demo):
    if not (isinstance(value, dict) and value.get("schema_version") == 1 and
            value.get("module_id") == MODULE_ID and value.get("is_demo") is is_demo and
            isinstance(value.get("records"), list) and len(value["records"]) <= MAX_HISTORY):
        return False
    for record in value["records"]:
        if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", record["id"])
                or not iso_date(record.get("first_recorded_date")) or not iso_date(record.get("last_recorded_date"))
                or not isinstance(record.get("observed_dates"), list) or len(record["observed_dates"]) > WINDOW_DAYS
                or any(not iso_date(day) for day in record["observed_dates"])):
            return False
        for field, limit in (("url_keys", 64), ("title_keys", 16)):
            minimum = 0 if field == "url_keys" else 1
            if (not isinstance(record.get(field), list) or not minimum <= len(record[field]) <= limit
                    or any(not isinstance(k, str) or not re.fullmatch(r"[0-9a-f]{24}", k) for k in record[field])):
                return False
        if (not isinstance(record.get("title_variants"), list) or not 1 <= len(record["title_variants"]) <= 3
                or any(not isinstance(t, str) or not t or len(t) > 1000 for t in record["title_variants"])
                or not isinstance(record.get("change_events"), list) or len(record["change_events"]) > 32
                or any(not isinstance(e, dict) or not iso_date(e.get("date")) for e in record["change_events"])):
            return False
    return True


def annotate_report(report, previous_history=None):
    """Return cards and a new history; only successful recorded dates count."""
    selected_date = iso_date(report.get("report_date"))
    if not selected_date:
        raise ValueError("invalid story report date")
    if previous_history is not None and not valid_history(previous_history, report.get("is_demo") is True):
        raise ValueError("invalid story history")
    history = copy.deepcopy(previous_history) if previous_history is not None else empty_history(report.get("is_demo") is True)
    cutoff = selected_date - dt.timedelta(days=WINDOW_DAYS - 1)
    records = []
    for record in history["records"]:
        if not isinstance(record, dict) or not iso_date(record.get("last_recorded_date")):
            continue
        if not cutoff <= iso_date(record["last_recorded_date"]) <= selected_date:
            continue
        records.append(record)
    url_records = {key: record for record in records for key in record["url_keys"]}
    title_records = {key: record for record in records for key in record["title_keys"]}
    fuzzy_records, event_records = {}, {}
    for record in records:
        for title in record["title_variants"]:
            for signature in event_signatures(title):
                if record not in event_records.setdefault(signature, []):
                    event_records[signature].append(record)
            _, entities, numbers, _ = title_features(title)
            if entities:
                bucket = fuzzy_records.setdefault((entities, numbers), [])
                if record not in bucket:
                    bucket.append(record)
    groups = merge_items(report.get("items", []))
    delta = report.get("delta", {})
    comparable = delta.get("has_baseline") is True and delta.get("comparison_skipped") is False
    changed_ids = set(delta.get("changed_ids", [])) if comparable else set()
    new_ids = set(delta.get("new_ids", [])) if comparable else set()
    for group in groups:
        urls = {key(source["url"]) for source in group["sources"] if source["url"]}
        titles = {key(normalized(source["title"])) for source in group["sources"]}
        record = next((url_records[k] for k in sorted(urls) if k in url_records), None)
        if record is None:
            record = next((title_records[k] for k in sorted(titles) if k in title_records), None)
        if record is None:
            candidates = [r for signature in event_signatures(group["title"]) for r in event_records.get(signature, [])]
            record = next((r for r in candidates if any(event_compatible(group, {"title": title, "published_at": r.get("latest_report_time")}) for title in r["title_variants"])), None)
        if record is None:
            _, entities, numbers, _ = title_features(group["title"])
            record = next((r for r in fuzzy_records.get((entities, numbers), [])
                           if any(same_story(group, {"title": title}) for title in r["title_variants"])), None)
        # A newly improved display cluster may join several old source-level
        # records. Union their actual dates rather than losing the earliest one.
        peers = {id(url_records[k]): url_records[k] for k in urls if k in url_records}
        peers.update({id(title_records[k]): title_records[k] for k in titles if k in title_records})
        if record is not None:
            peers[id(record)] = record
        if peers:
            record = min(peers.values(), key=lambda r: (r["first_recorded_date"], r["id"]))
            for peer in peers.values():
                if peer is record:
                    continue
                for field in ("observed_dates", "url_keys", "title_keys", "title_variants"):
                    record[field] = list(dict.fromkeys(record.get(field, []) + peer.get(field, [])))
                events = record.get("change_events", []) + peer.get("change_events", [])
                record["change_events"] = list({(e.get("date"), e.get("run_id")): e for e in events}.values())[-32:]
                record["first_recorded_date"] = min(record["first_recorded_date"], peer["first_recorded_date"])
                record["last_recorded_date"] = max(record["last_recorded_date"], peer["last_recorded_date"])
            if len(peers) > 1:
                removed = set(peers) - {id(record)}
                records = [r for r in records if id(r) not in removed]
                for mapping in (url_records, title_records):
                    for k, value in list(mapping.items()):
                        if id(value) in removed:
                            mapping[k] = record
                for mapping in (fuzzy_records, event_records):
                    for k, values in list(mapping.items()):
                        mapping[k] = list({id(record if id(value) in removed else value): record if id(value) in removed else value for value in values}.values())
        existed = record is not None
        if record is None:
            record = {"id": group["id"], "observed_dates": [], "url_keys": [], "title_keys": [],
                      "title_variants": [], "first_recorded_date": report["report_date"],
                      "last_recorded_date": report["report_date"], "change_events": []}
            records.append(record)
        group["id"] = record["id"]
        raw_changed = bool(changed_ids & set(group["member_ids"]))
        group["change"] = "baseline" if not comparable else "changed" if raw_changed else "unchanged" if existed else "new" if new_ids & set(group["member_ids"]) else "unchanged"
        dates = {d for d in record.get("observed_dates", []) if iso_date(d) and cutoff <= iso_date(d) <= selected_date}
        dates.add(report["report_date"])
        record["observed_dates"] = sorted(dates)
        first = record.get("first_recorded_date")
        record["first_recorded_date"] = min(first, report["report_date"]) if iso_date(first) else report["report_date"]
        record["last_recorded_date"] = max(dates)
        record["url_keys"] = list(dict.fromkeys(record.get("url_keys", []) + sorted(urls)))[-64:]
        record["title_keys"] = list(dict.fromkeys(record.get("title_keys", []) + sorted(titles)))[-16:]
        record["title_variants"] = list(dict.fromkeys(record.get("title_variants", []) + [source["title"][:1000] for source in group["sources"]]))[-3:]
        times = [report_time(source) for source in group["sources"]]
        times = [value for value in times if value is not None]
        if times:
            record["latest_report_time"] = max(times).isoformat()
        for k in urls:
            url_records[k] = record
        for k in titles:
            title_records[k] = record
        if raw_changed:
            event = {"date": report["report_date"], "generated_at": report.get("generated_at", ""),
                     "run_id": report.get("run_id", ""), "title": group["title"], "kind": "title_or_keyword_change"}
            if not any(e.get("run_id") == event["run_id"] for e in record["change_events"]):
                record["change_events"].append(event)
        record["change_events"] = [e for e in record.get("change_events", []) if iso_date(e.get("date")) and cutoff <= iso_date(e["date"]) <= selected_date][-32:]
        streak, day = 0, selected_date
        while day.isoformat() in dates:
            streak += 1
            day -= dt.timedelta(days=1)
        group["history"] = {"observed_dates": sorted(dates), "first_recorded_date": record["first_recorded_date"],
                            "last_recorded_date": record["last_recorded_date"], "observed_days": len(dates),
                            "consecutive_days": streak, "change_dates": sorted({e["date"] for e in record["change_events"]}),
                            "change_events": copy.deepcopy(record["change_events"]), "window_days": WINDOW_DAYS,
                            "scope": "recorded_dates", "history_complete": False}
    # Pairwise variants may both match a prior cluster. Render its identity
    # once, retaining all sources, without claiming a verified real event.
    unique = {}
    for group in groups:
        if group["id"] not in unique:
            unique[group["id"]] = group
            continue
        target = unique[group["id"]]
        sources = {(source["url"], normalized(source["title"]), source["source"]): source
                   for source in target["sources"] + group["sources"]}
        target["sources"] = list(sources.values())
        target["source_count"] = len(sources)
        target["grouping_basis"] = sorted(set(target["grouping_basis"] + group["grouping_basis"]))
        target["source_names"] = sorted(set(target["source_names"] + group["source_names"]))
        target["member_ids"] = sorted(set(target["member_ids"] + group["member_ids"]))
        target["sections"] = sorted(set(target["sections"] + group["sections"]))
        target["risk_terms"] = sorted(set(target["risk_terms"] + group["risk_terms"]))
        if RANK[group["risk"]] < RANK[target["risk"]]:
            for field in ("title", "url", "source", "section", "published_at", "observed_at", "time_basis", "risk"):
                target[field] = group[field]
        priority = {"changed": 0, "new": 1, "unchanged": 2, "baseline": 3}
        target["change"] = min((target["change"], group["change"]), key=priority.get)
        target["history"] = group["history"]
    groups = list(unique.values())
    ordered = sorted(records, key=lambda r: (r["last_recorded_date"], r["id"]), reverse=True)
    history.update(run_id=report.get("run_id", ""), records=ordered[:MAX_HISTORY], truncated=len(ordered) > MAX_HISTORY,
                   latest_recorded_date=report["report_date"])
    return groups, history
