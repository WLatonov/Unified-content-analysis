from pathlib import Path
import json
import os
import pandas as pd

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
SRC = Path(os.environ.get("GALLICA_COMPOSITION_OUT", PROJECT / "outputs" / "composition"))
OUT = Path(os.environ.get("GALLICA_COMPOSITION_SUMMARY_OUT", PROJECT / "outputs" / "composition_summary"))
OUT.mkdir(exist_ok=True)


def weighted_summary(path: Path, group_col: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    congress = df[df["событие"].isin(["holy_alliance", "aachen", "troppau", "laibach", "verona"])].copy()
    out = congress.groupby(group_col, as_index=False).agg(
        окон_событий=("окон_события", "sum"),
        окон_с_Александром=("окон_с_Александром", "sum"),
    )
    out["доля_pct"] = (100 * out["окон_с_Александром"] / out["окон_событий"]).round(2)
    return out.sort_values("окон_событий", ascending=False)


def main():
    classes = pd.read_csv(SRC / "01_Классификация_78_газет.csv")
    classes.to_csv(OUT / "01_Классификация_газет_для_аудита.csv", index=False, encoding="utf-8-sig")

    summary = json.loads((SRC / "08_Итоги_состава.json").read_text(encoding="utf-8"))
    total = summary["pages"]
    orient = pd.DataFrame([
        {"группа": k, "страниц": v, "доля_pct": round(100*v/total, 2)}
        for k, v in summary["orientation_pages"].items()
    ])
    genre = pd.DataFrame([
        {"группа": k, "страниц": v, "доля_pct": round(100*v/total, 2)}
        for k, v in summary["genre_pages"].items()
    ])
    orient.to_csv(OUT / "02_Итоговый_состав_по_ориентации.csv", index=False, encoding="utf-8-sig")
    genre.to_csv(OUT / "03_Итоговый_состав_по_жанрам.csv", index=False, encoding="utf-8-sig")

    by_year_o = pd.read_csv(SRC / "02_Состав_по_годам_и_ориентации.csv")
    by_year_g = pd.read_csv(SRC / "03_Состав_по_годам_и_жанрам.csv")
    years = sorted(set(by_year_o["год"]))
    year_rows = []
    for year in years:
        oy = by_year_o[by_year_o["год"] == year]
        gy = by_year_g[by_year_g["год"] == year]
        pages = int(oy["страниц"].sum())
        year_rows.append({
            "год": year,
            "страниц": pages,
            "доля_корпуса_pct": round(100*pages/total, 2),
            "доля_консервативных_pct": float(oy.loc[oy["политическая_ориентация"] == "консервативная/роялистская", "доля_страниц_года_pct"].sum()),
            "доля_либеральных_pct": float(oy.loc[oy["политическая_ориентация"] == "либеральная/оппозиционная", "доля_страниц_года_pct"].sum()),
            "доля_столичных_pct": float(gy.loc[gy["жанровая_группа"] == "общеполитическая столичная газета", "доля_страниц_года_pct"].sum()),
            "доля_региональных_политических_pct": float(gy.loc[gy["жанровая_группа"] == "региональная общественно-политическая газета", "доля_страниц_года_pct"].sum()),
        })
    pd.DataFrame(year_rows).to_csv(OUT / "04_Изменение_состава_по_годам.csv", index=False, encoding="utf-8-sig")

    wo = weighted_summary(SRC / "04_Событие_Александр_по_ориентации.csv", "группа")
    wg = weighted_summary(SRC / "05_Событие_Александр_по_жанрам.csv", "группа")
    wo.to_csv(OUT / "05_Конгрессы_и_Александр_по_ориентации.csv", index=False, encoding="utf-8-sig")
    wg.to_csv(OUT / "06_Конгрессы_и_Александр_по_жанрам.csv", index=False, encoding="utf-8-sig")

    title = pd.read_csv(SRC / "07_Событие_Александр_по_газетам.csv")
    rows = []
    for event, g in title.groupby("событие"):
        pooled = 100*g["окон_с_Александром"].sum()/g["окон_события"].sum()
        eligible = g[g["окон_события"] >= 5]
        macro = eligible["доля_pct"].mean() if len(eligible) else float("nan")
        rows.append({
            "событие": event,
            "взвешенная_доля_pct": round(pooled, 2),
            "равный_вес_газет_pct": round(macro, 2),
            "разница_pp": round(macro-pooled, 2),
            "газет_с_не_менее_5_окнами": len(eligible),
        })
    pd.DataFrame(rows).to_csv(OUT / "07_Чувствительность_к_объему_газет.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
