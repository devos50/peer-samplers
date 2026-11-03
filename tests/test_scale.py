import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from peer_sim import Config, Simulation
from peer_sim.algorithms.basalt import _ranking
from peer_sim.algorithms.common import rank
from peer_sim.metrics import synthetic_ip
from scripts.analyze_scale import analyze, interval
from scripts.scale_experiments import job_key

ROOT = Path(__file__).resolve().parents[1]


class ScaleTests(unittest.TestCase):
    def test_memoized_ranks_match_uncached_hash_reference(self):
        def reference(seed, value):
            return int.from_bytes(hashlib.blake2b(f"{seed}:{value}".encode(), digest_size=16).digest(), "big")
        for seed in (0, 134, 2**100):
            for peer in (0, 1, 255, 1000):
                self.assertEqual(rank(seed, peer), reference(seed, peer))
                self.assertEqual(_ranking(seed, peer, False, 8), (reference(seed, peer),))
                for groups in (1, 2, 8):
                    address = synthetic_ip(peer, groups)
                    self.assertEqual(_ranking(seed, peer, True, groups),
                                     tuple(reference(seed, address[:i]) for i in range(1, 5)))

    def test_student_intervals_and_missing_data(self):
        self.assertIsNone(interval([])["mean"])
        self.assertIsNone(interval([2])["ci95_low"])
        observed = interval([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(observed["mean"], 5.5)
        self.assertAlmostEqual(observed["ci95_high"], 7.665697, places=5)

    def test_parallel_checkpoint_resume_matches_simulation_and_analysis(self):
        cfg = Config(nodes=8, rounds=6, warmup=1, crash_round=3, observation_interval=2)
        jobs = []
        for seed in (1, 2):
            for algorithm in ("cyclon", "newscast"):
                values = cfg.to_dict() | {"seed": seed}
                jobs.append({"tier": "test", "algorithm": algorithm, "config": values})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            job_file = base / "jobs.json"
            job_file.write_text(json.dumps(jobs))
            out = base / "out"
            command = [sys.executable, str(ROOT / "scripts/scale_experiments.py"),
                       "--jobs", str(job_file), "--output", str(out), "--workers", "2"]
            first = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(first.returncode, 0, first.stderr)
            checkpoints = list((out / "runs").glob("*.json.gz"))
            self.assertEqual(len(checkpoints), 4)
            times = {p: p.stat().st_mtime_ns for p in checkpoints}
            manifest_path = out / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["provenance_note"] = "retained metadata"
            manifest_path.write_text(json.dumps(manifest))
            for job in jobs:
                with gzip.open(out / "runs" / f"{job_key(job)}.json.gz", "rt") as stream:
                    saved = json.load(stream)
                expected = json.loads(json.dumps(Simulation(job["algorithm"], Config(**job["config"])).run()))
                self.assertTrue(all(saved[key] == value for key, value in expected.items()))
            second = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("4/4 cached", second.stdout)
            self.assertEqual(json.loads(manifest_path.read_text())["provenance_note"], "retained metadata")
            self.assertEqual(times, {p: p.stat().st_mtime_ns for p in checkpoints})
            result = analyze(out, reports=True)
            self.assertEqual(result["completed"], 4)
            self.assertEqual(len(result["summary"]), 2)
            self.assertTrue((out / "test/report.html").exists())
            pairs = result["paired_comparisons"]
            self.assertTrue(all(pair["n"] == 2 for pair in pairs))
            changed = json.loads(job_file.read_text())
            changed[0]["config"]["nodes"] = 9
            job_file.write_text(json.dumps(changed))
            rejected = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("different implementation or job manifest", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
