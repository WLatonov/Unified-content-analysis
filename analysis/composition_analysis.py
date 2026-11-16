from __future__ import annotations

import csv
import json
import re
import sqlite3
import os
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from reviewer_robustness_analysis import (
    ALEX,
    EVENTS,
    EXTRA,
    alex_match,
    any_match,
    event_match,
    norm,
    windows,
)

PROJECT = Path(__file__).resolve().parents[1]
PARSER = Path(os.environ.get("GALLICA_PARSER_ROOT", PROJECT))
ANALYSIS = Path(os.environ.get("GALLICA_ANALYSIS_OUT", PROJECT / "outputs" / "combined"))
OUT = Path(os.environ.get("GALLICA_COMPOSITION_OUT", PROJECT / "outputs" / "composition"))
OUT.mkdir(exist_ok=True)

CONSERVATIVE = {
    "Gazette de France",
    "La Quotidienne",
    "Le Mémorial bordelais : feuille politique et littéraire",
    "Le Drapeau blanc / par A. Martainville et plusieurs hommes de lettres",
    "Journal de Paris",
    "L'Étoile : journal du soir",
    "Journal général de France",
    "La France chrétienne : journal religieux, politique et littéraire",
    "Le Fidèle ami du roi : journal commencé à Gand",
    "Journal royal",
}

LIBERAL = {
    "Le Courrier français",
    "Le Constitutionnel : journal du commerce, politique et littéraire",
    "L'Indépendant : journal général, politique, littéraire et militaire",
    "La Renommée",
    "Le Globe : journal littéraire",
    "Mémorial de l'homme public, ou le Défenseur des libertés françaises / par une réunion de jurisconsultes, de publicistes et d'hommes de lettres",
    "L'Ami de la Charte : journal du Puy-de-Dôme [\"puis\" du Puy-de-Dôme, de la Haute-Loire et du Cantal \"puis\" du Puy-de-Dôme, de la Haute-Loire, du Cantal et de la Corrèze]",
}

OFFICIAL = {
    "Gazette nationale ou le Moniteur universel",
    "Nouvelles officielles",
    "Journal officiel du Gard : politique, administratif et littéraire",
}

MODERATE = {
    "Journal des débats politiques et littéraires",
    "Journal politique et littéraire de Toulouse et de la Haute-Garonne",
}

THEMES = {
    "war": [r"\bguerre\b", r"\bbataille\b", r"\bcombat", r"\barmee?s?\b", r"\btroupes?\b", r"\bsang\b", r"\bmort?s?\b"],
    "peace": [r"\bpaix\b", r"\bpacifi", r"\btranquillite\b", r"\brepos\b", r"\breconciliation\b", r"\bconcorde\b"],
    "order": [r"\bordres?\b", r"\blegitim", r"\btrone\b", r"\bsouverain", r"\brestauration\b", r"\bstabilite\b"],
    "liberty": [r"\bliberte\b", r"\bconstitution", r"\bdroits?\b", r"\bindependance\b", r"\brepresentation\b"],
    "religion": [r"\bchretien", r"\breligion\b", r"\bprovidence\b", r"\bevang", r"\bdivin", r"\bdieu\b", r"\bfraternite\b", r"\bhumanite\b"],
    "intervention": [r"\bintervention\b", r"\bintervenir\b", r"\binvasion\b", r"\boccupation\b", r"\bexpedition\b"],
}


def orientation(title: str) -> tuple[str, str]:
    if title in CONSERVATIVE:
        return "консервативная/роялистская", "классификация по диссертации и истории издания"
    if title in LIBERAL:
        return "либеральная/оппозиционная", "классификация по диссертации и истории издания"
    if title in OFFICIAL:
        return "официальная/правительственная", "официальный статус или прямое указание в заглавии"
    if title in MODERATE:
        return "умеренная", "классификация по диссертации и истории издания"
    return "не классифицирована", "ориентация не устанавливалась только по заглавию"


def genre(title: str) -> str:
    t = title.lower()
    if any(x in t for x in ("affiches", "annonces", "avis divers")):
        return "объявления и коммерческая информация"
    if title in OFFICIAL or any(x in t for x in ("administratif", "officiel", "département")):
        return "официально-административная региональная газета"
    if any(x in t for x in ("spectacles", "arts", "littéraire")) and "politique" not in t and "journal de paris" not in t:
        return "литературно-культурная газета"
    if title in {
        "Gazette nationale ou le Moniteur universel", "Gazette de France", "La Quotidienne",
        "Journal des débats politiques et littéraires", "Le Drapeau blanc / par A. Martainville et plusieurs hommes de lettres",
        "Le Courrier français", "Journal de Paris", "Le Constitutionnel : journal du commerce, politique et littéraire",
        "Journal général de France", "L'Étoile : journal du soir", "Journal du commerce",
    }:
        return "общеполитическая столичная газета"
    if title in {"Niederrheinischer Kurier", "Galignani's messenger", "L'Abeille haytienne", "Journal de la Pointe-à-Pitre"}:
        return "иностранная/колониальная газета"
    return "региональная общественно-политическая газета"


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 2) if d else 0.0


def main() -> None:
    pages = pd.read_csv(ANALYSIS / "03_Коды_событий_по_страницам.csv")
    comp = pd.read_csv(ANALYSIS / "04_Состав_корпуса_по_газетам.csv")
    title_col = "газета"
    classes = []
    for _, row in comp.iterrows():
        o, basis = orientation(row[title_col])
        classes.append({
            "газета": row[title_col], "страниц": int(row["страниц"]), "выпусков": int(row["выпусков"]),
            "политическая_ориентация": o, "основание_ориентации": basis, "жанровая_группа": genre(row[title_col]),
        })
    class_df = pd.DataFrame(classes)
    class_df.to_csv(OUT / "01_Классификация_78_газет.csv", index=False, encoding="utf-8-sig")
    pages = pages.merge(class_df[["газета", "политическая_ориентация", "жанровая_группа"]], on="газета", how="left")

    year_rows = []
    for (year, o), g in pages.groupby(["year", "политическая_ориентация"], dropna=False):
        year_rows.append({"год": int(year), "политическая_ориентация": o, "страниц": len(g), "доля_страниц_года_pct": pct(len(g), len(pages[pages.year == year]))})
    pd.DataFrame(year_rows).to_csv(OUT / "02_Состав_по_годам_и_ориентации.csv", index=False, encoding="utf-8-sig")
    genre_rows = []
    for (year, gr), g in pages.groupby(["year", "жанровая_группа"], dropna=False):
        genre_rows.append({"год": int(year), "жанровая_группа": gr, "страниц": len(g), "доля_страниц_года_pct": pct(len(g), len(pages[pages.year == year]))})
    pd.DataFrame(genre_rows).to_csv(OUT / "03_Состав_по_годам_и_жанрам.csv", index=False, encoding="utf-8-sig")

    mapping = {}
    for dbname in ("state_events_alexander_policy_1812_1822.sqlite3", "state_all_newspapers_1812_1825.sqlite3"):
        db = PARSER / dbname
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
        for ark, page, folder in con.execute("SELECT issue_ark,page_number,output_path FROM downloads"):
            mapping.setdefault((str(ark), int(page)), str(folder))
        con.close()
    extra_root = PARSER / "corpus_alexandre_sainte_alliance_1812_1825" / "Journal_de_la_Loz_re"
    for meta in extra_root.rglob("*_metadata.json") if extra_root.exists() else []:
        try:
            m = json.loads(meta.read_text(encoding="utf-8-sig"))
            mapping.setdefault((str(m["issue_ark"]).split("/")[-1], int(m["digital_page"])), str(meta.parent))
        except Exception:
            pass

    cev = {k: [re.compile(x) for x in v[1]] for k, v in EVENTS.items()}
    cex = {k: [re.compile(x) for x in v] for k, v in EXTRA.items()}
    calex = [re.compile(x) for x in ALEX]
    cthemes = {k: [re.compile(x) for x in v] for k, v in THEMES.items()}
    orient_stats = defaultdict(Counter)
    genre_stats = defaultdict(Counter)
    theme_orient = defaultdict(Counter)
    event_title = defaultdict(Counter)

    for idx, row in pages.iterrows():
        key = (str(row["issue_ark"]), int(row["page"]))
        folder = mapping.get(key)
        if not folder:
            continue
        txt = Path(folder) / f"page_{int(row['page'])}_ocr_clean.txt"
        if not txt.exists():
            continue
        raw = txt.read_text(encoding="utf-8", errors="replace")
        year = int(row["year"])
        active = [code for code in EVENTS if int(row.get(code, 0)) == 1]
        if not active:
            continue
        for w in windows(raw, 20):
            a = alex_match(w, calex)
            for code in active:
                if not event_match(code, w, year, cev, cex):
                    continue
                for group_name, group_value, target in (
                    ("orientation", row["политическая_ориентация"], orient_stats),
                    ("genre", row["жанровая_группа"], genre_stats),
                ):
                    target[(code, group_value)]["windows"] += 1
                    target[(code, group_value)]["alexander"] += int(a)
                event_title[(code, row["газета"])]["windows"] += 1
                event_title[(code, row["газета"])]["alexander"] += int(a)
                if code in {"holy_alliance", "aachen", "troppau", "laibach", "verona"}:
                    for theme, pats in cthemes.items():
                        theme_orient[(code, row["политическая_ориентация"], theme)]["windows"] += 1
                        theme_orient[(code, row["политическая_ориентация"], theme)]["hits"] += int(any_match(w, pats))

    def stats_df(stats):
        out = []
        for (code, group), c in sorted(stats.items()):
            out.append({"событие": code, "группа": group, "окон_события": c["windows"], "окон_с_Александром": c["alexander"], "доля_pct": pct(c["alexander"], c["windows"])})
        return pd.DataFrame(out)

    stats_df(orient_stats).to_csv(OUT / "04_Событие_Александр_по_ориентации.csv", index=False, encoding="utf-8-sig")
    stats_df(genre_stats).to_csv(OUT / "05_Событие_Александр_по_жанрам.csv", index=False, encoding="utf-8-sig")
    theme_rows = []
    for (code, group, theme), c in sorted(theme_orient.items()):
        theme_rows.append({"событие": code, "ориентация": group, "тема": theme, "окон_события": c["windows"], "окон_с_темой": c["hits"], "доля_pct": pct(c["hits"], c["windows"])})
    pd.DataFrame(theme_rows).to_csv(OUT / "06_Темы_конгрессов_по_ориентации.csv", index=False, encoding="utf-8-sig")

    title_rows = []
    for (code, title), c in sorted(event_title.items()):
        title_rows.append({"событие": code, "газета": title, "окон_события": c["windows"], "окон_с_Александром": c["alexander"], "доля_pct": pct(c["alexander"], c["windows"])})
    pd.DataFrame(title_rows).to_csv(OUT / "07_Событие_Александр_по_газетам.csv", index=False, encoding="utf-8-sig")

    summary = {
        "pages": len(pages),
        "titles": int(pages["газета"].nunique()),
        "orientation_pages": pages.groupby("политическая_ориентация").size().sort_values(ascending=False).to_dict(),
        "genre_pages": pages.groupby("жанровая_группа").size().sort_values(ascending=False).to_dict(),
        "year_pages": pages.groupby("year").size().to_dict(),
    }
    (OUT / "08_Итоги_состава.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
