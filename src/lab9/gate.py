"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    from lab9.graders import GRADERS

    problems: list[str] = []
    rows = pr.get("rows") or []
    man = pr.get("manifest") or {}
    bman = base.get("manifest") or {}

    # 1. Every reported number is finite. NaN compares False with any threshold, so it "passes".
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (a crashed or dropped grader, not a score)")

    # 2. Row count and (item, seed) coverage: nothing dropped, duplicated or cherry-picked.
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows but manifest says {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    if len(set(keys)) != len(keys):
        dup = sorted({k for k in keys if keys.count(k) > 1})
        problems.append(f"duplicate (item, seed) rows: {dup[:5]}")
    bkeys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != bkeys:
        miss, extra = sorted(bkeys - set(keys)), sorted(set(keys) - bkeys)
        problems.append(f"(item, seed) set differs from baseline: missing {miss[:5]}{'…' if len(miss) > 5 else ''}"
                        f" extra {extra[:5]}{'…' if len(extra) > 5 else ''}")
    if sorted(man.get("seeds") or []) != sorted(bman.get("seeds") or []):
        problems.append(f"seeds {man.get('seeds')} differ from baseline seeds {bman.get('seeds')}")
    if man.get("items") != bman.get("items"):
        problems.append(f"manifest items {man.get('items')} differ from baseline {bman.get('items')}")

    # 3. Graders ran on every row: a crash must not turn into a missing value that leaves the mean.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for m in graded:
        holes = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if r.get(m) is None]
        if holes:
            problems.append(f"metric {m} has no value on {len(holes)} row(s), e.g. {holes[0]}")

    # 4. Reported metrics must be what the rows say (a hand-edited summary is not a measurement).
    if rows and not problems:
        for m in graded:
            vals = [r[m] for r in rows]
            got = sum(map(bool, vals)) if m in ("secret_leak", "approval_bypass") else sum(map(bool, vals)) / len(vals)
            rep = (pr.get("metrics") or {}).get(m)
            if rep is None or abs(float(rep) - got) > 1e-3:
                problems.append(f"metric {m} reported {rep} but rows give {round(got, 4)}")

    # 5. Slice tags come from the label; an item may not leave a slice between baseline and PR.
    btags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows") or []}
    for r in rows:
        iid = r.get("item_id")
        if iid in btags and sorted(r.get("slices") or []) != btags[iid]:
            problems.append(f"{iid} slice tags {sorted(r.get('slices') or [])} differ from baseline {btags[iid]}")
            break

    # 6. Ratchet: on the same eval-set version a threshold may only get stricter.
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Same eval-set version => no threshold may loosen, no metric/slice may vanish or stop blocking."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []                       # a new eval-set version re-baselines; thresholds start over
    out: list[str] = []

    def compare(where: str, old: dict, new: dict | None, th_old: dict, th_new: dict) -> None:
        if new is None:
            out.append(f"ratchet: {where} removed")
            return
        if old.get("blocking") and not new.get("blocking"):
            out.append(f"ratchet: {where} no longer blocking")
        for key in ("min",):
            if key in th_old and (key not in th_new or th_new[key] < th_old[key]):
                out.append(f"ratchet: {where} {key} {th_old[key]} -> {th_new.get(key)}")
        for key in ("max", "max_increase"):
            if key in th_old and (key not in th_new or th_new[key] > th_old[key]):
                out.append(f"ratchet: {where} {key} {th_old[key]} -> {th_new.get(key)}")
        if th_old.get("no_significant_drop") and not th_new.get("no_significant_drop"):
            out.append(f"ratchet: {where} dropped no_significant_drop")

    new_m = {m["id"]: m for m in spec.get("metrics") or []}
    for m in base_spec.get("metrics") or []:
        n = new_m.get(m["id"])
        compare(f"metric {m['id']}", m, n, m.get("threshold") or {}, (n or {}).get("threshold") or {})
    new_s = {(s.get("name"), s.get("metric")): s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        n = new_s.get((s.get("name"), s.get("metric")))
        compare(f"slice {s.get('name')}/{s.get('metric')}", s, n, s, n or {})
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        val = round(sum(a.values()) / len(a), 4) if a else None
        if val is None:
            verdict = "missing"           # an empty slice cannot vouch for anything
        elif "min" in sl and val < sl["min"]:
            verdict = "fail"
        elif "max" in sl and val > sl["max"]:
            verdict = "fail"
        if sl.get("no_significant_drop") and a:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<40} {val!s:<8} {json.dumps(th):<40} {note:<28} {label} ({len(a)} items)")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
