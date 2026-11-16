from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import os
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PARSER = Path(os.environ.get("GALLICA_PARSER_ROOT", PROJECT))
ANALYSIS = Path(os.environ.get("GALLICA_ANALYSIS_OUT", PROJECT / "outputs" / "combined"))
BASE = Path(os.environ.get("GALLICA_SEARCH_ROOT", PARSER))
RESULT_JSON = ANALYSIS / "reviewer_robustness_results.json"
RESULT_CSV = ANALYSIS / "reviewer_robustness_by_event.csv"
PROGRESS = ANALYSIS / "reviewer_robustness_progress.txt"

EVENTS = {
    "borodino": ((1812,), [r"\bborodin[oa]?\b", r"\b(?:la\s+)?mos[ck]owa\b"]),
    "moscow": ((1812,), [r"\bmoscou\b"]),
    "lutzen": ((1813,), [r"\blutzen\b"]),
    "bautzen": ((1813,), [r"\bbautzen\b", r"\bbauzen\b"]),
    "leipzig": ((1813,), [r"\bleipzig\b", r"\bleipsi(?:c|ck|g)\b"]),
    "paris1814": ((1814,), [r"\b(?:paix|traite)\s+(?:de\s+)?paris\b", r"\bparis\s+(?:paix|traite)\b"]),
    "vienna": ((1814, 1815), [r"\bcongres\s+(?:de\s+)?vienne\b", r"\bvienne\s+congres\b"]),
    "paris1815": ((1815,), [r"\b(?:paix|traite)\s+(?:de\s+)?paris\b", r"\bparis\s+(?:paix|traite)\b"]),
    "holy_alliance": ((1815, 1816), [r"\bacte\s+(?:de\s+la\s+)?sainte\s+alliance\b", r"\bsainte\s+alliance\b"]),
    "aachen": ((1818,), [r"\baix\s+la\s+chapelle\b"]),
    "troppau": ((1820,), [r"\btroppau\b"]),
    "laibach": ((1821,), [r"\blai?ybach\b", r"\blaibach\b"]),
    "verona": ((1822,), [r"\bverone\b"]),
}
EXTRA = {"moscow": [r"\babandon", r"\bevac", r"\bquitt", r"\bincendi", r"\bbrul", r"\bretraite\b"]}
ALEX = [r"\bempereur\s+alexandre\b", r"\balexandre\s+(?:i|1er|premier)\b", r"\b(?:czar|tsar)\s+alexandre\b", r"\bempereur\s+de\s+russie\b"]
THEMES_WIDE = {
    "order": [r"\bordres?\b", r"\blegitim", r"\btrone\b", r"\bsouverain", r"\brestauration\b", r"\bstabilite\b"],
    "liberty": [r"\bliberte\b", r"\bconstitution", r"\bdroits?\b", r"\bindependance\b", r"\brepresentation\b"],
    "intervention": [r"\bintervention\b", r"\bintervenir\b", r"\binvasion\b", r"\boccupation\b", r"\bexpedition\b"],
}
THEMES_NARROW = {
    "order": [r"\blegitim", r"\btrone\b", r"\bsouverain", r"\brestauration\b", r"\bstabilite\b"],
    "liberty": [r"\bliberte\b", r"\bconstitution", r"\bindependance\b", r"\brepresentation\b"],
    "intervention": [r"\binvasion\b", r"\boccupation\b", r"\bexpedition\b"],
}


def norm(text: str) -> str:
    text = text.lower().replace("œ", "oe").replace("æ", "ae").replace("’", "'")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def windows(text: str, overlap: int) -> list[str]:
    toks = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", norm(text))
    if not toks:
        return []
    if len(toks) <= 100:
        return [" ".join(toks)]
    step = 100 - overlap
    return [" ".join(toks[i:i + 100]) for i in range(0, len(toks), step) if len(toks[i:i + 100]) >= 30]


def any_match(text: str, pats: list[re.Pattern]) -> bool:
    return any(p.search(text) for p in pats)


def event_match(code: str, text: str, year: int, cev, cex) -> bool:
    years, _ = EVENTS[code]
    if year not in years or not any_match(text, cev[code]):
        return False
    return code not in cex or any_match(text, cex[code])


def alex_match(text: str, calex) -> bool:
    if any_match(text, calex):
        return True
    return bool(re.search(r"\balexandre\b", text) and re.search(r"\b(?:russie|russe|russes|czar|tsar|empereur|majeste\s+imperiale)\b", text))


def wilson(n: int, d: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if not d:
        return 0.0, 0.0
    p = n / d
    den = 1 + z * z / d
    center = (p + z * z / (2 * d)) / den
    half = z * math.sqrt(p * (1 - p) / d + z * z / (4 * d * d)) / den
    return 100 * (center - half), 100 * (center + half)


def find_one(name: str) -> Path:
    direct = {
        "03_Коды_событий_по_страницам.csv": ANALYSIS / name,
        "state_events_alexander_policy_1812_1822.sqlite3": PARSER / name,
        "state_all_newspapers_1812_1825.sqlite3": PARSER / name,
    }.get(name)
    if direct and direct.exists():
        return direct
    xs = list(BASE.rglob(name))
    if not xs:
        raise FileNotFoundError(name)
    return xs[0]


def main() -> None:
    ANALYSIS.mkdir(parents=True, exist_ok=True)
    csv03 = find_one("03_Коды_событий_по_страницам.csv")
    with csv03.open("r", encoding="utf-8-sig", newline="") as f:
        accepted = list(csv.DictReader(f))
    PROGRESS.write_text(f"loaded accepted pages: {len(accepted)}\n", encoding="utf-8")
    title_key = next(k for k in accepted[0] if "газет" in k.lower())

    mapping: dict[tuple[str, int], str] = {}
    for dbname in ("state_events_alexander_policy_1812_1822.sqlite3", "state_all_newspapers_1812_1825.sqlite3"):
        db = find_one(dbname)
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
        for ark, page, folder in con.execute("SELECT issue_ark,page_number,output_path FROM downloads"):
            mapping.setdefault((str(ark), int(page)), str(folder))
        con.close()
        PROGRESS.write_text(f"loaded database {dbname}: {len(mapping)} mapped pages\n", encoding="utf-8")

    extra_root = PARSER / "corpus_alexandre_sainte_alliance_1812_1825" / "Journal_de_la_Loz_re"
    for meta in extra_root.rglob("*_metadata.json") if extra_root.exists() else []:
        if "Journal_de_la_Loz_re" not in str(meta.parent):
            continue
        try:
            m = json.loads(meta.read_text(encoding="utf-8-sig"))
            mapping.setdefault((str(m["issue_ark"]).split("/")[-1], int(m["digital_page"])), str(meta.parent))
        except Exception:
            pass
    PROGRESS.write_text(f"loaded extra metadata: {len(mapping)} mapped pages\n", encoding="utf-8")

    counts_by_title = Counter(r[title_key] for r in accepted)
    top5 = {t for t, _ in counts_by_title.most_common(5)}
    cev = {k: [re.compile(x) for x in v[1]] for k, v in EVENTS.items()}
    cex = {k: [re.compile(x) for x in v] for k, v in EXTRA.items()}
    calex = [re.compile(x) for x in ALEX]
    tw = {k: [re.compile(x) for x in v] for k, v in THEMES_WIDE.items()}
    tn = {k: [re.compile(x) for x in v] for k, v in THEMES_NARROW.items()}

    stats = {o: defaultdict(lambda: defaultdict(int)) for o in (20, 0)}
    theme = {"wide": defaultdict(int), "narrow": defaultdict(int)}
    hash_counts = Counter()
    missing = 0
    total_event_windows = 0
    for idx, row in enumerate(accepted, 1):
        ark, page = row["issue_ark"], int(row["page"])
        folder = mapping.get((ark, page))
        txt = Path(folder) / f"page_{page}_ocr_clean.txt" if folder else None
        if not txt or not txt.exists():
            missing += 1
            continue
        raw = txt.read_text(encoding="utf-8", errors="replace")
        normalized = norm(raw)
        hash_counts[hashlib.sha256(normalized.encode("utf-8")).hexdigest()] += 1
        year = int(row["year"])
        title = row[title_key]
        active_codes = [code for code in EVENTS if str(row.get(code, "0")).strip() in {"1", "1.0"}]
        if not active_codes:
            if idx % 1000 == 0:
                PROGRESS.write_text(f"{idx}/{len(accepted)}\n", encoding="utf-8")
            continue
        for overlap in (20, 0):
            for w in windows(raw, overlap):
                a = alex_match(w, calex)
                for code in active_codes:
                    if event_match(code, w, year, cev, cex):
                        stats[overlap][code]["den_all"] += 1
                        stats[overlap][code]["num_all"] += int(a)
                        if title not in top5:
                            stats[overlap][code]["den_no_top5"] += 1
                            stats[overlap][code]["num_no_top5"] += int(a)
                        if overlap == 20:
                            total_event_windows += 1
                            for cat in tw:
                                theme["wide"][cat] += int(any_match(w, tw[cat]))
                                theme["narrow"][cat] += int(any_match(w, tn[cat]))
        if idx % 1000 == 0:
            PROGRESS.write_text(f"{idx}/{len(accepted)}\n", encoding="utf-8")

    rows = []
    for code in EVENTS:
        s20, s0 = stats[20][code], stats[0][code]
        n, d = s20["num_all"], s20["den_all"]
        lo, hi = wilson(n, d)
        def pct(a, b): return 100 * a / b if b else 0.0
        rows.append({
            "event": code,
            "windows_overlap20": d,
            "with_alexander_overlap20": n,
            "percent_overlap20": round(pct(n, d), 2),
            "wilson95_low": round(lo, 2),
            "wilson95_high": round(hi, 2),
            "percent_no_overlap": round(pct(s0["num_all"], s0["den_all"]), 2),
            "percent_excluding_top5": round(pct(s20["num_no_top5"], s20["den_no_top5"]), 2),
        })

    repeated_groups = sum(1 for v in hash_counts.values() if v > 1)
    repeated_pages = sum(v for v in hash_counts.values() if v > 1)
    repeated_excess = sum(v - 1 for v in hash_counts.values() if v > 1)
    result = {
        "pages_expected": len(accepted),
        "pages_missing": missing,
        "top5": counts_by_title.most_common(5),
        "top5_share_percent": round(100 * sum(v for _, v in counts_by_title.most_common(5)) / len(accepted), 2),
        "exact_normalized_duplicate_groups": repeated_groups,
        "pages_in_exact_duplicate_groups": repeated_pages,
        "exact_duplicate_excess_pages": repeated_excess,
        "exact_duplicate_excess_share_percent": round(100 * repeated_excess / len(accepted), 2),
        "event_windows_overlap20": total_event_windows,
        "theme_dictionary_sensitivity": {
            cat: {
                "wide_percent": round(100 * theme["wide"][cat] / total_event_windows, 2),
                "narrow_percent": round(100 * theme["narrow"][cat] / total_event_windows, 2),
                "difference_pp": round(100 * (theme["narrow"][cat] - theme["wide"][cat]) / total_event_windows, 2),
            } for cat in tw
        },
        "events": rows,
    }
    RESULT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with RESULT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    PROGRESS.write_text("complete\n", encoding="utf-8")


if __name__ == "__main__":
    main()
