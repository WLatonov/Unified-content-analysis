import json
import sqlite3
import os
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
root = Path(os.environ.get("GALLICA_PARSER_ROOT", PROJECT))
audit = pd.read_csv(Path(os.environ.get("GALLICA_AUDIT_CSV", PROJECT / "data" / "newspaper_type_audit.csv")))
types = dict(zip(audit.newspaper, audit.source_type))
unknown_newspapers = {
    "Journal des arts et de la politique",
    "Journal de la Côte-d'Or : feuille politique, littéraire, commerciale et industrielle...",
    "Le Réveil : journal des sciences, de la littérature, des moeurs, théâtres et beaux-arts",
    "Affiches, annonces et avis divers de la ville de Dijon",
    "Affiches, annonces et avis divers de la ville de Metz",
    "Feuille d'annonces du département de la Manche",
    'L\'Ami de la Charte : journal du Puy-de-Dôme ["puis" du Puy-de-Dôme, de la Haute-Loire et du Cantal "puis" du Puy-de-Dôme, de la Haute-Loire, du Cantal et de la Corrèze]',
}


def read_rows(db):
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
    rows = con.execute(
        "SELECT d.issue_ark,d.page_number,c.title,c.publication_date "
        "FROM downloads d JOIN candidates c USING(issue_ark)"
    ).fetchall()
    con.close()
    return rows


def is_newspaper(title):
    return types.get(title) == "газета" or (title not in types and title in unknown_newspapers)


events = read_rows(root / "state_events_alexander_policy_1812_1822.sqlite3")
first = read_rows(root / "state_all_newspapers_1812_1825.sqlite3")
event_keys = {(ark, page) for ark, page, title, _ in events if is_newspaper(title)}
first_keys = {(ark, page) for ark, page, title, _ in first if is_newspaper(title)}
extra_keys = set()
extra_dir = root / "corpus_alexandre_sainte_alliance_1812_1825" / "Journal_de_la_Loz_re"
for path in extra_dir.rglob("*_metadata.json"):
    try:
        meta = json.loads(path.read_text(encoding="utf-8-sig"))
        extra_keys.add((str(meta["issue_ark"]).split("/")[-1], int(meta["digital_page"])))
    except Exception:
        pass

first_all = first_keys | extra_keys
print({
    "event_newspaper_pages": len(event_keys),
    "first_db_newspaper_pages": len(first_keys),
    "extra_lozere_pages": len(extra_keys),
    "first_total_unique_newspaper_pages": len(first_all),
    "overlap_event_first": len(event_keys & first_all),
    "combined_unique_newspaper_pages": len(event_keys | first_all),
    "only_event": len(event_keys - first_all),
    "only_first": len(first_all - event_keys),
})
