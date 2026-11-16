from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

from event_content_analysis import AUDIT, DB_FIRST, EXTRA_FIRST_CORPUS, UNKNOWN_NEWSPAPERS


audit_df = pd.read_csv(AUDIT)
known_types = dict(zip(audit_df.newspaper, audit_df.source_type))

con = sqlite3.connect(f"file:{DB_FIRST.as_posix()}?mode=ro&immutable=1", uri=True)
rows = con.execute(
    "SELECT d.issue_ark,d.page_number,d.output_path,c.title,c.publication_date "
    "FROM downloads d JOIN candidates c USING(issue_ark)"
).fetchall()
con.close()

for meta_path in EXTRA_FIRST_CORPUS.rglob("*_metadata.json"):
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        rows.append(
            (
                str(meta["issue_ark"]).split("/")[-1],
                int(meta["digital_page"]),
                str(meta_path.parent),
                str(meta["periodical_title"]),
                str(meta["issue_date"]),
            )
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        pass

unique = {}
for row in rows:
    unique.setdefault((row[0], row[1]), row)

accepted = []
for row in unique.values():
    title = row[3]
    source_type = known_types.get(title)
    if source_type is None:
        source_type = "газета" if title in UNKNOWN_NEWSPAPERS else "исключено"
    if source_type == "газета":
        accepted.append(row)

words = 0
missing = 0
for _, page_no, folder, _, _ in accepted:
    path = Path(folder) / f"page_{page_no}_ocr_clean.txt"
    if not path.exists():
        missing += 1
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    words += len(re.findall(r"\w+", text))

print(f"raw_rows={len(rows)}")
print(f"unique_rows={len(unique)}")
print(f"newspaper_pages={len(accepted)}")
print(f"newspaper_titles={len(set(x[3] for x in accepted))}")
print(f"issues={len(set(x[0] for x in accepted))}")
print(f"words={words}")
print(f"missing={missing}")
