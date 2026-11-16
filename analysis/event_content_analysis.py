from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
import sys
import os
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT = Path(__file__).resolve().parents[1]
PARSER_ROOT = Path(os.environ.get("GALLICA_PARSER_ROOT", PROJECT))
DB_EVENT = Path(os.environ.get("GALLICA_EVENT_DB", PARSER_ROOT / "state_events_alexander_policy_1812_1822.sqlite3"))
DB_FIRST = Path(os.environ.get("GALLICA_PERSONALIZED_DB", PARSER_ROOT / "state_all_newspapers_1812_1825.sqlite3"))
EXTRA_FIRST_CORPUS = Path(os.environ.get(
    "GALLICA_EXTRA_CORPUS",
    PARSER_ROOT / "corpus_alexandre_sainte_alliance_1812_1825" / "Journal_de_la_Loz_re",
))
AUDIT = Path(os.environ.get("GALLICA_AUDIT_CSV", PROJECT / "data" / "newspaper_type_audit.csv"))
COMBINED = "--combined" in sys.argv
OUT = Path(os.environ.get(
    "GALLICA_ANALYSIS_OUT",
    PROJECT / "outputs" / ("combined" if COMBINED else "events_only"),
))

UNKNOWN_NEWSPAPERS = {
    "Journal des arts et de la politique",
    "Journal de la Côte-d'Or : feuille politique, littéraire, commerciale et industrielle...",
    "Le Réveil : journal des sciences, de la littérature, des moeurs, théâtres et beaux-arts",
    "Affiches, annonces et avis divers de la ville de Dijon",
    "Affiches, annonces et avis divers de la ville de Metz",
    "Feuille d'annonces du département de la Manche",
    "L'Ami de la Charte : journal du Puy-de-Dôme [\"puis\" du Puy-de-Dôme, de la Haute-Loire et du Cantal \"puis\" du Puy-de-Dôme, de la Haute-Loire, du Cantal et de la Corrèze]",
}

EVENTS = {
    "borodino": ("Бородинское сражение", (1812,), [r"\bborodin[oa]?\b", r"\b(?:la\s+)?mos[ck]owa\b"]),
    "moscow": ("Оставление и пожар Москвы", (1812,), [r"\bmoscou\b"]),
    "lutzen": ("Сражение при Лютцене", (1813,), [r"\blutzen\b", r"\blutzen\b"]),
    "bautzen": ("Сражение при Баутцене", (1813,), [r"\bbautzen\b", r"\bbauzen\b"]),
    "leipzig": ("Лейпцигская битва", (1813,), [r"\bleipzig\b", r"\bleipsi(?:c|ck|g)\b"]),
    "paris1814": ("Первый Парижский мир", (1814,), [r"\b(?:paix|traite)\s+(?:de\s+)?paris\b", r"\bparis\s+(?:paix|traite)\b"]),
    "vienna": ("Венский конгресс", (1814, 1815), [r"\bcongres\s+(?:de\s+)?vienne\b", r"\bvienne\s+congres\b"]),
    "paris1815": ("Второй Парижский мир", (1815,), [r"\b(?:paix|traite)\s+(?:de\s+)?paris\b", r"\bparis\s+(?:paix|traite)\b"]),
    "holy_alliance": ("Акт Священного союза", (1815, 1816), [r"\bacte\s+(?:de\s+la\s+)?sainte\s+alliance\b", r"\bsainte\s+alliance\b"]),
    "aachen": ("Аахенский конгресс", (1818,), [r"\baix\s+la\s+chapelle\b"]),
    "troppau": ("Троппауский конгресс", (1820,), [r"\btroppau\b"]),
    "laibach": ("Лайбахский конгресс", (1821,), [r"\blai?ybach\b", r"\blaibach\b"]),
    "verona": ("Веронский конгресс", (1822,), [r"\bverone\b"]),
}

ACTORS = {
    "alexander": ("Александр I", [r"\bempereur\s+alexandre\b", r"\balexandre\s+(?:i|1er|premier)\b", r"\b(?:czar|tsar)\s+alexandre\b", r"\bempereur\s+de\s+russie\b"]),
    "napoleon": ("Наполеон / Бонапарт", [r"\bnapoleon\b", r"\bbonaparte\b"]),
    "russia": ("Россия", [r"\brussie\b", r"\brusse?s?\b"]),
    "france": ("Франция", [r"\bfrance\b", r"\bfrancais(?:e|es)?\b"]),
    "prussia": ("Пруссия", [r"\bprusse\b", r"\bprussien(?:ne|nes|s)?\b"]),
    "austria": ("Австрия / Меттерних", [r"\bautriche\b", r"\bautrichien(?:ne|nes|s)?\b", r"\bmetternich\b"]),
    "britain": ("Великобритания", [r"\bangleterre\b", r"\banglais(?:e|es)?\b", r"\bgrande\s+bretagne\b"]),
}

THEMES = {
    "victory": ("Победа и слава", [r"\bvictoire\b", r"\btriomph", r"\bgloire\b", r"\bglorieux", r"\bvainqueur"]),
    "defeat": ("Поражение и отступление", [r"\bdefaite\b", r"\bretraite\b", r"\bfuite\b", r"\bdesastre\b", r"\bperte?s?\b"]),
    "war": ("Война и насилие", [r"\bguerre\b", r"\bbataille\b", r"\bcombat", r"\barmee?s?\b", r"\btroupes?\b", r"\bsang\b", r"\bmort?s?\b"]),
    "peace": ("Мир и примирение", [r"\bpaix\b", r"\bpacifi", r"\btranquillite\b", r"\brepos\b", r"\breconciliation\b", r"\bconcorde\b"]),
    "diplomacy": ("Союз и дипломатия", [r"\balliance\b", r"\btraite\b", r"\bcongres\b", r"\bconference\b", r"\bnegoci", r"\bambassade", r"\bplenipotentiaire"]),
    "order": ("Порядок и легитимность", [r"\bordres?\b", r"\blegitim", r"\btrone\b", r"\bsouverain", r"\brestauration\b", r"\bstabilite\b"]),
    "liberty": ("Свобода и конституция", [r"\bliberte\b", r"\bconstitution", r"\bdroits?\b", r"\bindependance\b", r"\brepresentation\b"]),
    "religion": ("Христианская мораль", [r"\bchretien", r"\breligion\b", r"\bprovidence\b", r"\bevang", r"\bdivin", r"\bdieu\b", r"\bfraternite\b", r"\bhumanite\b"]),
    "intervention": ("Интервенция", [r"\bintervention\b", r"\bintervenir\b", r"\binvasion\b", r"\boccupation\b", r"\bexpedition\b"]),
}

EVENT_EXTRA = {
    "moscow": [r"\babandon", r"\bevac", r"\bquitt", r"\bincendi", r"\bbrul", r"\bretraite\b"],
}


def norm(text: str) -> str:
    text = text.lower().replace("œ", "oe").replace("æ", "ae").replace("’", "'")
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


def windows(text: str, size: int, overlap: int):
    tokens = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", norm(text))
    if not tokens:
        return []
    if len(tokens) <= size:
        return [" ".join(tokens)]
    step = size - overlap
    return [" ".join(tokens[i:i + size]) for i in range(0, len(tokens), step) if len(tokens[i:i + size]) >= min(30, size)]


def any_match(text: str, patterns: list[re.Pattern]) -> bool:
    return any(rx.search(text) for rx in patterns)


def actor_match(code: str, text: str, compiled_actors) -> bool:
    if any_match(text, compiled_actors[code]):
        return True
    if code == "alexander" and re.search(r"\balexandre\b", text):
        return bool(re.search(r"\b(?:russie|russe|russes|czar|tsar|empereur|majest[eé]\s+imperiale)\b", text))
    return False


def event_match(code: str, text: str, year: int, compiled_events, compiled_extra) -> bool:
    if year not in EVENTS[code][1] or not any_match(text, compiled_events[code]):
        return False
    if code in compiled_extra:
        return any_match(text, compiled_extra[code])
    return True


def pct(n, d):
    return round(100 * n / d, 2) if d else 0.0


def save_csv(name, rows):
    pd.DataFrame(rows).to_csv(OUT / name, index=False, encoding="utf-8-sig")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    audit_df = pd.read_csv(AUDIT)
    known_types = dict(zip(audit_df.newspaper, audit_df.source_type))

    databases = [DB_EVENT, DB_FIRST] if COMBINED else [DB_EVENT]
    raw_downloads = []
    query_errors_by_db = {}
    download_rows_by_db = {}
    for db_path in databases:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
        rows = con.execute(
            "SELECT d.issue_ark,d.page_number,d.output_path,c.title,c.publication_date "
            "FROM downloads d JOIN candidates c USING(issue_ark) ORDER BY c.publication_date,c.title,d.page_number"
        ).fetchall()
        raw_downloads.extend(rows)
        download_rows_by_db[db_path.name] = len(rows)
        try:
            query_errors_by_db[db_path.name] = con.execute("SELECT count(*) FROM issue_queries WHERE status='error'").fetchone()[0]
        except sqlite3.OperationalError:
            query_errors_by_db[db_path.name] = None
        con.close()

    if COMBINED and EXTRA_FIRST_CORPUS.exists():
        extra_rows = []
        for meta_path in EXTRA_FIRST_CORPUS.rglob("*_metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
                issue_ark = str(meta["issue_ark"]).split("/")[-1]
                page_no = int(meta["digital_page"])
                extra_rows.append((issue_ark, page_no, str(meta_path.parent), str(meta["periodical_title"]), str(meta["issue_date"])))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        raw_downloads.extend(extra_rows)
        download_rows_by_db["separate_Journal_de_la_Loz_re"] = len(extra_rows)

    # A page downloaded into both corpora has the same Gallica issue ARK and
    # physical page number. Keep one path only; do not hash-deduplicate different
    # issues because historical reprints are meaningful evidence.
    unique_downloads = {}
    for row in raw_downloads:
        unique_downloads.setdefault((row[0], row[1]), row)
    downloads = sorted(unique_downloads.values(), key=lambda x: (x[4], x[3], x[1]))
    duplicate_download_rows = len(raw_downloads) - len(downloads)

    title_counts = Counter(title for _, _, _, title, _ in downloads)
    audit_rows = []
    accepted_titles = set()
    for title, count in sorted(title_counts.items(), key=lambda x: (-x[1], x[0])):
        source_type = known_types.get(title)
        basis = "аудит прежнего корпуса"
        if source_type is None:
            source_type = "газета" if title in UNKNOWN_NEWSPAPERS else "исключено: журнал/прочее"
            basis = "ручная классификация нового названия"
        include = source_type == "газета"
        if include:
            accepted_titles.add(title)
        audit_rows.append({"издание": title, "страниц_в_базе": count, "тип": source_type, "включено": int(include), "основание": basis})
    save_csv("01_Аудит_типов_изданий.csv", audit_rows)

    pages = []
    missing = []
    seen = set()
    for issue_ark, page_no, folder, title, date in downloads:
        if title not in accepted_titles:
            continue
        key = (issue_ark, page_no)
        if key in seen:
            continue
        seen.add(key)
        txt = Path(folder) / f"page_{page_no}_ocr_clean.txt"
        if not txt.exists():
            missing.append({"issue_ark": issue_ark, "page": page_no, "path": str(txt)})
            continue
        raw = txt.read_text(encoding="utf-8", errors="replace")
        try:
            year = int(str(date)[:4])
        except ValueError:
            continue
        pages.append({"issue_ark": issue_ark, "page": page_no, "path": str(txt), "title": title, "date": str(date)[:10], "year": year, "text": raw, "words": len(re.findall(r"\w+", raw))})
    save_csv("02_Отсутствующие_OCR_файлы.csv", missing)

    ce = {k: [re.compile(x) for x in v[2]] for k, v in EVENTS.items()}
    ca = {k: [re.compile(x) for x in v[1]] for k, v in ACTORS.items()}
    ct = {k: [re.compile(x) for x in v[1]] for k, v in THEMES.items()}
    cx = {k: [re.compile(x) for x in v] for k, v in EVENT_EXTRA.items()}

    page_event_rows = []
    newspaper = defaultdict(lambda: {"pages": 0, "issues": set(), "words": 0, "events": Counter()})
    yearly = defaultdict(lambda: {"pages": 0, "words": 0, "events": Counter()})
    main_fragments = []
    sensitivity_rows = []
    mutual_rows = []
    theme_rows = []

    # Reuse tokenized windows for all calculations at the principal size.
    page_windows_100 = {}
    for i, page in enumerate(pages):
        ws = windows(page["text"], 100, 20)
        page_windows_100[i] = ws
        ev_presence = {}
        for code in EVENTS:
            ev_presence[code] = any(event_match(code, w, page["year"], ce, cx) for w in ws)
        page_event_rows.append({"issue_ark": page["issue_ark"], "page": page["page"], "date": page["date"], "year": page["year"], "газета": page["title"], "слов": page["words"], **{code: int(v) for code, v in ev_presence.items()}})
        n = newspaper[page["title"]]; n["pages"] += 1; n["issues"].add(page["issue_ark"]); n["words"] += page["words"]
        y = yearly[page["year"]]; y["pages"] += 1; y["words"] += page["words"]
        for code, present in ev_presence.items():
            n["events"][code] += int(present); y["events"][code] += int(present)
        for wi, w in enumerate(ws):
            ev = {code: event_match(code, w, page["year"], ce, cx) for code in EVENTS}
            ac = {code: actor_match(code, w, ca) for code in ACTORS}
            th = {code: any_match(w, pats) for code, pats in ct.items()}
            main_fragments.append((i, wi, ev, ac, th))

    save_csv("03_Коды_событий_по_страницам.csv", page_event_rows)
    newspaper_rows = []
    for title, d in sorted(newspaper.items(), key=lambda x: -x[1]["pages"]):
        newspaper_rows.append({"газета": title, "страниц": d["pages"], "выпусков": len(d["issues"]), "слов": d["words"], "страниц_с_событиями": sum(d["events"].values()), **{EVENTS[c][0]: d["events"][c] for c in EVENTS}})
    save_csv("04_Состав_корпуса_по_газетам.csv", newspaper_rows)
    year_rows = []
    for year, d in sorted(yearly.items()):
        year_rows.append({"год": year, "страниц": d["pages"], "слов": d["words"], **{EVENTS[c][0]: d["events"][c] for c in EVENTS}})
    save_csv("05_Частоты_событий_по_годам.csv", year_rows)

    event_window_counts = Counter()
    actor_window_counts_by_years = {}
    for ecode, (elabel, years, _) in EVENTS.items():
        relevant = [x for x in main_fragments if pages[x[0]]["year"] in years]
        event_ws = [x for x in relevant if x[2][ecode]]
        event_window_counts[ecode] = len(event_ws)
        for acode, (alabel, _) in ACTORS.items():
            co = sum(x[3][acode] for x in event_ws)
            actor_den = sum(x[3][acode] for x in relevant)
            mutual_rows.append({"событие": elabel, "актор": alabel, "окна_события": len(event_ws), "совместных_окон": co, "событие_к_актору_pct": pct(co, len(event_ws)), "актор_к_событию_pct": pct(co, actor_den), "окна_актора_в_периоде": actor_den})
        for tcode, (tlabel, _) in THEMES.items():
            co = sum(x[4][tcode] for x in event_ws)
            theme_rows.append({"событие": elabel, "тема": tlabel, "окна_события": len(event_ws), "совместных_окон": co, "доля_окон_события_pct": pct(co, len(event_ws))})
    save_csv("06_Взаимная_встречаемость_события_и_акторы_окно100.csv", mutual_rows)
    save_csv("07_Встречаемость_события_и_темы_окно100.csv", theme_rows)

    for size in (50, 100, 150, 200):
        overlap = size // 5
        agg = {c: Counter() for c in EVENTS}
        for page in pages:
            for w in windows(page["text"], size, overlap):
                ac_alex = actor_match("alexander", w, ca)
                for code in EVENTS:
                    if event_match(code, w, page["year"], ce, cx):
                        agg[code]["event"] += 1
                        agg[code]["alex"] += int(ac_alex)
        for code, values in agg.items():
            sensitivity_rows.append({"событие": EVENTS[code][0], "окно": size, "окон_события": values["event"], "с_Александром": values["alex"], "доля_с_Александром_pct": pct(values["alex"], values["event"])})
    save_csv("08_Проверка_окон_50_100_150_200.csv", sensitivity_rows)

    codebook = []
    for code, (label, years, pats) in EVENTS.items():
        extra = EVENT_EXTRA.get(code, [])
        codebook.append({"группа": "событие", "код": code, "категория": label, "годы": ", ".join(map(str, years)), "индикаторы": " | ".join(pats), "дополнительное_условие": " | ".join(extra)})
    for code, (label, pats) in ACTORS.items():
        codebook.append({"группа": "актор", "код": code, "категория": label, "годы": "", "индикаторы": " | ".join(pats), "дополнительное_условие": ""})
    for code, (label, pats) in THEMES.items():
        codebook.append({"группа": "тема", "код": code, "категория": label, "годы": "", "индикаторы": " | ".join(pats), "дополнительное_условие": ""})
    save_csv("09_Кодировочная_схема.csv", codebook)

    # Figures
    corpus_note = ("Объединенный корпус: событийный + Александр I / Священный союз"
                   if COMBINED else "Событийный корпус")
    plt.rcParams.update({"font.size": 14, "axes.titlesize": 20, "axes.labelsize": 17,
                         "xtick.labelsize": 17, "ytick.labelsize": 17,
                         "legend.fontsize": 14, "figure.titlesize": 20})
    event_labels = [EVENTS[c][0] for c in EVENTS]
    page_freq = [sum(r[c] for r in page_event_rows) for c in EVENTS]
    plt.figure(figsize=(16, 10)); order = np.argsort(page_freq)
    plt.barh([event_labels[i] for i in order], [page_freq[i] for i in order], color="#446b9e")
    plt.xlabel("Число газетных страниц"); plt.title(f"Присутствие событий\n{corpus_note}", pad=16); plt.tight_layout(); plt.savefig(OUT / "10_Частоты_событий.png", dpi=250); plt.close()

    mdf = pd.DataFrame(mutual_rows)
    pivot = mdf.pivot(index="событие", columns="актор", values="событие_к_актору_pct").reindex(event_labels)
    plt.figure(figsize=(17, 11)); im = plt.imshow(pivot.values, aspect="auto", cmap="YlGnBu", vmin=0, vmax=max(1, np.nanmax(pivot.values)))
    plt.xticks(range(len(pivot.columns)), pivot.columns, rotation=35, ha="right"); plt.yticks(range(len(pivot.index)), pivot.index)
    cb = plt.colorbar(im); cb.set_label("Доля окон события, %", fontsize=19); cb.ax.tick_params(labelsize=17); plt.title(f"Акторы в контекстах исторических событий (окно 100 слов)\n{corpus_note}", pad=16); plt.tight_layout(); plt.savefig(OUT / "11_Акторы_в_контекстах_событий.png", dpi=250); plt.close()

    tdf = pd.DataFrame(theme_rows)
    tp = tdf.pivot(index="событие", columns="тема", values="доля_окон_события_pct").reindex(event_labels)
    plt.figure(figsize=(18, 11)); im = plt.imshow(tp.values, aspect="auto", cmap="OrRd", vmin=0, vmax=max(1, np.nanmax(tp.values)))
    plt.xticks(range(len(tp.columns)), tp.columns, rotation=35, ha="right"); plt.yticks(range(len(tp.index)), tp.index)
    cb = plt.colorbar(im); cb.set_label("Доля окон события, %", fontsize=19); cb.ax.tick_params(labelsize=17); plt.title(f"Смысловые рамки исторических событий (окно 100 слов)\n{corpus_note}", pad=16); plt.tight_layout(); plt.savefig(OUT / "12_Темы_в_контекстах_событий.png", dpi=250); plt.close()

    sp = pd.DataFrame(sensitivity_rows).pivot(index="событие", columns="окно", values="доля_с_Александром_pct").reindex(event_labels)
    plt.figure(figsize=(17, 10))
    for size in (50, 100, 150, 200): plt.plot(range(len(sp.index)), sp[size], marker="o", label=f"{size} слов")
    plt.xticks(range(len(sp.index)), sp.index, rotation=45, ha="right"); plt.ylabel("Доля контекстов с Александром I, %"); plt.title(f"Устойчивость связи событий с Александром I\n{corpus_note}", pad=16); plt.legend(); plt.tight_layout(); plt.savefig(OUT / "13_Чувствительность_к_размеру_окна.png", dpi=250); plt.close()

    top = newspaper_rows[:20]
    plt.figure(figsize=(17, 11)); plt.barh([x["газета"][:65] for x in reversed(top)], [x["страниц"] for x in reversed(top)], color="#6a8f5b")
    plt.xlabel("Число страниц"); plt.title(f"Крупнейшие газетные подкорпусы\n{corpus_note}", pad=16); plt.tight_layout(); plt.savefig(OUT / "14_Состав_корпуса.png", dpi=250); plt.close()

    manifest = {
        "download_rows_in_database": len(downloads),
        "download_rows_before_cross_corpus_deduplication": len(raw_downloads),
        "duplicate_download_rows_removed": duplicate_download_rows,
        "download_rows_by_database": download_rows_by_db,
        "source_titles_total": len(title_counts),
        "newspaper_pages_analyzed": len(pages),
        "newspaper_titles": len(accepted_titles),
        "issues": len(set(p["issue_ark"] for p in pages)),
        "words": sum(p["words"] for p in pages),
        "fragments_100": len(main_fragments),
        "excluded_pages_non_newspapers": sum(x["страниц_в_базе"] for x in audit_rows if not x["включено"]),
        "excluded_titles": sum(not x["включено"] for x in audit_rows),
        "missing_local_ocr_files": len(missing),
        "ocr_request_errors_by_database": query_errors_by_db,
        "ocr_request_errors_in_state_db": sum(x or 0 for x in query_errors_by_db.values()),
        "deduplication_key": "issue_ark + physical_page_number",
        "databases": [str(x) for x in databases],
        "principal_window": 100,
        "overlap_percent": 20,
        "event_page_frequencies": {EVENTS[c][0]: sum(r[c] for r in page_event_rows) for c in EVENTS},
    }
    (OUT / "00_Манифест_исследования.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
