from __future__ import annotations

import csv
import json
import shutil
import os
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from docx import Document


PROJECT = Path(__file__).resolve().parents[1]
COMPOSITION = Path(os.environ.get("GALLICA_COMPOSITION_OUT", PROJECT / "outputs" / "composition"))
CLASS_FILE = next(COMPOSITION.glob("01_*.csv"))
YEAR_FILE = next(COMPOSITION.glob("02_*.csv"))
EVENT_TITLE_FILE = next(COMPOSITION.glob("07_*.csv"))
OUT = Path(os.environ.get("GALLICA_RECLASSIFICATION_OUT", PROJECT / "outputs" / "reclassification"))
ARTICLE_VALUE = os.environ.get("GALLICA_ARTICLE_DOCX", "").strip()
ARTICLE = Path(ARTICLE_VALUE) if ARTICLE_VALUE else None


# Издания, печатавшиеся в Париже. Все остальные материковые/европейские
# региональные газеты относятся к провинциальным; две газеты колоний
# выделены отдельно.
CAPITAL = {
    "Gazette nationale ou le Moniteur universel",
    "Gazette de France",
    "La Quotidienne",
    "Journal des débats politiques et littéraires",
    "Le Drapeau blanc / par A. Martainville et plusieurs hommes de lettres",
    "Le Courrier français",
    "Journal de Paris",
    "Le Constitutionnel : journal du commerce, politique et littéraire",
    "Journal général de France",
    "Le Nain couleur de rose : journal politique, littéraire et moral",
    "L'Étoile : journal du soir",
    "Journal du commerce",
    "Galignani's messenger",
    "Journal de l'Empire",
    "Feuille du jour",
    "Journal royal",
    "Le Télégraphe",
    "La France chrétienne : journal religieux, politique et littéraire",
    "Affiches, annonces et avis divers, ou Journal général de France",
    "Le Nain blanc",
    "Le Globe : journal littéraire",
    "Journal des arts et de la politique",
    "La Renommée",
    "Mémorial de l'homme public, ou le Défenseur des libertés françaises / par une réunion de jurisconsultes, de publicistes et d'hommes de lettres",
    "Le Diable boiteux : journal des spectacles, des moeurs et de la littérature",
    "Le Réveil : journal des sciences, de la littérature, des moeurs, théâtres et beaux-arts",
    "Le Corsaire : journal des spectacles, de la littérature, des arts, des moeurs et des modes",
}

COLONIAL = {
    "Journal de la Pointe-à-Pitre",
    "L'Abeille haytienne",
}


def political(old: str) -> str:
    if old in {"консервативная/роялистская", "официальная/правительственная"}:
        return "консервативная"
    if old == "либеральная/оппозиционная":
        return "либеральная"
    return "умеренная"


def geographic(title: str) -> str:
    if title in COLONIAL:
        return "колониальная"
    if title in CAPITAL:
        return "столичная"
    return "провинциальная"


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 2) if d else 0.0


def fmt(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def replace_paragraph(paragraph, text: str) -> None:
    old_runs = list(paragraph.runs)
    rpr = deepcopy(old_runs[0]._r.rPr) if old_runs and old_runs[0]._r.rPr is not None else None
    for run in old_runs:
        paragraph._p.remove(run._r)
    run = paragraph.add_run(text)
    if rpr is not None:
        run._r.insert(0, rpr)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with CLASS_FILE.open(encoding="utf-8-sig", newline="") as fh:
        classes = list(csv.DictReader(fh))

    by_title = {}
    political_pages = Counter()
    geographic_pages = Counter()
    for row in classes:
        title = row["газета"]
        p = political(row["политическая_ориентация"])
        g = geographic(title)
        pages = int(row["страниц"])
        by_title[title] = (p, g)
        political_pages[p] += pages
        geographic_pages[g] += pages

    total = sum(political_pages.values())
    assert sum(geographic_pages.values()) == total

    with YEAR_FILE.open(encoding="utf-8-sig", newline="") as fh:
        year_rows = list(csv.DictReader(fh))
    liberal_year = {}
    year_total = Counter()
    year_liberal = Counter()
    for row in year_rows:
        y = int(row["год"])
        n = int(row["страниц"])
        year_total[y] += n
        if political(row["политическая_ориентация"]) == "либеральная":
            year_liberal[y] += n
    for y in sorted(year_total):
        liberal_year[y] = pct(year_liberal[y], year_total[y])

    congress_codes = {"holy_alliance", "aachen", "troppau", "laibach", "verona"}
    orientation_windows = Counter()
    orientation_alex = Counter()
    geography_windows = Counter()
    geography_alex = Counter()
    with EVENT_TITLE_FILE.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["событие"] not in congress_codes:
                continue
            p, g = by_title[row["газета"]]
            w = int(row["окон_события"])
            a = int(row["окон_с_Александром"])
            orientation_windows[p] += w
            orientation_alex[p] += a
            geography_windows[g] += w
            geography_alex[g] += a

    p27 = (
        "Из 19 789 страниц объединенного корпуса 4 126 (20,85%) относятся к 1814 г., "
        "6 392 (32,30%) — к 1815 г. Таким образом, эти два года образуют 53,15% корпуса. "
        f"По политической ориентации страницы распределяются между тремя группами: "
        f"консервативные газеты — {fmt(pct(political_pages['консервативная'], total))}%, "
        f"умеренные — {fmt(pct(political_pages['умеренная'], total))}%, "
        f"либеральные — {fmt(pct(political_pages['либеральная'], total))}%. "
        "К консервативным отнесены также официальные правительственные издания; в умеренную группу включены "
        "непартийные административные, информационные и коммерческие газеты, для которых не установлена явно "
        "либеральная или консервативная позиция. Поэтому политическая классификация охватывает весь корпус и не "
        "смешивается с административным статусом или жанром издания. В 1812–1817 гг. либеральные издания в корпусе "
        f"практически отсутствуют, тогда как их доля возрастает с {fmt(liberal_year[1818])}% в 1818 г. "
        f"до {fmt(liberal_year[1825])}% в 1825 г."
    )

    p28 = (
        "По географической принадлежности корпус разделен на столичные, провинциальные и колониальные газеты. "
        f"На столичные издания приходится {fmt(pct(geographic_pages['столичная'], total))}% страниц, "
        f"на провинциальные — {fmt(pct(geographic_pages['провинциальная'], total))}%, "
        f"на колониальные — {fmt(pct(geographic_pages['колониальная'], total))}%. "
        "Столичными считались газеты, выходившие в Париже; провинциальными — материковые региональные и прочие "
        "непарижские европейские издания; колониальными — газеты, издававшиеся во французских и бывших французских "
        "колониях. В совокупности 100-словных окон, связанных с Актом Священного союза и четырьмя конгрессами, "
        f"Александр I встречается в {fmt(pct(orientation_alex['консервативная'], orientation_windows['консервативная']))}% "
        f"окон консервативных газет, {fmt(pct(orientation_alex['умеренная'], orientation_windows['умеренная']))}% "
        f"окон умеренных и {fmt(pct(orientation_alex['либеральная'], orientation_windows['либеральная']))}% окон либеральных газет."
    )

    backup = None
    if ARTICLE is not None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = ARTICLE.with_name(f"article_final_backup_before_reclassification_{stamp}.docx")
        shutil.copy2(ARTICLE, backup)
        doc = Document(ARTICLE)
        replace_paragraph(doc.paragraphs[27], p27)
        replace_paragraph(doc.paragraphs[28], p28)
        doc.save(ARTICLE)

    audit_rows = []
    for row in classes:
        title = row["газета"]
        p, g = by_title[title]
        audit_rows.append({
            "газета": title,
            "страниц": row["страниц"],
            "политическая_ориентация": p,
            "географическая_принадлежность": g,
            "исходная_классификация": row["политическая_ориентация"],
        })
    with (OUT / "Классификация_78_газет_политика_география.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(audit_rows[0]))
        w.writeheader()
        w.writerows(audit_rows)

    summary = {
        "total_pages": total,
        "political_pages": dict(political_pages),
        "political_pct": {k: pct(v, total) for k, v in political_pages.items()},
        "geographic_pages": dict(geographic_pages),
        "geographic_pct": {k: pct(v, total) for k, v in geographic_pages.items()},
        "congress_alexander_orientation": {
            k: {"windows": orientation_windows[k], "with_alexander": orientation_alex[k],
                "pct": pct(orientation_alex[k], orientation_windows[k])}
            for k in sorted(orientation_windows)
        },
        "congress_alexander_geography": {
            k: {"windows": geography_windows[k], "with_alexander": geography_alex[k],
                "pct": pct(geography_alex[k], geography_windows[k])}
            for k in sorted(geography_windows)
        },
        "liberal_share_by_year_pct": liberal_year,
        "article_updated": str(ARTICLE) if ARTICLE else None,
        "backup": str(backup) if backup else None,
    }
    (OUT / "Итоги_пересчета.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
