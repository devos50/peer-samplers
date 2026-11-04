"""Resource limits use callback-level peaks, not occasional overlay snapshots."""
from contextlib import contextmanager
from dataclasses import replace
import unittest

from peer_sim import Config, Simulation
from peer_sim.experiment import PROTOCOL_FIELDS, run_experiments
from peer_sim.protocol import Protocol, REGISTRY
from peer_sim.workload import Change, Workload


@contextmanager
def protocol_type(cls):
    name = "_resource_probe"
    assert name not in REGISTRY
    REGISTRY[name] = cls
    try:
        yield name
    finally:
        del REGISTRY[name]


def config(**overrides):
    return Config(**dict({"nodes": 8, "rounds": 3, "warmup": 1,
                          "view_size": 6, "exchange_size": 3, "active_size": 3,
                          "observation_interval": 1, "crash_round": 1}, **overrides))


class ResourceTests(unittest.TestCase):
    def test_every_callback_peak_is_seen_between_observations(self):
        for callback in ("bootstrap", "tick", "message", "timer", "sample"):
            with self.subTest(callback=callback):
                class Probe(Protocol):
                    def bootstrap(self, peers, initial):
                        self.view = {(self.me + 1) % self.cfg.nodes}
                        if callback == "bootstrap":
                            self.grow()
                        if callback == "message":
                            self.ctx.send(self.me, "grow")
                        if callback == "timer":
                            self.ctx.timer(.2, "grow")

                    def grow(self):
                        self.view = set(range(self.cfg.nodes)) - {self.me}
                        self.ctx.timer(.1, "shrink")

                    def tick(self):
                        if callback == "tick" and self.ctx.now == 0:
                            self.grow()

                    def on_message(self, sender, kind, body):
                        self.grow()

                    def on_timer(self, kind, data):
                        if kind == "grow":
                            self.grow()
                        else:
                            self.view = {(self.me + 1) % self.cfg.nodes}

                    def request_sample(self, token):
                        if callback == "sample" and self.ctx.now < 1:
                            self.grow()
                        self.ctx.complete(token, next(iter(self.view)))

                    def neighbors(self):
                        return self.view

                    def state_size(self):
                        return len(self.view) + 1  # one retained history descriptor

                with protocol_type(Probe) as name:
                    run = Simulation(name, config()).run()
                resources = run["resource_usage"]
                self.assertEqual(resources["peak_retained_descriptors"], 8)
                self.assertEqual(resources["peak_routing_descriptors"], 7)
                self.assertEqual(resources["measured_peak_retained_descriptors"], 2)
                self.assertEqual(resources["measured_peak_routing_descriptors"], 1)
                self.assertEqual(resources["mean_retained_descriptors"], 2)
                self.assertTrue(all(row["mean_state_descriptors"] == 2
                                    for row in run["timeseries"]))

    def test_join_spike_and_node_time_weighted_means(self):
        class Probe(Protocol):
            def bootstrap(self, peers, initial):
                self.view = set(peers)

            def neighbors(self):
                return self.view

            def state_size(self):
                return self.me + 1

        workload = Workload(((0, (1,)), (1, (0,))), (
            Change(1, (0,), ((2, (1,)),)),
            Change(2, (1,), ((3, (2,)),)),
        ))
        with protocol_type(Probe) as name:
            run = Simulation(name, config(nodes=2, samples_per_node=0), workload).run()
        resources = run["resource_usage"]
        self.assertEqual(resources["peak_retained_descriptors"], 4)
        self.assertEqual(resources["measured_peak_retained_descriptors"], 4)
        self.assertEqual(resources["mean_retained_descriptors"], 3)
        self.assertEqual(resources["all_time_mean_retained_descriptors"], 2.5)
        self.assertEqual(resources["mean_routing_descriptors"], 1)
        self.assertEqual(resources["all_time_live_node_rounds"], 6)

    def test_warmup_carries_state_and_means_exclude_drain(self):
        class Probe(Protocol):
            def bootstrap(self, peers, initial):
                self.view = set(peers)
                self.count = 4
                self.ctx.timer(2.99, "late")

            def neighbors(self):
                return self.view

            def state_size(self):
                return self.count

            def on_timer(self, kind, data):
                self.ctx.send(self.me, "drain")

            def on_message(self, sender, kind, body):
                self.count = 9

        with protocol_type(Probe) as name:
            run = Simulation(name, config(maintenance_interval=100, samples_per_node=0)).run()
        resources = run["resource_usage"]
        self.assertEqual(resources["peak_retained_descriptors"], 9)
        self.assertEqual(resources["measured_peak_retained_descriptors"], 9)
        self.assertEqual(resources["mean_retained_descriptors"], 4)
        self.assertEqual(resources["all_time_mean_retained_descriptors"], 4)

    def test_staggered_maintenance_ticks_leave_sample_demand_unchanged(self):
        class Probe(Protocol):
            ticks = []

            def bootstrap(self, peers, initial):
                self.view = set(peers)

            def neighbors(self):
                return self.view

            def tick(self):
                self.ticks.append((self.me, int(self.ctx.now)))

        cfg = config(rounds=7, maintenance_interval=3)
        with protocol_type(Probe) as name:
            run = Simulation(name, cfg).run()
        self.assertEqual(sorted(Probe.ticks),
                         [(node, round_) for node in range(cfg.nodes)
                          for round_ in range(cfg.rounds) if (node + round_) % 3 == 0])
        self.assertEqual(run["samples"]["requests"], cfg.nodes * (cfg.rounds - cfg.warmup))

    def test_default_interval_and_instrumentation_are_deterministic(self):
        for algorithm in ("cyclon", "newscast", "hyparview", "peerswap"):
            with self.subTest(algorithm=algorithm):
                cfg = config(rounds=9, scenario="mixed", churn=.1)
                first = Simulation(algorithm, cfg).run()
                self.assertEqual(first, Simulation(algorithm, replace(cfg, maintenance_interval=1)).run())
                self.assertGreater(first["resource_usage"]["peak_retained_descriptors"], 0)

    def test_resource_parameters_validate_and_are_protocol_overrides(self):
        expected = {"maintenance_interval", "peerswap_reserve", "peerswap_repair_attempts"}
        self.assertTrue(expected <= PROTOCOL_FIELDS)
        for name, value in (("maintenance_interval", 0), ("maintenance_interval", 1.5),
                            ("peerswap_reserve", -1), ("peerswap_reserve", True),
                            ("peerswap_repair_attempts", 0)):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                config(**{name: value})
        self.assertEqual(config(peerswap_reserve=0).peerswap_reserve, 0)
        runs = run_experiments(config(), ["cyclon", "newscast"], ["churn"], [1],
                               {"cyclon": {"maintenance_interval": 2}})
        self.assertEqual(runs[0]["workload_digest"], runs[1]["workload_digest"])

    def test_measured_message_kinds_conserve_sent_traffic_with_churn_and_loss(self):
        class Probe(Protocol):
            def bootstrap(self, peers, initial):
                self.view = set(peers)

            def neighbors(self):
                return self.view

            def tick(self):
                self.ctx.send(self.me, "probe_live", {"peer": self.me})
                self.ctx.send(999999, "probe_dead", [self.me], channel="sampling")

        cfg = config(rounds=5, scenario="churn", churn=.2, loss=.4, samples_per_node=0)
        with protocol_type(Probe) as name:
            run = Simulation(name, cfg).run()
        kinds, traffic = run["measured_traffic_by_kind"], run["measured_traffic"]
        self.assertEqual(set(kinds), {"probe_live", "probe_dead"})
        self.assertEqual(kinds["probe_live"]["messages"], cfg.nodes * (cfg.rounds - cfg.warmup))
        self.assertEqual(kinds["probe_dead"]["messages"], kinds["probe_live"]["messages"])
        self.assertGreater(run["messages_by_kind"]["probe_live"], kinds["probe_live"]["messages"])
        self.assertGreater(traffic["bootstrap_messages"], 0)
        self.assertGreater(traffic["messages_lost"], 0)
        self.assertGreater(traffic["messages_to_dead"], 0)
        self.assertEqual(sum(row["bytes"] for row in kinds.values()) + traffic["bootstrap_bytes"],
                         traffic["bytes_sent"])
        self.assertEqual(sum(row["messages"] for row in kinds.values()) + traffic["bootstrap_messages"],
                         traffic["messages_sent"])
        self.assertEqual(kinds["probe_live"]["bytes"], traffic["maintenance_bytes"])
        self.assertEqual(kinds["probe_dead"]["bytes"], traffic["sampling_bytes"])


if __name__ == "__main__":
    unittest.main()
