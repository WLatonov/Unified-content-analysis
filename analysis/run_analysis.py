from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


PROJECT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def resolve(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def call(script: str, env: dict[str, str], *args: str) -> None:
    command = [sys.executable, str(HERE / script), *args]
    print("\n>", " ".join(command), flush=True)
    subprocess.run(command, cwd=PROJECT, env=env, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Воспроизведение расчетов статьи по двум корпусам Gallica")
    ap.add_argument("--config", default=str(PROJECT / "configs" / "analysis.json"))
    ap.add_argument("--skip-report", action="store_true", help="не создавать черновик Word")
    args = ap.parse_args()

    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    base = config_path.parent
    parser_root = resolve(cfg["parser_root"], base)
    output_root = resolve(cfg.get("output_root", "../outputs/reproduction"), base)
    combined = output_root / "combined"
    composition = output_root / "composition"
    composition_summary = output_root / "composition_summary"
    reclassification = output_root / "reclassification"
    for path in (combined, composition, composition_summary, reclassification):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1",
        "GALLICA_PARSER_ROOT": str(parser_root),
        "GALLICA_EVENT_DB": str(resolve(cfg["event_database"], parser_root)),
        "GALLICA_PERSONALIZED_DB": str(resolve(cfg["personalized_database"], parser_root)),
        "GALLICA_EXTRA_CORPUS": str(resolve(cfg["extra_personalized_corpus"], parser_root)),
        "GALLICA_AUDIT_CSV": str(resolve(cfg.get("newspaper_type_audit", "../data/newspaper_type_audit.csv"), base)),
        "GALLICA_ANALYSIS_OUT": str(combined),
        "GALLICA_COMPOSITION_OUT": str(composition),
        "GALLICA_COMPOSITION_SUMMARY_OUT": str(composition_summary),
        "GALLICA_RECLASSIFICATION_OUT": str(reclassification),
        "GALLICA_SEARCH_ROOT": str(parser_root),
    })

    call("event_content_analysis.py", env, "--combined")
    call("reviewer_robustness_analysis.py", env)
    call("composition_analysis.py", env)
    call("composition_summary.py", env)
    call("reclassify_article_press.py", env)
    call("corpus_comparison_stats.py", env)
    if not args.skip_report:
        call("build_event_content_report.py", env, "--combined")
    print(f"\nГотово. Результаты: {output_root}")


if __name__ == "__main__":
    main()

