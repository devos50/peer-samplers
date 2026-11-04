#!/usr/bin/env python3
"""Prepare, select, and analyze a reproducible matched-budget PeerSwap study.

Run jobs with scale_experiments.py. Selection uses only tuning checkpoints;
evaluation configurations and seeds are frozen in selection.json before testing.
"""
import argparse
import csv
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from peer_sim import Config
from scripts.analyze_scale import interval
from scripts.scale_experiments import implementation_digest, job_key

ALGORITHMS = ("cyclon", "newscast", "hyparview", "peerswap", "peerswap_repair")
BUDGETS = ({"name": "small", "descriptors": 16, "bytes": 512},
           {"name": "large", "descriptors": 32, "bytes": 2048})
SCENARIOS = ("static", "churn", "crash")
TUNING_SEEDS = (201, 202, 203)
EVALUATION_SEEDS = tuple(range(301, 311))
TRAFFIC_HEADROOM = .85
METRICS = ("live_sample_rate", "global_tv", "global_tv_excess_over_iid",
           "local_tv_excess_over_iid", "bytes_per_live_node_round", "bytes_per_live_sample",
           "late_live_sample_rate", "final_strong_component", "final_dead_view_fraction",
           "peak_retained_descriptors", "mean_retained_descriptors", "recovery_rounds",
           "budget_violation", "repair_bytes_per_live_node_round")


def harness_digest():
    digest = hashlib.sha256()
    for name in ("scripts/budget_experiments.py", "scripts/scale_experiments.py", "scripts/analyze_scale.py"):
        digest.update(name.encode())
        digest.update((ROOT / name).read_bytes())
    return digest.hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, keys)
        writer.writeheader()
        writer.writerows(rows)


def candidates():
    grids = {
        "cyclon": [dict(view_size=v, exchange_size=e, maintenance_interval=t)
                   for v in (4, 8, 16, 32) for e in (2, v) for t in (1, 2)],
        "newscast": [dict(view_size=v, exchange_size=min(4, v), maintenance_interval=t)
                     for v in (4, 8, 16, 32) for t in (1, 2, 4, 8)],
        "hyparview": [dict(active_size=a, view_size=p, exchange_size=e, maintenance_interval=t)
                      for a, p in ((2, 6), (4, 12), (4, 28), (8, 24))
                      for e in (2, 6) for t in (1, 2)],
        "peerswap": [dict(view_size=4, exchange_size=4, peerswap_rate=r, maintenance_interval=t)
                     for r in (.005, .02, .08, .32) for t in (1, 2, 4, 8)],
        "peerswap_repair": [dict(view_size=v, exchange_size=4, peerswap_reserve=p,
                                 peerswap_rate=r, maintenance_interval=t, peerswap_repair_attempts=1)
                            for v, p in ((4, 4), (4, 12), (8, 8), (8, 24))
                            for r in (.01, .05) for t in (1, 2)],
    }
    return [dict(algorithm=a, candidate=f"{a}-{i:02d}", parameters=p)
            for a in ALGORITHMS for i, p in enumerate(grids[a])]


def base_config(nodes, rounds, seed, scenario):
    return Config(nodes=nodes, rounds=rounds, warmup=rounds // 5,
                  crash_round=rounds // 2, seed=seed, scenario=scenario,
                  view_size=4, exchange_size=4, active_size=4,
                  observation_interval=10).to_dict()


def make_job(candidate, nodes, rounds, seed, scenario, phase, budget=None):
    base = base_config(nodes, rounds, seed, scenario)
    return dict(algorithm=candidate["algorithm"], candidate=candidate["candidate"],
                phase=phase, budget=budget,
                tier=f"{phase}-{budget or 'grid'}-{nodes}-peers",
                config=base | candidate["parameters"], workload_config=base)


def prepare(output):
    path = output / "plan.json"
    plan = dict(schema_version=1, algorithms=ALGORITHMS, budgets=BUDGETS,
                candidates=candidates(), tuning_seeds=TUNING_SEEDS,
                evaluation_seeds=EVALUATION_SEEDS, scenarios=SCENARIOS,
                tuning_nodes=160, tuning_rounds=160, evaluation_nodes=[250, 1000],
                evaluation_rounds=400, initial_degree_bound=4,
                selection_score="mean((1 - live_sample_rate) + live_sample_rate * global_tv)",
                selection_ties=["mean_bytes", "candidate"],
                traffic_tuning_fraction=TRAFFIC_HEADROOM,
                feasibility="Every tuning run: all-time peak retained descriptors <= M and measured bytes/live-node-round <= 0.85*B; held-out runs must satisfy M and B",
                memory_scope="Retained membership descriptors; excludes transient RPC, transaction snapshots, control buffers, and runtime overhead",
                source_implementation_sha256=implementation_digest(), harness_sha256=harness_digest())
    if path.exists() and json.loads(path.read_text()) != json.loads(json.dumps(plan)):
        raise ValueError("Existing plan differs; use a new study directory")
    dump(path, plan)
    jobs = [make_job(c, 160, 160, seed, scenario, "tuning") for c in candidates()
            for scenario in SCENARIOS for seed in TUNING_SEEDS]
    dump(output / "tuning-jobs.json", jobs)
    print(f"Prepared {len(jobs)} tuning jobs; 16 configurations per algorithm")


def load_runs(directory, expected_jobs=None):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["implementation_sha256"] != implementation_digest():
        raise ValueError("Run implementation differs from current simulator")
    if expected_jobs is not None and manifest["jobs"] != expected_jobs:
        raise ValueError("Run manifest differs from the complete prespecified job matrix")
    traces = {}
    runs = []
    for job in manifest["jobs"]:
        with gzip.open(directory / "runs" / f"{job_key(job)}.json.gz", "rt") as stream:
            run = json.load(stream)
        cfg = run["config"]
        if cfg != Config(**job["config"]).to_dict() or run["algorithm"] != job["algorithm"]:
            raise ValueError("Checkpoint configuration mismatch")
        if run["analysis"]["implementation_sha256"] != manifest["implementation_sha256"]:
            raise ValueError("Checkpoint implementation mismatch")
        if sum(run["samples"]["outcomes"].values()) != run["samples"]["requests"]:
            raise ValueError("Incomplete request accounting")
        trace_key = (cfg["nodes"], cfg["rounds"], cfg["scenario"], cfg["seed"])
        if trace_key in traces and traces[trace_key] != run["workload_digest"]:
            raise ValueError("Mismatched membership/bootstrap/initial-graph trace")
        traces[trace_key] = run["workload_digest"]
        runs.append((job, run))
    return runs


def select(output):
    plan = json.loads((output / "plan.json").read_text())
    if plan["source_implementation_sha256"] != implementation_digest():
        raise ValueError("Implementation changed after plan freeze")
    if plan["harness_sha256"] != harness_digest():
        raise ValueError("Experiment harness changed after plan freeze")
    groups = {}
    expected = [make_job(c, 160, 160, seed, scenario, "tuning") for c in plan["candidates"]
                for scenario in SCENARIOS for seed in TUNING_SEEDS]
    for job, run in load_runs(output / "tuning", expected):
        if job["phase"] != "tuning" or run["config"]["seed"] not in TUNING_SEEDS:
            raise ValueError("Non-training data entered selection")
        groups.setdefault(job["candidate"], []).append(run)
    scores = []
    for candidate in plan["candidates"]:
        runs = groups[candidate["candidate"]]
        if len(runs) != len(TUNING_SEEDS) * len(SCENARIOS):
            raise ValueError("Missing tuning runs")
        values = []
        for run in runs:
            p = run["samples"]["live_sample_rate"]
            tv = run["samples"]["global_tv"]
            values.append(1 - p + p * (tv if tv is not None else 1))
        row = candidate | dict(score=statistics.fmean(values),
            mean_live=statistics.fmean(r["samples"]["live_sample_rate"] for r in runs),
            mean_bytes=statistics.fmean(r["bytes_per_live_node_round"] for r in runs),
            max_bytes=max(r["bytes_per_live_node_round"] for r in runs),
            peak_descriptors=max(r["resource_usage"]["peak_retained_descriptors"] for r in runs))
        scores.append(row)
    selected = []
    for budget in BUDGETS:
        for algorithm in ALGORITHMS:
            rows = [r for r in scores if r["algorithm"] == algorithm]
            eligible = [r for r in rows if r["max_bytes"] <= TRAFFIC_HEADROOM * budget["bytes"] and
                        r["peak_descriptors"] <= budget["descriptors"]]
            # Preserve a diagnostic configuration when none fits; never label it matched.
            diagnostic = sorted(rows, key=lambda r: (max(r["max_bytes"] / budget["bytes"],
                r["peak_descriptors"] / budget["descriptors"]), r["score"], r["candidate"]))
            chosen = min(eligible, key=lambda r: (r["score"], r["mean_bytes"], r["candidate"])) if eligible else diagnostic[0]
            selected.append(chosen | dict(budget=budget["name"], training_feasible=bool(eligible),
                                          feasible_candidates=len(eligible)))
    for row in scores:
        others = [r for r in scores if r["algorithm"] == row["algorithm"] and r != row]
        keys = ("score", "max_bytes", "peak_descriptors")
        row["pareto_frontier"] = not any(all(r[k] <= row[k] for k in keys) and
            any(r[k] < row[k] for k in keys) for r in others)
    selection = dict(plan_sha256=hashlib.sha256((output / "plan.json").read_bytes()).hexdigest(),
                     implementation_sha256=implementation_digest(), selected=selected, scores=scores)
    path = output / "selection.json"
    if path.exists() and json.loads(path.read_text()) != selection:
        raise ValueError("Frozen selection differs")
    dump(path, selection)
    write_csv(output / "tuning-scores.csv", [r | {"parameters": json.dumps(r["parameters"], sort_keys=True)} for r in scores])
    write_csv(output / "selected-configurations.csv", [r | {"parameters": json.dumps(r["parameters"], sort_keys=True)} for r in selected])
    jobs = [make_job(c, nodes, 400, seed, scenario, "evaluation", c["budget"])
            for c in selected for nodes in (250, 1000)
            for scenario in SCENARIOS for seed in EVALUATION_SEEDS]
    dump(output / "evaluation-jobs.json", jobs)
    print(f"Frozen {len(selected)} configurations; prepared {len(jobs)} held-out evaluation jobs")
    for row in selected: print(row["budget"], row["algorithm"], row["candidate"], "feasible", row["training_feasible"],
                              "score", round(row["score"], 4), "max bytes", round(row["max_bytes"], 1), "peak descriptors", row["peak_descriptors"])


def analyze(output):
    selected = json.loads((output / "selection.json").read_text())
    plan = json.loads((output / "plan.json").read_text())
    if selected["plan_sha256"] != hashlib.sha256((output / "plan.json").read_bytes()).hexdigest():
        raise ValueError("Plan modified after selection")
    if selected["implementation_sha256"] != implementation_digest():
        raise ValueError("Implementation modified after selection")
    if plan["harness_sha256"] != harness_digest():
        raise ValueError("Experiment harness modified after plan freeze")
    frozen = {(r["budget"], r["algorithm"]): r for r in selected["selected"]}
    budgets = {b["name"]: b for b in BUDGETS}
    records = []
    total_requests = 0
    expected = [make_job(c, nodes, 400, seed, scenario, "evaluation", c["budget"])
                for c in selected["selected"] for nodes in (250, 1000)
                for scenario in SCENARIOS for seed in EVALUATION_SEEDS]
    for job, run in load_runs(output / "evaluation", expected):
        if job["phase"] != "evaluation" or run["config"]["seed"] not in EVALUATION_SEEDS:
            raise ValueError("Unexpected held-out seed or phase")
        choice = frozen[job["budget"], job["algorithm"]]
        if job["candidate"] != choice["candidate"] or any(run["config"][k] != v for k, v in choice["parameters"].items()):
            raise ValueError("Evaluation differs from frozen parameters")
        b = budgets[job["budget"]]
        traffic_bad = run["bytes_per_live_node_round"] > b["bytes"]
        memory_bad = run["resource_usage"]["peak_retained_descriptors"] > b["descriptors"]
        row = dict(budget=job["budget"], algorithm=job["algorithm"], candidate=job["candidate"],
                   nodes=run["config"]["nodes"], scenario=run["config"]["scenario"], seed=run["config"]["seed"],
                   training_feasible=choice["training_feasible"], traffic_violation=traffic_bad,
                   memory_violation=memory_bad, budget_violation=traffic_bad or memory_bad,
                   workload_digest=run["workload_digest"], requests=run["samples"]["requests"],
                   **{k: run["samples"][k] for k in ("live_sample_rate", "global_tv", "local_tv_excess_over_iid")},
                   **{k: run[k] for k in ("bytes_per_live_node_round", "bytes_per_live_sample", "recovery_rounds")},
                   **{k: run["analysis"][k] for k in ("global_tv_excess_over_iid", "late_live_sample_rate")},
                   **{k: run["resource_usage"][k] for k in ("peak_retained_descriptors", "mean_retained_descriptors")},
                   final_strong_component=run["final_overlay"]["largest_strong_component_fraction"],
                   final_dead_view_fraction=run["final_overlay"]["dead_view_fraction"],
                   repair_bytes_per_live_node_round=sum(v["bytes"] for k, v in run.get("measured_traffic_by_kind", {}).items()
                                                        if "repair" in k) / run["live_node_rounds"])
        records.append(row)
        total_requests += row["requests"]
    groups = {}
    for row in records:
        groups.setdefault((row["budget"], row["nodes"], row["scenario"], row["algorithm"]), []).append(row)
    summary = []
    for (budget, nodes, scenario, algorithm), rows in sorted(groups.items()):
        if len(rows) != len(EVALUATION_SEEDS) or len({r["seed"] for r in rows}) != len(EVALUATION_SEEDS):
            raise ValueError("Incomplete evaluation group")
        summary.append(dict(budget=budget, nodes=nodes, scenario=scenario, algorithm=algorithm,
            runs=len(rows), candidate=rows[0]["candidate"], training_feasible=rows[0]["training_feasible"],
            matched_budget=rows[0]["training_feasible"] and not any(r["budget_violation"] for r in rows),
            violation_count=sum(r["budget_violation"] for r in rows),
            max_bytes=max(r["bytes_per_live_node_round"] for r in rows),
            max_descriptors=max(r["peak_retained_descriptors"] for r in rows),
            recovery_observed_fraction=sum(r["recovery_rounds"] is not None for r in rows) / len(rows),
            **{k: interval([r[k] for r in rows if r[k] is not None]) for k in METRICS}))
    pairs = []
    for budget, nodes, scenario in sorted({k[:3] for k in groups}):
        for a, b in itertools.combinations(ALGORITHMS, 2):
            left = {r["seed"]: r for r in groups[budget, nodes, scenario, a]}
            right = {r["seed"]: r for r in groups[budget, nodes, scenario, b]}
            all_matched = all(r["training_feasible"] and not r["budget_violation"] for r in [*left.values(), *right.values()])
            for metric in METRICS:
                diffs = [left[s][metric] - right[s][metric] for s in EVALUATION_SEEDS
                         if left[s][metric] is not None and right[s][metric] is not None]
                pairs.append(dict(budget=budget, nodes=nodes, scenario=scenario, algorithm_a=a, algorithm_b=b,
                                  metric=metric, matched_budget=all_matched, negative=sum(d < 0 for d in diffs),
                                  ties=sum(d == 0 for d in diffs), positive=sum(d > 0 for d in diffs), **interval(diffs)))
    result = dict(plan=plan, selected=selected["selected"], completed=len(records), total_requests=total_requests,
                  implementation_sha256=implementation_digest(), summary=summary, paired_comparisons=pairs)
    dump(output / "analysis.json", result)
    write_csv(output / "run-metrics.csv", records)
    flat = []
    for row in summary:
        values = {}
        for k, value in row.items():
            if isinstance(value, dict): values.update({f"{k}_{key}": v for key, v in value.items()})
            else: values[k] = value
        flat.append(values)
    write_csv(output / "summary.csv", flat)
    write_csv(output / "paired-comparisons.csv", pairs)
    print(f"Analyzed {len(records)} held-out runs, {total_requests:,} requests, {len(summary)} groups")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "select", "analyze"))
    parser.add_argument("--output", type=Path, default=Path("results/peerswap-budget"))
    args = parser.parse_args()
    {"prepare": prepare, "select": select, "analyze": analyze}[args.action](args.output)


if __name__ == "__main__":
    main()
