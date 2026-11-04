#!/usr/bin/env python3
"""Run resumable process-parallel experiment jobs, preserving each raw result.

Job file: [{"algorithm": "cyclon", "config": {Config fields...}, "tier": "250-peers"}, ...]
Each job is independent. Protocols and logical message accounting are unchanged.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from peer_sim import Config, Simulation
from peer_sim.experiment import recovery_rounds
from peer_sim.workload import make_workload


def implementation_digest():
    digest = hashlib.sha256()
    for path in sorted((ROOT / "peer_sim").rglob("*.py")):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def job_key(job):
    return hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()[:20]


def run_job(job, output):
    key = job_key(job)
    started = time.perf_counter()
    workload = (make_workload(Config(**job["workload_config"]))
                if "workload_config" in job else None)
    result = Simulation(job["algorithm"], Config(**job["config"]), workload).run()
    result["recovery_rounds"] = recovery_rounds(result)
    result["tier"] = job["tier"]
    cfg = result["config"]
    late = [row for row in result["timeseries"] if row["time"] >= cfg["rounds"] * .75]
    requests = sum(row["samples"]["requests"] for row in late)
    live = sum(row["samples"]["outcomes"]["live"] for row in late)
    samples = result["samples"]
    result["analysis"] = {
        "implementation_sha256": implementation_digest(),
        "global_tv_excess_over_iid": (samples["global_tv"] - samples["iid_global_tv"]
                                      if samples["global_tv"] is not None else None),
        "late_live_sample_rate": live / requests if requests else None,
        "late_requests": requests,
        "wall_seconds": time.perf_counter() - started,
        "worker_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    path = Path(output) / "runs" / f"{key}.json.gz"
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(result, stream, separators=(",", ":"), allow_nan=False)
    os.replace(temporary, path)
    return {"key": key, "tier": job["tier"], "algorithm": job["algorithm"],
            "scenario": cfg["scenario"], "seed": cfg["seed"], **result["analysis"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("workers must be positive")
    jobs = json.loads(args.jobs.read_text())
    if not jobs or len({job_key(j) for j in jobs}) != len(jobs):
        parser.error("jobs must be nonempty and unique")
    for job in jobs:
        Config(**job["config"])
        if "workload_config" in job:
            Config(**job["workload_config"])
    output = args.output.resolve()
    (output / "runs").mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "implementation_sha256": implementation_digest(), "jobs": jobs}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if any(previous.get(key) != value for key, value in manifest.items()):
            parser.error("existing output has a different implementation or job manifest; choose a new output directory")
        manifest = previous  # retain explicit provenance for equivalent cached runs
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    pending = [job for job in jobs if not (output / "runs" / f"{job_key(job)}.json.gz").exists()]
    complete = len(jobs) - len(pending)
    print(f"{complete}/{len(jobs)} cached; running {len(pending)} jobs on {args.workers} workers", flush=True)
    failures = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                             max_tasks_per_child=1) as pool:
        futures = {pool.submit(run_job, job, str(output)): job for job in pending}
        for future in as_completed(futures):
            job = futures[future]
            try:
                record = future.result()
            except Exception as exc:
                failures.append({"job": job, "error": repr(exc)})
                print(f"FAILED {job['tier']} {job['algorithm']} {exc!r}", flush=True)
                continue
            complete += 1
            with (output / "progress.jsonl").open("a") as stream:
                stream.write(json.dumps(record) + "\n")
            print(f"{complete}/{len(jobs)} {record['tier']} {record['scenario']} "
                  f"seed={record['seed']} {record['algorithm']} {record['wall_seconds']:.1f}s "
                  f"{record['worker_peak_rss_kib']/1024:.0f}MiB", flush=True)
    (output / "status.json").write_text(json.dumps({"completed": complete, "total": len(jobs),
                                                  "failures": failures}, indent=2) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
