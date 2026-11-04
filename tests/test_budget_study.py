"""Independent checks of the matched-budget study's isolation and accounting."""
from contextlib import redirect_stdout
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from peer_sim import Config
from peer_sim.workload import make_workload
from scripts import budget_experiments as study
from scripts.scale_experiments import implementation_digest, job_key, run_job


class BudgetStudyTests(unittest.TestCase):
    def test_checkpoint_runner_uses_fixed_workload_with_different_view_sizes(self):
        base = Config(nodes=14, rounds=9, warmup=2, crash_round=4, scenario="churn",
                      churn=.12, view_size=4, exchange_size=2, active_size=2,
                      observation_interval=2).to_dict()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "runs").mkdir()
            observed = []
            for capacity in (8, 12):
                job = dict(algorithm="cyclon", tier="fixture", workload_config=base,
                           config=base | {"view_size": capacity})
                run_job(job, out)
                with gzip.open(out / "runs" / f"{job_key(job)}.json.gz", "rt") as stream:
                    saved = json.load(stream)
                observed.append(saved["workload_digest"])
                self.assertEqual(saved["config"]["view_size"], capacity)
                self.assertNotEqual(make_workload(Config(**job["config"])).digest,
                                    saved["workload_digest"])
            self.assertEqual(observed, [make_workload(Config(**base)).digest] * 2)
            self.assertEqual(base["view_size"], 4)

    def training_fixture(self, output):
        with redirect_stdout(io.StringIO()):
            study.prepare(output)
        jobs = json.loads((output / "tuning-jobs.json").read_text())
        runs = []
        for job in jobs:
            # Most candidates need the large budget. Three attractive CYCLON
            # alternatives exercise separate traffic, memory, and score criteria.
            cost, descriptors, live, tv = 1000, 20, .8, .25
            if job["candidate"] == "cyclon-00":
                cost, descriptors, live, tv = 100, 4, .9, .2
            elif job["candidate"] == "cyclon-01":
                cost, descriptors, live, tv = 500, 4, 1, 0
            elif job["candidate"] == "cyclon-02":
                cost, descriptors, live, tv = 100, 17, 1, 0
            elif job["candidate"] == "cyclon-03":
                cost, descriptors, live, tv = 100, 4, .9, .1
            run = dict(algorithm=job["algorithm"], config=job["config"],
                       samples=dict(live_sample_rate=live, global_tv=tv),
                       bytes_per_live_node_round=cost,
                       resource_usage=dict(peak_retained_descriptors=descriptors))
            runs.append((job, run))
        return runs

    def freeze_fixture(self, output):
        runs = self.training_fixture(output)
        with patch.object(study, "load_runs", return_value=runs) as loader:
            with redirect_stdout(io.StringIO()):
                study.select(output)
        self.assertEqual(loader.call_args.args[0], output / "tuning")
        return json.loads((output / "selection.json").read_text())

    def test_selection_rejects_overbudget_candidates_and_freezes_test_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            frozen = self.freeze_fixture(output)
            choices = {(c["budget"], c["algorithm"]): c for c in frozen["selected"]}
            small = choices["small", "cyclon"]
            self.assertEqual(small["candidate"], "cyclon-03")
            self.assertTrue(small["training_feasible"])
            self.assertFalse(choices["small", "hyparview"]["training_feasible"])
            scores = {row["candidate"]: row for row in frozen["scores"]}
            self.assertLess(scores["cyclon-01"]["score"], small["score"])
            self.assertLess(scores["cyclon-02"]["score"], small["score"])
            self.assertLess(scores["cyclon-01"]["max_bytes"], 512)
            self.assertGreater(scores["cyclon-01"]["max_bytes"], 512 * .85)
            jobs = json.loads((output / "evaluation-jobs.json").read_text())
            self.assertEqual(len(jobs), 600)
            for job in jobs:
                choice = choices[job["budget"], job["algorithm"]]
                self.assertEqual(job["candidate"], choice["candidate"])
                self.assertTrue(all(job["config"][k] == v
                                    for k, v in choice["parameters"].items()))
                self.assertIn(job["config"]["seed"], study.EVALUATION_SEEDS)
                self.assertNotIn(job["config"]["seed"], study.TUNING_SEEDS)
                self.assertEqual(job["workload_config"]["view_size"], 4)

    def test_selection_rejects_heldout_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            runs = self.training_fixture(output)
            runs[0][1]["config"]["seed"] = study.EVALUATION_SEEDS[0]
            with patch.object(study, "load_runs", return_value=runs):
                with self.assertRaisesRegex(ValueError, "Non-training"):
                    study.select(output)
            self.assertFalse((output / "selection.json").exists())

    def evaluation_fixture(self, output):
        self.freeze_fixture(output)
        jobs = json.loads((output / "evaluation-jobs.json").read_text())
        runs = []
        for job in jobs:
            run = dict(algorithm=job["algorithm"], config=deepcopy(job["config"]),
                workload_digest=f"{job['config']['nodes']}:{job['config']['scenario']}:{job['config']['seed']}",
                samples=dict(requests=10, live_sample_rate=.9, global_tv=.1,
                             local_tv_excess_over_iid=.05),
                bytes_per_live_node_round=100, bytes_per_live_sample=111,
                recovery_rounds=None,
                analysis=dict(global_tv_excess_over_iid=.08, late_live_sample_rate=.9),
                resource_usage=dict(peak_retained_descriptors=8, mean_retained_descriptors=7),
                final_overlay=dict(largest_strong_component_fraction=1, dead_view_fraction=0),
                measured_traffic_by_kind={"rpc:repair_attach": {"bytes": 25},
                                          "reply:repair_attach": {"bytes": 15}},
                live_node_rounds=10)
            runs.append((job, run))
        return runs

    def test_analysis_rejects_configuration_changed_after_tuning(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            runs = self.evaluation_fixture(output)
            runs[0][1]["config"]["view_size"] += 1
            with patch.object(study, "load_runs", return_value=runs):
                with self.assertRaisesRegex(ValueError, "frozen parameters"):
                    study.analyze(output)
            self.assertFalse((output / "analysis.json").exists())

    def test_one_heldout_violation_invalidates_group_and_paired_matched_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            runs = self.evaluation_fixture(output)
            for job, run in runs:
                if (job["budget"] == "small" and job["algorithm"] == "cyclon"
                        and run["config"]["nodes"] == 250
                        and run["config"]["scenario"] == "churn"
                        and run["config"]["seed"] == 301):
                    run["bytes_per_live_node_round"] = 513
            with patch.object(study, "load_runs", return_value=runs):
                with redirect_stdout(io.StringIO()):
                    study.analyze(output)
            result = json.loads((output / "analysis.json").read_text())
            row = next(r for r in result["summary"] if r["budget"] == "small"
                       and r["algorithm"] == "cyclon" and r["nodes"] == 250
                       and r["scenario"] == "churn")
            self.assertFalse(row["matched_budget"])
            self.assertEqual(row["violation_count"], 1)
            self.assertEqual(row["max_bytes"], 513)
            self.assertEqual(row["repair_bytes_per_live_node_round"]["mean"], 4)
            pairs = [p for p in result["paired_comparisons"] if p["budget"] == "small"
                     and p["nodes"] == 250 and p["scenario"] == "churn"
                     and "cyclon" in (p["algorithm_a"], p["algorithm_b"])]
            self.assertTrue(pairs)
            self.assertTrue(all(not p["matched_budget"] for p in pairs))

    def test_loader_rejects_incomplete_planned_matrix_before_reading_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            job = study.make_job(study.candidates()[0], 160, 160, 201, "static", "tuning")
            (directory / "manifest.json").write_text(json.dumps({
                "implementation_sha256": implementation_digest(), "jobs": []}))
            with self.assertRaises(ValueError):
                study.load_runs(directory, expected_jobs=[job])


if __name__ == "__main__":
    unittest.main()
