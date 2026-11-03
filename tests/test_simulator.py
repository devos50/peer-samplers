import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from peer_sim import Config, Simulation
from peer_sim import algorithms
from peer_sim.algorithms.brahms import Brahms
from peer_sim.algorithms.common import rank
from peer_sim.algorithms.peerswap import PeerSwap
from peer_sim.engine import Context
from peer_sim.experiment import run_experiments, summarize
from peer_sim.metrics import Samples, hierarchical_weights, overlay_snapshot
from peer_sim.protocol import Protocol, REGISTRY
from peer_sim.report import write_results
from peer_sim.workload import make_workload


def small(**kwargs):
    return Config(**dict({"nodes": 18, "rounds": 14, "warmup": 3,
                          "view_size": 6, "exchange_size": 3, "active_size": 3,
                          "crash_round": 7}, **kwargs))


class EngineTests(unittest.TestCase):
    def test_every_algorithm_reproducible_and_all_requests_accounted(self):
        for name in REGISTRY:
            with self.subTest(name=name):
                cfg = small(scenario="mixed", churn=.08, crash_fraction=.4)
                first = Simulation(name, cfg).run()
                self.assertEqual(first, Simulation(name, cfg).run())
                samples = first["samples"]
                self.assertEqual(samples["requests"], sum(samples["outcomes"].values()))
                self.assertEqual(samples["requests"], sum(r["samples"]["requests"] for r in first["timeseries"]))
                self.assertEqual(samples["outcomes"]["live"], sum(r["samples"]["outcomes"]["live"] for r in first["timeseries"]))
                for row in first["timeseries"]:
                    self.assertEqual(row["samples"]["requests"], sum(row["samples"]["outcomes"].values()))
                traffic = first["measured_traffic"]
                self.assertEqual(traffic["messages_sent"], sum(traffic.get(k + "_messages", 0) for k in ("maintenance", "sampling", "bootstrap")))
                self.assertEqual(traffic["bytes_sent"], sum(traffic.get(k + "_bytes", 0) for k in ("maintenance", "sampling", "bootstrap")))
                self.assertGreater(traffic["bytes_sent"], 0)

    def test_algorithms_share_churn_and_bootstrap_trace(self):
        runs = run_experiments(small(scenario="mixed"), ["cyclon", "hyparview", "peerswap"], ["mixed"], [17])
        self.assertEqual(len({r["workload_digest"] for r in runs}), 1)
        self.assertEqual(len({r["samples"]["requests"] for r in runs}), 1)

    def test_churn_bootstrap_contacts_are_bounded_and_alive(self):
        cfg = small(scenario="mixed", churn=.8, crash_fraction=.8)
        trace = make_workload(cfg)
        live = set(range(cfg.nodes))
        for change in trace.changes:
            live.difference_update(change.leaving)
            for node, peers in change.joining:
                self.assertLessEqual(len(peers), cfg.bootstrap_size)
                self.assertTrue(set(peers) <= live)
                self.assertNotIn(node, live)
                live.add(node)
            self.assertGreater(len(live), 0)

    def test_failed_sends_cost_bytes_and_payloads_are_snapshots(self):
        sim = Simulation("cyclon", small(loss=.5))
        sim.live.update({0, 1})
        class NeverLose:
            def random(self):
                return 1
        sim.network_rng = NeverLose()
        payload = [1, 2]
        sim.send(0, 99, "test", payload)
        payload.append(3)
        self.assertEqual(sim.queue[0][3][3], [1, 2])
        expected = sim.config.header_bytes + len('["test",[1,2]]'.encode())
        self.assertEqual(sim.traffic["bytes_sent"], expected)
        class AlwaysLose:
            def random(self):
                return 0
        sim.network_rng = AlwaysLose()
        sim.send(0, 1, "lost", None)
        self.assertEqual(sim.traffic["messages_sent"], 2)
        self.assertEqual(sim.traffic["messages_lost"], 1)
        self.assertEqual(len(sim.queue), 1)

    def test_context_exposes_no_membership_or_liveness_api(self):
        ctx = Context(Simulation("cyclon", small()), 0)
        self.assertFalse(hasattr(ctx, "live"))
        self.assertFalse(hasattr(ctx, "is_alive"))
        self.assertFalse(hasattr(ctx, "peers"))

    def test_no_sampling_has_null_uniformity_not_perfect_score(self):
        result = Simulation("cyclon", small(samples_per_node=0)).run()
        self.assertIsNone(result["samples"]["global_tv"])
        self.assertIsNone(result["samples"]["live_sample_rate"])
        self.assertIsNone(result["bytes_per_live_sample"])
        json.dumps(result, allow_nan=False)

    def test_timeout_and_loss_are_visible(self):
        result = Simulation("mrwb", small(sample_timeout=.01, loss=.2)).run()
        self.assertGreater(result["samples"]["outcomes"]["timeout"], 0)
        self.assertGreater(result["traffic"]["messages_lost"], 0)
        self.assertGreater(result["measured_traffic"]["sampling_bytes"], 0)

    def test_crash_snapshot_captures_damage_before_repairs(self):
        result = Simulation("hyparview", small(nodes=40, scenario="crash", crash_fraction=.5)).run()
        immediate = next(row for row in result["timeseries"] if row["time"] == 7)
        self.assertEqual(immediate["live_nodes"], 20)
        self.assertGreater(immediate["dead_view_fraction"], .2)

    def test_invalid_configuration(self):
        for overrides in ({"nodes": 1}, {"churn": -1}, {"loss": 1}, {"latency": math.nan},
                          {"timeout": .01}, {"warmup": 14}, {"exchange_size": 99}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                small(**overrides)


class MetricTests(unittest.TestCase):
    def test_self_exclusion_and_membership_changes_in_uniform_target(self):
        metrics = Samples(1)
        # Two epochs, uniform amongst currently-live peers except the requester.
        for p in (1, 2):
            metrics.requests += 1
            metrics.result(0, p, "live", 0, 0, frozenset({0, 1, 2}))
        for _ in range(2):
            metrics.requests += 1
            metrics.result(0, 3, "live", 0, 1, frozenset({0, 3}))
        report = metrics.report()
        self.assertAlmostEqual(report["global_tv"], 0)
        self.assertAlmostEqual(report["mean_local_tv"], 0)

    def test_global_fairness_can_hide_local_bias(self):
        metrics = Samples(123)
        live = frozenset(range(6))
        for _ in range(200):
            for p in range(6):
                metrics.requests += 1
                metrics.result(p, (p + 1) % 6, "live", 0, 0, live)
        result = metrics.report()
        self.assertAlmostEqual(result["global_tv"], 0)
        self.assertAlmostEqual(result["mean_local_tv"], .8)
        self.assertGreater(result["local_tv_excess_over_iid"], .65)

    def test_dead_results_do_not_improve_conditional_uniformity(self):
        metrics = Samples(1)
        metrics.requests = 2
        metrics.result(0, 1, "live", 0, 0, frozenset({0, 1}))
        metrics.result(0, 99, "dead", 0, 0, frozenset({0, 1}))
        report = metrics.report()
        self.assertEqual(report["global_tv"], 0)
        self.assertEqual(report["live_sample_rate"], .5)

    def test_hierarchical_target_is_not_uniform_over_ids(self):
        weights = hierarchical_weights([0, 1, 2, 4, 6], 2)
        self.assertAlmostEqual(sum(weights.values()), 1)
        self.assertAlmostEqual(weights[1], .5)
        self.assertAlmostEqual(weights[0], .125)

    def test_strong_connectivity_is_not_weak_connectivity(self):
        class View:
            def __init__(self, view): self.view = view
            def neighbors(self): return set(self.view)
            def state_size(self): return len(self.view)
        result = overlay_snapshot({0: View([1]), 1: View([2]), 2: View([])}, {0, 1, 2})
        self.assertEqual(result["largest_component_fraction"], 1)
        self.assertAlmostEqual(result["largest_strong_component_fraction"], 1 / 3)


class ProtocolTests(unittest.TestCase):
    def test_cache_bounds_and_self_exclusion_under_churn(self):
        for name in ("cyclon", "newscast", "brahms", "basalt", "basalt_uniform"):
            sim = Simulation(name, small(scenario="mixed", churn=.1))
            sim.run()
            for p in sim.live:
                protocol = sim.protocols[p]
                self.assertNotIn(p, protocol.neighbors())
                self.assertLessEqual(len(protocol.sample_pool()), sim.config.view_size)

    def test_cyclon_contacts_oldest_descriptor(self):
        sim = Simulation("cyclon", small())
        sim.live.update({0, 1, 2, 3})
        protocol = algorithms.Cyclon(Context(sim, 0))
        protocol.view = {1: 1, 2: 100, 3: 5}
        protocol.tick()
        messages = [d for _, _, event, d in sim.queue if event == "message"]
        self.assertEqual(messages[0][1], 2)

    def test_cyclon_does_not_discard_partner_when_reply_has_only_duplicates(self):
        cfg = small(nodes=2, rounds=20)
        sim = Simulation("cyclon", cfg)
        result = sim.run()
        self.assertEqual(result["samples"]["live_sample_rate"], 1)
        self.assertEqual(sim.protocols[0].neighbors(), {1})
        self.assertEqual(sim.protocols[1].neighbors(), {0})

    def test_newscast_retains_freshest_and_deduplicates(self):
        sim = Simulation("newscast", small(view_size=3))
        protocol = algorithms.Newscast(Context(sim, 0))
        protocol.merge([[1, 1], [1, 9], [2, 4], [3, 5], [4, 6], [0, 99]])
        self.assertEqual(protocol.view, {1: 9, 4: 6, 3: 5})

    def test_history_sampling_is_invariant_to_repeated_advertisements(self):
        sim = Simulation("brahms", small())
        protocol = Brahms(Context(sim, 0))
        protocol.observe([1, 2, 3, 4])
        before = protocol.sample_pool()
        protocol.observe([1] * 1000)
        self.assertEqual(protocol.sample_pool(), before)
        for seed, peer in zip(protocol.seeds, protocol.samples):
            self.assertEqual(peer, min([1, 2, 3, 4], key=lambda p: rank(seed, p)))

    def test_basalt_uses_hit_counters_and_refreshes_selected_slot(self):
        sim = Simulation("basalt_uniform", small())
        protocol = algorithms.BasaltUniform(Context(sim, 0))
        protocol.bootstrap([1, 2, 3], True)
        protocol.hits = [100] * 6
        protocol.hits[2] = 0
        self.assertEqual(protocol.select_peer(), protocol.slots[2])
        self.assertEqual(protocol.hits[2], 1)
        seed = protocol.seeds[0]
        peer = protocol.slots[0]
        self.assertEqual(protocol.refresh(), peer)
        self.assertNotEqual(protocol.seeds[0], seed)

    def test_hyparview_active_edges_are_symmetric_and_bounded(self):
        sim = Simulation("hyparview", small(scenario="mixed", churn=.07))
        sim.run()
        for p in sim.live:
            node = sim.protocols[p]
            self.assertLessEqual(len(node.active), sim.config.active_size)
            self.assertLessEqual(len(node.passive), sim.config.view_size)
            self.assertFalse(node.active & node.passive)
            for q in node.active:
                self.assertIn(p, sim.protocols[q].active)

    def test_peerswap_preserves_graph_structure(self):
        for topology in ("random", "ring", "star"):
            sim = Simulation("peerswap", small(topology=topology, rounds=30))
            sim.run()
            before = {p: set(v) for p, v in sim.workload.initial}
            after = {p: sim.protocols[p].neighbors() for p in sim.live}
            self.assertEqual(sorted(map(len, before.values())), sorted(map(len, after.values())))
            def triangles(graph):
                return sum(len(graph[p] & graph[q]) for p in graph for q in graph[p]) // 6
            self.assertEqual(triangles(before), triangles(after))
            for p in after:
                self.assertNotIn(p, after[p])
                for q in after[p]:
                    self.assertIn(p, after[q])
            self.assertGreater(sum(p.completed_swaps for p in sim.protocols.values()), 0)

    def test_metropolis_corrects_star_degree_bias(self):
        cfg = small(nodes=12, rounds=90, warmup=15, topology="star", walk_length=9)
        plain = Simulation("random_walk", cfg).run()
        corrected = Simulation("metropolis_hastings", cfg).run()
        self.assertGreater(plain["samples"]["global_tv"], .6)
        self.assertLess(corrected["samples"]["global_tv"], .15)
        self.assertGreater(corrected["measured_traffic"]["sampling_messages"], 0)

    def test_mrwb_recovers_more_queries_during_churn(self):
        cfg = small(nodes=40, rounds=35, warmup=5, view_size=8, exchange_size=4,
                    scenario="mixed", churn=.05, crash_round=16, crash_fraction=.5)
        mh = Simulation("metropolis_hastings", cfg).run()
        mrwb = Simulation("mrwb", cfg).run()
        self.assertGreater(mrwb["samples"]["live_sample_rate"], mh["samples"]["live_sample_rate"])


class InterfaceTests(unittest.TestCase):
    def test_outputs_and_summary_confidence(self):
        runs = run_experiments(small(rounds=7, warmup=2), ["cyclon"], ["static"], [1, 2])
        summary = summarize(runs)
        self.assertEqual(summary[0]["runs"], 2)
        self.assertIsNotNone(summary[0]["global_tv_ci95"])
        with tempfile.TemporaryDirectory() as tmp:
            write_results(tmp, runs, summary)
            payload = json.loads((Path(tmp) / "results.json").read_text())
            self.assertEqual(len(payload["runs"]), 2)
            self.assertIn('type="application/json"', (Path(tmp) / "report.html").read_text())
            self.assertNotIn('<script src=', (Path(tmp) / "report.html").read_text())
            self.assertTrue((Path(tmp) / "summary.csv").read_text().startswith("scenario,algorithm,"))
            self.assertNotIn("__DATA__", (Path(tmp) / "report.html").read_text())

    def test_summary_accepts_direct_simulation_results(self):
        row = summarize([Simulation("cyclon", small()).run()])[0]
        self.assertEqual(row["runs"], 1)
        self.assertEqual(row["recovery_rounds_n"], 0)

    def test_new_protocol_can_be_added_without_engine_changes(self):
        class Example(Protocol):
            name = "_test_extension"
            def bootstrap(self, peers, initial): self.view = set(peers)
            def neighbors(self): return self.view
        REGISTRY[Example.name] = Example
        try:
            run = Simulation(Example.name, small(rounds=4, warmup=1)).run()
            self.assertEqual(run["samples"]["live_sample_rate"], 1)
        finally:
            del REGISTRY[Example.name]

    def test_protocol_overrides_cannot_change_shared_workload(self):
        with self.assertRaises(ValueError):
            run_experiments(small(), ["cyclon"], ["static"], [1], {"cyclon": {"nodes": 999}})

    def test_cli_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run([sys.executable, "-m", "peer_sim", "--algorithms", "cyclon,newscast",
                                   "--nodes", "12", "--rounds", "8", "--view-size", "6",
                                   "--exchange-size", "3", "--scenarios", "static,churn",
                                   "--output", tmp, "--quiet"], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((Path(tmp) / "report.html").exists())
            self.assertIn("cyclon", done.stdout)


if __name__ == "__main__":
    unittest.main()
