"""Fault and invariant tests for the experimental PeerSwap repair extension."""
import heapq
import unittest

from peer_sim import Config, Simulation
from peer_sim.algorithms.peerswap_repair import PeerSwapRepair
from peer_sim.engine import Context
from peer_sim.protocol import REGISTRY


def config(**kwargs):
    values = dict(nodes=24, rounds=50, warmup=5, view_size=4, exchange_size=2,
                  active_size=2, crash_round=20, peerswap_reserve=8)
    values.update(kwargs)
    return Config(**values)


def advance(sim, until):
    """Deliver only explicitly queued protocol events for small fault fixtures."""
    while sim.queue and sim.queue[0][0] <= until:
        at, _, kind, body = heapq.heappop(sim.queue)
        sim.now = at
        if kind == "message":
            source, target, message, data, _ = body
            if target in sim.live:
                sim.protocols[target].on_message(source, message, data)
        elif kind == "timer":
            node, timer, data = body
            if node in sim.live:
                sim.protocols[node].on_timer(timer, data)
    sim.now = until


class RepairTests(unittest.TestCase):
    def test_failure_free_samples_traffic_and_swaps_match_original(self):
        for topology in ("random", "ring"):
            cfg = config(topology=topology)
            original = Simulation("peerswap", cfg)
            repaired = Simulation("peerswap_repair", cfg)
            left, right = original.run(), repaired.run()
            self.assertEqual(left["samples"], right["samples"])
            self.assertEqual(left["traffic"], right["traffic"])
            self.assertEqual(left["messages_by_kind"], right["messages_by_kind"])
            for node in original.live:
                self.assertEqual(original.protocols[node].view, repaired.protocols[node].view)
                self.assertEqual(original.protocols[node].completed_swaps,
                                 repaired.protocols[node].completed_swaps)
            self.assertFalse(any(node.damaged for node in repaired.protocols.values()))
            self.assertGreater(sum(node.state_size() - len(node.view)
                                   for node in repaired.protocols.values()), 0)

    def test_rejects_overfull_initial_graph_without_silent_truncation(self):
        with self.assertRaisesRegex(ValueError, "initial degree"):
            Simulation("peerswap_repair", config(topology="star")).run()

    def test_every_event_preserves_descriptor_and_degree_bounds_under_loss(self):
        testcase = self

        class Checked(PeerSwapRepair):
            def check(self):
                testcase.assertNotIn(self.me, self.view | set(self.reserve))
                testcase.assertLessEqual(len(self.view), self.cfg.view_size)
                testcase.assertLessEqual(len(self.reserve), self.cfg.peerswap_reserve)
                testcase.assertFalse(self.view & set(self.reserve))
                testcase.assertTrue(self.connecting <= self.view | set(self.reserve))
                testcase.assertLessEqual(len(self.view | self.connecting), self.cfg.view_size)
                testcase.assertLessEqual(len(self.connecting), self.cfg.peerswap_repair_attempts)
                testcase.assertLessEqual(self.state_size(), self.cfg.view_size + self.cfg.peerswap_reserve)

        for method in ("bootstrap", "tick", "on_message", "on_timer"):
            parent = getattr(PeerSwapRepair, method)

            def checked(self, *args, parent=parent):
                result = parent(self, *args)
                self.check()
                return result

            setattr(Checked, method, checked)
        REGISTRY["peerswap_repair_checked"] = Checked
        try:
            cfg = config(scenario="mixed", churn=.12, loss=.15,
                         peerswap_repair_attempts=3, peerswap_reserve=5)
            result = Simulation("peerswap_repair_checked", cfg).run()
            self.assertGreater(result["traffic"]["messages_lost"], 0)
            self.assertGreater(result["messages_by_kind"].get("rpc:repair_attach", 0), 0)
        finally:
            REGISTRY.pop("peerswap_repair_checked")

    def test_asymmetric_edge_is_removed_then_reciprocally_readmitted(self):
        sim = Simulation("peerswap_repair", config(peerswap_rate=1e-12))
        sim._add(0, [1], initial=True)
        sim._add(1, [], initial=True)
        a, b = sim.protocols[0], sim.protocols[1]
        a.tick()
        advance(sim, .5)
        self.assertFalse(a.view)
        self.assertTrue(a.damaged)
        self.assertIn(1, a.reserve)
        a.tick()
        advance(sim, 1)
        self.assertEqual(a.view, {1})
        self.assertEqual(b.view, {0})
        self.assertGreater(sim.traffic["maintenance_bytes"], 0)
        self.assertEqual(sim.by_kind["rpc:repair_attach"], 1)
        self.assertEqual(sim.by_kind["reply:repair_attach"], 1)

    def test_simultaneous_underfull_peers_admit_each_other_during_repair(self):
        sim = Simulation("peerswap_repair", config(view_size=2, peerswap_rate=1e-12))
        sim._add(0, [], initial=True)
        sim._add(1, [], initial=True)
        a, b = sim.protocols[0], sim.protocols[1]
        a.damaged = b.damaged = True
        a.learn([1])
        b.learn([0])
        a.tick()
        b.tick()
        self.assertIsNotNone(a.lock)
        self.assertIsNotNone(b.lock)
        advance(sim, .5)
        self.assertEqual(a.view, {1})
        self.assertEqual(b.view, {0})
        self.assertFalse(a.connecting | b.connecting)
        self.assertIsNone(a.lock)
        self.assertIsNone(b.lock)

    def test_simultaneous_three_peer_cycle_reserves_capacity_for_both_directions(self):
        sim = Simulation("peerswap_repair", config(view_size=2, peerswap_rate=1e-12))
        for node in range(3):
            sim._add(node, [], initial=True)
            protocol = sim.protocols[node]
            protocol.damaged = True
            protocol.learn([(node + 1) % 3])
        for protocol in sim.protocols.values():
            protocol.tick()
        advance(sim, .5)
        for node, protocol in sim.protocols.items():
            self.assertEqual(protocol.view, {0, 1, 2} - {node})
            self.assertFalse(protocol.connecting)
            self.assertIsNone(protocol.lock)

    def test_admission_cannot_consume_a_slot_reserved_for_another_outgoing_request(self):
        sim = Simulation("peerswap_repair", config(view_size=2, peerswap_rate=1e-12))
        sim._add(0, [1], initial=True)
        node = sim.protocols[0]
        node.damaged = True
        node.learn([2])
        node.tick()
        self.assertEqual(node.connecting, {2})
        rejected = node.handle_request(3, "repair_attach", {"isolated": False})
        self.assertFalse(rejected["accepted"])
        self.assertEqual(node.view, {1})
        # A reciprocal request for the reserved peer shares that slot.
        accepted = node.handle_request(2, "repair_attach", {"isolated": False})
        self.assertTrue(accepted["accepted"])
        self.assertEqual(node.view, {1, 2})
        self.assertEqual(len(node.view | node.connecting), 2)

    def test_lost_admission_reply_does_not_leave_a_permanent_one_way_edge(self):
        sim = Simulation("peerswap_repair", config(peerswap_rate=1e-12))
        sim._add(0, [], initial=True)
        sim._add(1, [], initial=True)
        a, b = sim.protocols[0], sim.protocols[1]
        a.damaged = True
        a.learn([1])
        a.tick()
        advance(sim, sim.config.latency)
        self.assertEqual(b.view, {0})
        # Drop precisely the admission reply after send() has charged its bytes.
        sim.queue = [event for event in sim.queue
                     if not (event[2] == "message" and event[3][2] == "reply:repair_attach")]
        heapq.heapify(sim.queue)
        advance(sim, .5)
        self.assertFalse(a.view)
        self.assertFalse(a.connecting)
        b.tick()
        advance(sim, 1)
        self.assertFalse(b.view)  # reciprocal check discovers the lost reply
        b.tick()
        advance(sim, 1.5)
        self.assertEqual(a.view, {1})
        self.assertEqual(b.view, {0})

    def test_isolated_joiner_displaces_at_most_one_edge_at_full_introducer(self):
        sim = Simulation("peerswap_repair", config(peerswap_rate=1e-12, view_size=2))
        for node, peers in ((0, [1, 2]), (1, [0]), (2, [0])):
            sim._add(node, peers, initial=True)
        sim._add(3, [0], initial=False)
        advance(sim, .5)
        self.assertIn(0, sim.protocols[3].view)
        self.assertIn(3, sim.protocols[0].view)
        self.assertEqual(len(sim.protocols[0].view), 2)
        self.assertEqual(sim.by_kind["repair_drop"], 1)
        for node in (1, 2):
            self.assertEqual(node in sim.protocols[0].view, 0 in sim.protocols[node].view)

    def test_negative_commit_ack_is_not_counted_as_success(self):
        sim = Simulation("peerswap_repair", config())
        node = PeerSwapRepair(Context(sim, 0))
        node.lock = "0:1"
        node.transaction = {"id": "0:1", "a": 0, "b": 1,
                            "stage": "commit", "waiting": {1}, "participants": [0, 1]}
        node.handle_message(1, "swap_ack", ["0:1", False])
        self.assertEqual(node.completed_swaps, 0)
        self.assertIsNone(node.transaction)
        self.assertTrue(node.damaged)

    def test_dropped_swap_apply_eventually_heals_partial_commit(self):
        sim = Simulation("peerswap_repair", config(view_size=2, peerswap_rate=1e-12))
        for node, peers in ((0, [1, 2]), (1, [0, 3]), (2, [0]), (3, [1])):
            sim._add(node, peers, initial=True)
        sim.protocols[0].start_swap(1)
        advance(sim, .081)  # normal offer/prepare exchange has sent commit
        dropped = [event for event in sim.queue
                   if event[2] == "message" and event[3][1:3] == (2, "swap_apply")]
        self.assertEqual(len(dropped), 1)
        sim.queue = [event for event in sim.queue if event not in dropped]
        heapq.heapify(sim.queue)
        advance(sim, 2)
        self.assertIn(0, sim.protocols[2].view)
        self.assertNotIn(2, sim.protocols[0].view)
        self.assertEqual(sim.protocols[0].completed_swaps, 0)
        for round_ in range(2, 22):
            for protocol in sim.protocols.values():
                protocol.tick()
            advance(sim, round_ + 1)
        for node, protocol in sim.protocols.items():
            self.assertTrue(protocol.view)
            for neighbor in protocol.view:
                self.assertIn(node, sim.protocols[neighbor].view)
        self.assertGreater(sim.by_kind["rpc:repair_attach"], 0)

    def test_no_surviving_contact_cannot_be_replaced_by_a_membership_oracle(self):
        sim = Simulation("peerswap_repair", config())
        node = PeerSwapRepair(Context(sim, 0))
        node.damaged = True
        for _ in range(10):
            node.tick()
        self.assertFalse(node.view)
        self.assertFalse(node.reserve)
        self.assertFalse(sim.queue)

    def test_mixed_churn_reproducible_and_requests_conserved(self):
        cfg = config(scenario="mixed", churn=.08, loss=.05)
        first = Simulation("peerswap_repair", cfg).run()
        self.assertEqual(first, Simulation("peerswap_repair", cfg).run())
        samples = first["samples"]
        self.assertEqual(samples["requests"], sum(samples["outcomes"].values()))


if __name__ == "__main__":
    unittest.main()
