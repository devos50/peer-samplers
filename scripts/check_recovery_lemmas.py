#!/usr/bin/env python3
"""Exhaust finite graph models for proposed post-churn recovery lemmas.

This is finite evidence, not a general proof and not a distributed protocol.
Every labeled simple graph through --max-n vertices is enumerated. Graphs with
exactly two components are checked under every distinct uniform degree cap d>=2.
Caps above n-1 give the same all-spare choices and need no additional cases.

Legal merges use spare vertices, or a nonbridge edge when a component is fully
saturated. Every legal choice must connect the components without exceeding d.
An independent check considers arbitrary intercomponent two-switches: the result
is connected exactly when at least one deleted edge was not a bridge.

--protocol-fixture additionally demonstrates the existing PeerSwapRepair
saturated-component obstruction, both as a directly supplied state and after
a single crash from connected starting graphs. It changes no protocol code.
"""
import argparse
from collections import Counter
import heapq
import itertools
import json
from pathlib import Path
import sys


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def vertices(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def components(adjacency):
    unseen = (1 << len(adjacency)) - 1
    result = []
    while unseen:
        pending = unseen & -unseen
        reached = 0
        while pending:
            bit = pending & -pending
            pending ^= bit
            if reached & bit:
                continue
            reached |= bit
            pending |= adjacency[bit.bit_length() - 1] & ~reached
        result.append(reached)
        unseen &= ~reached
    return tuple(result)


def edges(adjacency, component=None):
    allowed = (1 << len(adjacency)) - 1 if component is None else component
    return tuple((u, v) for u in vertices(allowed)
                 for v in vertices(adjacency[u] & allowed) if u < v)


def rewire(adjacency, deleted=(), added=()):
    changed = list(adjacency)
    for u, v in deleted:
        require(u != v and changed[u] & (1 << v), "deleting an absent edge")
        changed[u] &= ~(1 << v)
        changed[v] &= ~(1 << u)
    for u, v in added:
        require(u != v and not changed[u] & (1 << v), "adding a loop or duplicate edge")
        changed[u] |= 1 << v
        changed[v] |= 1 << u
    return tuple(changed)


def bridge_flags(adjacency, graph_edges):
    count = len(components(adjacency))
    return {edge: len(components(rewire(adjacency, deleted=(edge,)))) > count
            for edge in graph_edges}


def cross_pairings(first, second):
    u, v = first
    x, y = second
    return (((u, x), (v, y)), ((u, y), (v, x)))


def check_connected_with_cap(adjacency, cap, case):
    require(len(components(adjacency)) == 1, f"{case}: merge did not connect")
    require(max(map(int.bit_count, adjacency), default=0) <= cap,
            f"{case}: degree cap exceeded")


def check_graph(adjacency, parts, counts):
    n = len(adjacency)
    degrees = tuple(map(int.bit_count, adjacency))
    component_edges = tuple(edges(adjacency, part) for part in parts)
    flags = bridge_flags(adjacency, tuple(itertools.chain.from_iterable(component_edges)))

    # This check does not assume a degree cap or require nonbridge deletions.
    for first, second in itertools.product(*component_edges):
        expected_connected = not flags[first] or not flags[second]
        for added in cross_pairings(first, second):
            changed = rewire(adjacency, deleted=(first, second), added=added)
            actual_connected = len(components(changed)) == 1
            require(actual_connected == expected_connected,
                    f"two-switch criterion failed: edges={edges(adjacency)}, deleted={first, second}")
            require(tuple(map(int.bit_count, changed)) == degrees,
                    "two-switch changed labeled vertex degrees")
            counts["arbitrary_two_switch_choices"] += 1
            counts["two_switch_connected" if actual_connected else "two_switch_disconnected"] += 1

    # Exactly two components implies degree <= n-2. Thus cap n-1 and every
    # larger cap put every vertex in the same "spare" class. n=2 needs cap=2.
    for cap in range(2, max(3, n)):
        if max(degrees) > cap:
            continue
        counts["graph_cap_cases"] += 1
        spare = tuple(tuple(v for v in vertices(part) if degrees[v] < cap) for part in parts)
        if spare[0] and spare[1]:
            for u, v in itertools.product(*spare):
                changed = rewire(adjacency, added=((u, v),))
                check_connected_with_cap(changed, cap, "two spare vertices")
                counts["two_spare_merge_choices"] += 1
            continue

        nonbridges = tuple(tuple(edge for edge in group if not flags[edge])
                           for group in component_edges)
        for side in (0, 1):
            if not spare[side]:
                require(all(degrees[v] == cap for v in vertices(parts[side])),
                        "component without a spare vertex was not saturated")
                require(nonbridges[side], "saturated d-regular component has no nonbridge edge")
                counts["saturated_component_cases"] += 1

        if bool(spare[0]) != bool(spare[1]):
            saturated = 0 if not spare[0] else 1
            for edge, w in itertools.product(nonbridges[saturated], spare[1 - saturated]):
                for endpoint in edge:
                    changed = rewire(adjacency, deleted=(edge,), added=((endpoint, w),))
                    check_connected_with_cap(changed, cap, "one saturated component")
                    counts["one_saturated_merge_choices"] += 1
        else:
            for first, second in itertools.product(*nonbridges):
                for added in cross_pairings(first, second):
                    changed = rewire(adjacency, deleted=(first, second), added=added)
                    check_connected_with_cap(changed, cap, "two saturated components")
                    counts["two_saturated_merge_choices"] += 1


def check_graphs(max_n):
    totals = Counter()
    by_n = []
    for n in range(1, max_n + 1):
        potential = tuple(itertools.combinations(range(n), 2))
        counts = Counter()
        for mask in range(1 << len(potential)):
            adjacency = [0] * n
            for index in vertices(mask):
                u, v = potential[index]
                adjacency[u] |= 1 << v
                adjacency[v] |= 1 << u
            counts["labeled_simple_graphs"] += 1
            parts = components(adjacency)
            if len(parts) != 2:
                continue
            counts["two_component_graphs"] += 1
            check_graph(tuple(adjacency), parts, counts)
        by_n.append({"vertices": n, **dict(sorted(counts.items()))})
        totals.update(counts)
    totals["legal_merge_choices"] = sum(totals[key] for key in (
        "two_spare_merge_choices", "one_saturated_merge_choices", "two_saturated_merge_choices"))
    return {"status": "passed", "max_n": max_n,
            "scope": "finite labeled simple graphs; evidence, not a general proof or protocol",
            "totals": dict(sorted(totals.items())), "by_vertices": by_n}


def protocol_obstruction_fixture():
    # Imports are optional; graph checking itself needs only the standard library.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from peer_sim import Config, Simulation

    cfg = Config(nodes=6, rounds=30, warmup=0, scenario="static", view_size=2,
                 active_size=2, exchange_size=2, peerswap_reserve=3,
                 peerswap_rate=.05, samples_per_node=0, loss=0)
    sim = Simulation("peerswap_repair", cfg)
    groups = (frozenset((0, 1, 2)), frozenset((3, 4, 5)))
    for group in groups:
        for node in sorted(group):
            sim._add(node, sorted(group - {node}), initial=True)
    for group, other in ((groups[0], groups[1]), (groups[1], groups[0])):
        for node in group:
            sim.protocols[node].learn(other)
            sim.protocols[node].damaged = True

    handled = 0

    def check_closed():
        for group, other in ((groups[0], groups[1]), (groups[1], groups[0])):
            for node in group:
                protocol = sim.protocols[node]
                require(protocol.view == group - {node}, "full triangle topology changed")
                require(set(protocol.reserve) == other, "cross-component reserve was lost")
                require(protocol.damaged, "fixture lost the damage trigger")
        require(not any("repair" in kind for kind in sim.by_kind),
                "saturated fixture unexpectedly sent a repair message")

    for round_ in range(cfg.rounds):
        sim.now = float(round_)
        for node in sorted(sim.live):
            sim.protocols[node].tick()
            check_closed()
        until = round_ + 1
        while sim.queue and sim.queue[0][0] < until:
            at, _, event, data = heapq.heappop(sim.queue)
            sim.now = at
            if event == "message":
                source, target, kind, body, _ = data
                sim.protocols[target].on_message(source, kind, body)
            elif event == "timer" and at < cfg.rounds:
                node, kind, payload = data
                sim.protocols[node].on_timer(kind, payload)
            handled += 1
            check_closed()
    adjacency = tuple(sum(1 << peer for peer in sim.protocols[node].view) for node in range(6))
    require(len(components(adjacency)) == 2, "saturated fixture unexpectedly connected")
    return {"status": "expected_fragmentation_observed", "nodes": 6,
            "rounds": cfg.rounds, "components": 2, "degree_cap": 2,
            "cross_reserve_contacts_per_node": 3, "all_nodes_damaged": True,
            "membership_changes": 0, "protocol_events_checked": handled,
            "tick_callbacks_checked": cfg.rounds * cfg.nodes,
            "explicit_repair_messages": 0,
            "scope": "finite execution of the unchanged protocol with saturated triangles"}


def connected_start_fixture(cap):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from peer_sim import Config, Simulation
    from peer_sim.workload import Change, Workload

    if cap == 2:
        n, seed, leaving, reserve = 8, 1, (6, 7), 6
        cycle = (0, 1, 2, 6, 3, 4, 5, 7)
        graph_edges = list(zip(cycle, cycle[1:] + cycle[:1]))
        expected_groups = (frozenset((0, 1, 2)), frozenset((3, 4, 5)))
    elif cap == 4:
        n, seed, leaving, reserve = 12, 9, (10, 11), 12
        expected_groups = (frozenset(range(5)), frozenset(range(5, 10)))
        graph_edges = [edge for group in expected_groups
                       for edge in itertools.combinations(sorted(group), 2)
                       if edge not in ((0, 1), (5, 6))]
        graph_edges += [(0, 10), (5, 10), (10, 11), (1, 11), (6, 11)]
    else:
        raise ValueError("connected-start fixtures support caps 2 and 4")

    adjacency = rewire((0,) * n, added=graph_edges)
    require(len(components(adjacency)) == 1, "fixture did not start connected")
    require(max(map(int.bit_count, adjacency)) <= cap, "initial graph exceeds cap")
    workload = Workload(tuple((node, tuple(vertices(adjacency[node]))) for node in range(n)),
                        (Change(5, leaving, ()),))
    require(len(workload.changes) == 1 and not workload.changes[0].joining,
            "fixture must have exactly one crash and no subsequent membership changes")
    cfg = Config(nodes=n, rounds=100, warmup=1, seed=seed, view_size=cap,
                 exchange_size=cap, active_size=cap, scenario="crash", crash_round=5,
                 crash_fraction=len(leaving) / n, peerswap_rate=.0001,
                 peerswap_reserve=reserve)
    sim = Simulation("peerswap_repair", cfg, workload)
    result = sim.run()
    require(sim.live == set(range(n)) - set(leaving), "unexpected final membership")
    # Compact live IDs before bitset connectivity checks: departed IDs are not
    # retained as isolated vertices, and component identities stay original IDs.
    live_ids = sorted(sim.live)
    indexes = {node: index for index, node in enumerate(live_ids)}
    for node in live_ids:
        require(len(sim.protocols[node].view) == cap, "final component is not saturated")
        require(sim.protocols[node].view <= sim.live, "stale final routing descriptor")
        require(all(node in sim.protocols[peer].view for peer in sim.protocols[node].view),
                "final routing graph is asymmetric")
    final_adjacency = tuple(sum(1 << indexes[peer] for peer in sim.protocols[node].view)
                            for node in live_ids)
    final_groups = tuple(frozenset(live_ids[index] for index in vertices(part))
                         for part in components(final_adjacency))
    require(set(final_groups) == set(expected_groups), "unexpected final components")
    cross_reserves = {}
    damaged_with_cross_reserve = []
    for group in final_groups:
        witnesses = []
        for node in sorted(group):
            cross = sorted(set(sim.protocols[node].reserve) & (sim.live - group))
            if cross:
                cross_reserves[node] = cross
                if sim.protocols[node].damaged:
                    witnesses.append(node)
        require(witnesses, "component lacks a damaged peer with a surviving cross-reserve contact")
        damaged_with_cross_reserve.extend(witnesses)
    require(result["final_overlay"]["largest_strong_component_fraction"] == .5,
            "unexpected final strongly connected component fraction")
    return {"status": "reachable_fragmentation_observed", "initial_nodes": n,
            "degree_cap": cap, "seed": seed, "rounds": cfg.rounds,
            "initial_components": 1, "crash_round": 5, "departed_nodes": list(leaving),
            "membership_change_events": 1, "subsequent_membership_changes": 0,
            "final_components": [sorted(group) for group in final_groups],
            "all_survivors_saturated": True, "final_largest_scc_fraction": .5,
            "surviving_cross_reserves": cross_reserves,
            "damaged_nodes_with_cross_reserves": sorted(damaged_with_cross_reserve),
            "workload_digest": workload.digest,
            "scope": "finite execution of unchanged protocol; connected start and one crash"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-n", type=int, default=6,
                        help="largest labeled graph size (default: 6; exponential enumeration)")
    parser.add_argument("--protocol-fixture", action="store_true",
                        help="check direct-state and reachable connected-start fragmentation fixtures")
    args = parser.parse_args(argv)
    if args.max_n < 2:
        parser.error("--max-n must be at least 2")
    result = check_graphs(args.max_n)
    if args.protocol_fixture:
        result["protocol_fixture"] = protocol_obstruction_fixture()
        result["connected_start_fixtures"] = [connected_start_fixture(cap) for cap in (2, 4)]
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
