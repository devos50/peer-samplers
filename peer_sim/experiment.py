"""Experiment matrices and seed-level uncertainty; all raw runs remain available."""
from collections import defaultdict
from dataclasses import replace
import math
import statistics

from .engine import Simulation
from .workload import make_workload


PROTOCOL_FIELDS = {"view_size", "exchange_size", "active_size", "walk_length",
                   "lease_rounds", "scamp_c", "peerswap_rate", "basalt_refresh"}


def recovery_rounds(run):
    cfg = run["config"]
    if cfg["scenario"] not in ("crash", "mixed") or not cfg["crash_fraction"]:
        return None
    for row in run["timeseries"]:
        if row["time"] < cfg["crash_round"]:
            continue
        rate = row["samples"]["live_sample_rate"]
        # First observed point meeting all three criteria; not an exact recovery time.
        if (row["largest_strong_component_fraction"] >= .95 and
                row["dead_view_fraction"] <= .05 and rate is not None and rate >= .95):
            return row["time"] - cfg["crash_round"]
    return None


def run_experiments(config, algorithms, scenarios, seeds, overrides=None, progress=None):
    overrides = overrides or {}
    for name, values in overrides.items():
        invalid = set(values) - PROTOCOL_FIELDS
        if invalid:
            raise ValueError(f"{name}: per-algorithm overrides must be protocol parameters; invalid: {sorted(invalid)}")
    results = []
    for scenario in scenarios:
        for seed in seeds:
            shared = replace(config, seed=seed, scenario=scenario)
            workload = make_workload(shared)
            for algorithm in algorithms:
                configured = replace(shared, **overrides.get(algorithm, {}))
                if progress:
                    progress(algorithm, scenario, seed)
                result = Simulation(algorithm, configured, workload).run()
                result["recovery_rounds"] = recovery_rounds(result)
                results.append(result)
    return results


def summarize(results):
    groups = defaultdict(list)
    for result in results:
        groups[result["config"]["scenario"], result["algorithm"]].append(result)
    summaries = []
    for (scenario, algorithm), runs in sorted(groups.items()):
        row = {"scenario": scenario, "algorithm": algorithm, "runs": len(runs)}
        metrics = {
            "global_tv": lambda r: r["samples"]["global_tv"],
            "iid_global_tv": lambda r: r["samples"]["iid_global_tv"],
            "mean_local_tv": lambda r: r["samples"]["mean_local_tv"],
            "iid_mean_local_tv": lambda r: r["samples"]["iid_mean_local_tv"],
            "local_tv_excess_over_iid": lambda r: r["samples"]["local_tv_excess_over_iid"],
            "mean_local_intended_tv": lambda r: r["samples"]["mean_local_intended_tv"],
            "live_sample_rate": lambda r: r["samples"]["live_sample_rate"],
            "bytes_per_live_node_round": lambda r: r["bytes_per_live_node_round"],
            "messages_per_live_node_round": lambda r: r["messages_per_live_node_round"],
            "bytes_per_live_sample": lambda r: r["bytes_per_live_sample"],
            "p95_latency_rounds": lambda r: r["samples"]["p95_latency_rounds"],
            "final_strong_component": lambda r: r["final_overlay"]["largest_strong_component_fraction"],
            "final_dead_view_fraction": lambda r: r["final_overlay"]["dead_view_fraction"],
            "recovery_rounds": lambda r: r["recovery_rounds"] if "recovery_rounds" in r else recovery_rounds(r),
        }
        for name, get in metrics.items():
            values = [get(r) for r in runs if get(r) is not None]
            row[name] = statistics.fmean(values) if values else None
            row[name + "_n"] = len(values)
            row[name + "_ci95"] = (1.96 * statistics.stdev(values) / math.sqrt(len(values))
                                      if len(values) > 1 else None)
        row["recovery_observed_fraction"] = row["recovery_rounds_n"] / len(runs)
        summaries.append(row)
    return summaries
