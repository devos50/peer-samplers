#!/usr/bin/env python3
"""Validate checkpointed experiments and report seed-level and paired uncertainty."""
import argparse
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from peer_sim.report import write_results
from scripts.scale_experiments import job_key


# Two-sided 95% Student t critical values; uncertainty is across independent seeds.
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
       6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
       11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
       16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
       24: 2.064, 29: 2.045, 39: 2.023, 59: 2.001, 119: 1.980}


def interval(values):
    if not values:
        return {"n": 0, "mean": None, "ci95_low": None, "ci95_high": None}
    mean = statistics.fmean(values)
    if len(values) == 1:
        return {"n": 1, "mean": mean, "ci95_low": None, "ci95_high": None}
    df = len(values) - 1
    # Use the closest smaller tabulated df (conservative); normal limit above 119.
    critical = T95[max(k for k in T95 if k <= df)] if df <= 119 else 1.980
    half = critical * statistics.stdev(values) / len(values) ** .5
    return {"n": len(values), "mean": mean, "ci95_low": mean - half, "ci95_high": mean + half}


def run_row(run):
    cfg, sample = run["config"], run["samples"]
    late = [r for r in run["timeseries"] if r["time"] >= cfg["rounds"] * .75]
    return {
        "tier": run["tier"], "nodes": cfg["nodes"], "rounds": cfg["rounds"],
        "scenario": cfg["scenario"], "algorithm": run["algorithm"], "seed": cfg["seed"],
        "workload_digest": run["workload_digest"],
        "global_tv": sample["global_tv"], "iid_global_tv": sample["iid_global_tv"],
        "global_tv_excess_over_iid": run["analysis"]["global_tv_excess_over_iid"],
        "mean_local_tv": sample["mean_local_tv"],
        "iid_mean_local_tv": sample["iid_mean_local_tv"],
        "local_tv_excess_over_iid": sample["local_tv_excess_over_iid"],
        "mean_local_intended_tv": sample["mean_local_intended_tv"],
        "live_sample_rate": sample["live_sample_rate"],
        "late_live_sample_rate": run["analysis"]["late_live_sample_rate"],
        "consecutive_repeat_rate": sample["consecutive_repeat_rate"],
        "bytes_per_live_node_round": run["bytes_per_live_node_round"],
        "messages_per_live_node_round": run["messages_per_live_node_round"],
        "bytes_per_live_sample": run["bytes_per_live_sample"],
        "final_strong_component": run["final_overlay"]["largest_strong_component_fraction"],
        "final_dead_view_fraction": run["final_overlay"]["dead_view_fraction"],
        "final_mean_view_size": run["final_overlay"]["mean_view_size"],
        "final_mean_state_descriptors": run["final_overlay"]["mean_state_descriptors"],
        "mean_late_strong_component": statistics.fmean(r["largest_strong_component_fraction"] for r in late),
        "recovery_rounds": run["recovery_rounds"],
        "requests": sample["requests"], "live_samples": sample["outcomes"]["live"],
    }


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze(directory, partial=False, reports=False):
    manifest = json.loads((directory / "manifest.json").read_text())
    rows, missing, traces = [], [], defaultdict(set)
    tiers = defaultdict(list)
    total_requests = 0
    for job in manifest["jobs"]:
        path = directory / "runs" / f"{job_key(job)}.json.gz"
        if not path.exists():
            missing.append(job)
            continue
        with gzip.open(path, "rt") as stream:
            run = json.load(stream)
        assert run["config"] == job["config"] and run["algorithm"] == job["algorithm"]
        sample = run["samples"]
        assert sum(sample["outcomes"].values()) == sample["requests"]
        assert sum(r["samples"]["requests"] for r in run["timeseries"]) == sample["requests"]
        assert sum(r["samples"]["outcomes"]["live"] for r in run["timeseries"]) == sample["outcomes"]["live"]
        cfg = run["config"]
        traces[run["tier"], cfg["scenario"], cfg["seed"]].add(run["workload_digest"])
        row = run_row(run)
        rows.append(row)
        total_requests += row["requests"]
        if reports:
            tiers[run["tier"]].append(run)
    if missing and not partial:
        raise ValueError(f"{len(missing)} jobs are still missing")
    assert all(len(values) == 1 for values in traces.values()), "algorithms did not share a trace"
    if not rows:
        raise ValueError("no completed runs")
    identity = {"tier", "nodes", "rounds", "scenario", "algorithm", "seed", "workload_digest"}
    metrics = [key for key in rows[0] if key not in identity]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["tier"], row["scenario"], row["algorithm"]].append(row)
    summaries = []
    for (tier, scenario, algorithm), group in sorted(grouped.items()):
        result = {"tier": tier, "nodes": group[0]["nodes"], "rounds": group[0]["rounds"],
                  "scenario": scenario, "algorithm": algorithm, "seeds": len(group)}
        for metric in metrics:
            result[metric] = interval([row[metric] for row in group if row[metric] is not None])
        result["recovery_observed_fraction"] = result["recovery_rounds"]["n"] / len(group)
        summaries.append(result)
    # Pair methods on the same seed, population, scenario, and exact membership trace.
    pairs = []
    pair_metrics = ["global_tv_excess_over_iid", "local_tv_excess_over_iid", "live_sample_rate",
                    "late_live_sample_rate", "bytes_per_live_node_round", "bytes_per_live_sample",
                    "final_strong_component"]
    for tier, scenario in sorted({(r["tier"], r["scenario"]) for r in rows}):
        names = sorted(r["algorithm"] for r in summaries if r["tier"] == tier and r["scenario"] == scenario)
        for i, a in enumerate(names):
            left = {r["seed"]: r for r in grouped[tier, scenario, a]}
            for b in names[i + 1:]:
                right = {r["seed"]: r for r in grouped[tier, scenario, b]}
                for metric in pair_metrics:
                    differences = [left[s][metric] - right[s][metric] for s in sorted(left.keys() & right.keys())
                                   if left[s][metric] is not None and right[s][metric] is not None]
                    larger_is_better = metric in ("live_sample_rate", "late_live_sample_rate", "final_strong_component")
                    improved = [v if larger_is_better else -v for v in differences]
                    pairs.append({"tier": tier, "scenario": scenario, "a": a, "b": b,
                                  "metric": metric, "difference": "a minus b", **interval(differences),
                                  "a_wins": sum(v > 1e-12 for v in improved),
                                  "ties": sum(abs(v) <= 1e-12 for v in improved),
                                  "b_wins": sum(v < -1e-12 for v in improved)})
    output = {"schema_version": 1, "implementation_sha256": manifest["implementation_sha256"],
              "completed": len(rows), "planned": len(manifest["jobs"]), "total_requests": total_requests,
              "ci_method": "two-sided Student t 95% intervals across seeds; paired differences use matching trace/seed; no multiplicity correction",
              "summary": summaries, "paired_comparisons": pairs}
    (directory / "analysis.json").write_text(json.dumps(output, indent=2) + "\n")
    write_csv(directory / "run_metrics.csv", rows)
    write_csv(directory / "paired_comparisons.csv", pairs)
    flat = []
    for row in summaries:
        record = {key: value for key, value in row.items() if key not in metrics}
        for metric in metrics:
            for field, value in row[metric].items():
                record[f"{metric}_{field}"] = value
        flat.append(record)
    write_csv(directory / "summary.csv", flat)
    for tier, runs in tiers.items():
        # The existing browser report expects flat means/half-widths. Feed it the
        # t intervals above rather than silently reverting to its normal intervals.
        report_summary = []
        for row in summaries:
            if row["tier"] != tier:
                continue
            record = {"scenario": row["scenario"], "algorithm": row["algorithm"], "runs": row["seeds"]}
            for metric in metrics:
                value = row[metric]
                record[metric] = value["mean"]
                record[metric + "_n"] = value["n"]
                record[metric + "_ci95"] = ((value["ci95_high"] - value["ci95_low"]) / 2
                                              if value["ci95_low"] is not None else None)
            record["recovery_observed_fraction"] = row["recovery_observed_fraction"]
            report_summary.append(record)
        destination = directory / tier
        write_results(destination, runs, report_summary)
        report = destination / "report.html"
        report.write_text(report.read_text().replace("approximate normal 95% confidence", "Student t 95% confidence"))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--reports", action="store_true")
    args = parser.parse_args(argv)
    output = analyze(args.directory, args.partial, args.reports)
    print(f"Validated {output['completed']}/{output['planned']} runs; {output['total_requests']:,} requests")
    for row in output["summary"]:
        print(row["tier"], row["scenario"], row["algorithm"],
              f"n={row['seeds']}", f"live={row['live_sample_rate']['mean']:.4f}",
              f"late={row['late_live_sample_rate']['mean']:.4f}",
              f"local_excess={row['local_tv_excess_over_iid']['mean']:.4f}",
              f"bytes={row['bytes_per_live_node_round']['mean']:.1f}")


if __name__ == "__main__":
    main()
