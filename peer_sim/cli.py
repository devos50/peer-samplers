import argparse
from dataclasses import fields
import importlib
import json
from pathlib import Path
import sys

from . import algorithms  # noqa: F401
from .config import Config
from .experiment import run_experiments, summarize
from .protocol import REGISTRY
from .report import write_results


def comma_values(text, convert=str):
    result = [convert(v.strip()) for v in text.split(",") if v.strip()]
    if not result or len(result) != len(set(result)):
        raise ValueError("lists must be nonempty and contain no duplicates")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare decentralized peer samplers on shared workloads.")
    parser.add_argument("--list", action="store_true", help="list registered algorithms")
    parser.add_argument("--algorithms", default="all", help="comma-separated names, or all")
    parser.add_argument("--scenarios", help="comma-separated static,churn,crash,mixed (default: static,churn,crash)")
    parser.add_argument("--seeds", help="comma-separated integer seeds (default: config seed)")
    parser.add_argument("--config", type=Path, help="JSON object containing Config fields")
    parser.add_argument("--algorithm-config", type=Path, help="JSON mapping algorithm names to protocol parameter overrides")
    parser.add_argument("--plugin", action="append", default=[], help="import a module that registers extra protocols")
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--quiet", action="store_true")
    excluded = {"scenario", "seed"}
    for field in fields(Config):
        if field.name in excluded:
            continue
        parser.add_argument("--" + field.name.replace("_", "-"), type=type(field.default), default=None)
    args = parser.parse_args(argv)
    try:
        for module in args.plugin:
            importlib.import_module(module)
        if args.list:
            print("\n".join(REGISTRY))
            return 0
        values = json.loads(args.config.read_text()) if args.config else {}
        for field in fields(Config):
            if field.name not in excluded and getattr(args, field.name) is not None:
                values[field.name] = getattr(args, field.name)
        if "rounds" in values:
            values.setdefault("warmup", min(20, values["rounds"] // 5))
            values.setdefault("crash_round", values["rounds"] // 2)
        config = Config(**values)
        names = list(REGISTRY) if args.algorithms == "all" else comma_values(args.algorithms)
        unknown = set(names) - REGISTRY.keys()
        if unknown:
            raise ValueError(f"unknown algorithms: {sorted(unknown)}")
        scenarios = comma_values(args.scenarios) if args.scenarios else ([values["scenario"]] if "scenario" in values else ["static", "churn", "crash"])
        seeds = comma_values(args.seeds, int) if args.seeds else [config.seed]
        overrides = json.loads(args.algorithm_config.read_text()) if args.algorithm_config else {}
        if set(overrides) - REGISTRY.keys():
            raise ValueError("algorithm-config contains unregistered algorithm names")
        progress = None if args.quiet else lambda a, s, seed: print(f"{s:7} seed={seed:<5} {a}", file=sys.stderr)
        results = run_experiments(config, names, scenarios, seeds, overrides, progress)
        summary = summarize(results)
        write_results(args.output, results, summary)
        print(f"{'Scenario':<9} {'Algorithm':<22} {'Live %':>8} {'Global TV':>10} {'Local excess':>13} {'Bytes/node/round':>17}")
        for row in summary:
            def fmt(value, digits=3):
                return f"{value:.{digits}f}" if value is not None else "—"
            live = row["live_sample_rate"]
            print(f"{row['scenario']:<9} {row['algorithm']:<22} {fmt(live * 100 if live is not None else None, 1):>8} {fmt(row['global_tv']):>10} {fmt(row['local_tv_excess_over_iid']):>13} {fmt(row['bytes_per_live_node_round'], 1):>17}")
        print(f"Report: {(args.output / 'report.html').resolve()}")
        return 0
    except (ValueError, TypeError, OSError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
