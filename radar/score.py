"""Opportunity Radar scoring engine.

Scores a list of opportunities (job openings, target accounts, partners...)
against a weighted, human-readable config, applies penalty filters,
drops anything below the threshold and returns a ranked shortlist.

Usage:
    python -m radar.score --config config/job_search.yaml --data data/sample_jobs.json
    python -m radar.score --config config/account_prospecting.yaml --data data/sample_accounts.json --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def normalize(text: str) -> str:
    """Lowercase and strip accents so 'Méx' matches 'mex'."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


@dataclass
class Result:
    item: dict
    score: int
    breakdown: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.item.get("name") or f"{self.item.get('title', '')} @ {self.item.get('company', '')}"


def item_text(item: dict, fields: list[str]) -> str:
    return normalize(" ".join(str(item.get(f, "")) for f in fields))


def score_keyword_dimension(dim: dict, item: dict) -> tuple[int, str]:
    """Best matching rule wins (rules are checked top-down, highest points first)."""
    text = item_text(item, dim.get("fields", ["title", "description"]))
    best_points, best_label = dim.get("default", 0), "no match"
    for rule in dim["rules"]:
        if any(normalize(k) in text for k in rule["any"]):
            if rule["points"] > best_points:
                best_points, best_label = rule["points"], rule.get("label", rule["any"][0])
    return min(best_points, dim["max"]), best_label


def score_number_dimension(dim: dict, item: dict) -> tuple[int, str]:
    """Numeric field vs. a floor, e.g. salary or fleet size."""
    value = item.get(dim["field"])
    if value in (None, ""):
        return dim.get("if_missing", 0), "not published"
    value = float(value)
    floor = dim["floor"]
    if value >= floor:
        return dim["max"], f"{value:,.0f} >= {floor:,.0f}"
    if value >= floor * (1 - dim.get("near_floor_pct", 0)):
        return dim.get("near_floor_points", 0), f"{value:,.0f} near floor"
    return 0, f"{value:,.0f} below floor"


def score_item(config: dict, item: dict) -> Result:
    total, breakdown, flags = 0, {}, []
    for dim in config["dimensions"]:
        kind = dim.get("type", "keywords")
        if kind == "keywords":
            pts, why = score_keyword_dimension(dim, item)
        elif kind == "number":
            pts, why = score_number_dimension(dim, item)
        else:
            raise ValueError(f"Unknown dimension type: {kind}")
        breakdown[dim["name"]] = (pts, dim["max"], why)
        total += pts

    for pen in config.get("penalties", []):
        text = item_text(item, pen.get("fields", ["title", "description"]))
        if any(normalize(k) in text for k in pen["any"]):
            total += pen["points"]  # negative number
            flags.append(f"{pen['label']} ({pen['points']})")

    return Result(item=item, score=max(0, min(100, total)), breakdown=breakdown, flags=flags)


def run(config: dict, items: list[dict]) -> tuple[list[Result], list[Result]]:
    threshold = config.get("threshold", 50)
    results = sorted((score_item(config, i) for i in items), key=lambda r: r.score, reverse=True)
    keep = [r for r in results if r.score >= threshold]
    drop = [r for r in results if r.score < threshold]
    return keep, drop


def digest(config: dict, keep: list[Result], drop: list[Result]) -> str:
    lines = [f"# {config.get('title', 'Opportunity Radar')}", ""]
    lines.append(f"Reviewed {len(keep) + len(drop)} · shortlisted {len(keep)} "
                 f"(threshold {config.get('threshold', 50)})")
    lines.append("")
    for i, r in enumerate(keep, 1):
        lines.append(f"## {i}. {r.name} — {r.score}/100")
        for name, (pts, mx, why) in r.breakdown.items():
            lines.append(f"- {name}: {pts}/{mx} ({why})")
        if r.flags:
            lines.append(f"- Risks: {'; '.join(r.flags)}")
        if r.item.get("next_step"):
            lines.append(f"- Next step: {r.item['next_step']}")
        lines.append("")
    if drop:
        lines.append("## Dropped")
        for r in drop:
            reason = f" · {'; '.join(r.flags)}" if r.flags else ""
            lines.append(f"- {r.name} — {r.score}{reason}")
    return "\n".join(lines)


def write_csv(path: Path, keep: list[Result]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "score", "risks"])
        for i, r in enumerate(keep, 1):
            w.writerow([i, r.name, r.score, "; ".join(r.flags)])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score and rank opportunities.")
    p.add_argument("--config", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--csv", help="optional CSV output for the shortlist")
    args = p.parse_args(argv)

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    items = json.loads(Path(args.data).read_text(encoding="utf-8"))
    keep, drop = run(config, items)
    print(digest(config, keep, drop))
    if args.csv:
        write_csv(Path(args.csv), keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
