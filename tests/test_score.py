import json
from pathlib import Path

import yaml

from radar.score import normalize, run, score_item

ROOT = Path(__file__).resolve().parents[1]


def load(config, data):
    cfg = yaml.safe_load((ROOT / "config" / config).read_text(encoding="utf-8"))
    items = json.loads((ROOT / "data" / data).read_text(encoding="utf-8"))
    return cfg, items


def test_normalize_strips_accents():
    assert normalize("Ciudad de México") == "ciudad de mexico"


def test_weights_add_up_to_100():
    for name in ["job_search.yaml", "account_prospecting.yaml"]:
        cfg = yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))
        assert sum(d["max"] for d in cfg["dimensions"]) == 100, name


def test_penalties_push_bad_fits_out():
    cfg, items = load("job_search.yaml", "sample_jobs.json")
    keep, drop = run(cfg, items)
    kept = {r.item["company"] for r in keep}
    assert "ModaNova (fictional)" not in kept
    assert "CloudLedger (fictional)" not in kept


def test_ranking_is_descending():
    cfg, items = load("account_prospecting.yaml", "sample_accounts.json")
    keep, _ = run(cfg, items)
    scores = [r.score for r in keep]
    assert scores == sorted(scores, reverse=True)


def test_score_is_clamped_between_0_and_100():
    cfg, _ = load("job_search.yaml", "sample_jobs.json")
    worst = {"title": "intern", "description": "roas paid media luxury treasury"}
    assert score_item(cfg, worst).score == 0
