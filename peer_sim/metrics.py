"""Observer-only metrics. No protocol can access the membership oracle."""
from collections import Counter, defaultdict
import math
import random
import statistics


def synthetic_ip(peer: int, groups: int) -> tuple[int, int, int, int]:
    # Unique IPv4 addresses in a reproducible, deliberately uneven prefix layout.
    group = 0 if groups == 1 or peer % 2 == 0 else 1 + (peer // 2) % (groups - 1)
    serial = peer
    return (10 + group % 200, (serial // 65536) % 256,
            (serial // 256) % 256, serial % 256)


def hierarchical_weights(peers, groups):
    """BASALT's uniform /8 -> /16 -> /24 -> address selection distribution."""
    tree = {}
    for peer in peers:
        a, b, c, _ = synthetic_ip(peer, groups)
        tree.setdefault(a, {}).setdefault(b, {}).setdefault(c, []).append(peer)
    result = {}
    for subnets in tree.values():
        for blocks in subnets.values():
            for members in blocks.values():
                weight = 1 / (len(tree) * len(subnets) * len(blocks) * len(members))
                result.update((p, weight) for p in members)
    return result


class Samples:
    def __init__(self, seed: int):
        self.requests = 0
        self.outcomes = Counter()
        self.observed = Counter()
        self.oracle = Counter()
        self.by_source = defaultdict(Counter)
        self.oracle_by_source = defaultdict(Counter)
        self.exposures = defaultdict(Counter)
        self.epochs = {}
        self.epoch_order = {}
        self.latencies = []
        self.rng = random.Random(seed)
        self.last = {}
        self.repeats = self.pairs = 0

    def result(self, source, peer, outcome, latency, epoch, live):
        self.outcomes[outcome] += 1
        if outcome != "live":
            return
        self.latencies.append(latency)
        self.observed[peer] += 1
        self.by_source[source][peer] += 1
        self.epochs[epoch] = live
        self.exposures[source][epoch] += 1
        if epoch not in self.epoch_order:
            order = tuple(sorted(live))
            self.epoch_order[epoch] = (order, {p: i for i, p in enumerate(order)})
        order, indices = self.epoch_order[epoch]
        index = self.rng.randrange(len(order) - 1)
        if index >= indices[source]:
            index += 1
        reference = order[index]
        self.oracle[reference] += 1
        self.oracle_by_source[source][reference] += 1
        if source in self.last:
            self.pairs += 1
            self.repeats += self.last[source] == peer
        self.last[source] = peer

    @staticmethod
    def tv(observed, expected):
        total = sum(observed.values())
        if total == 0:
            return None
        return max(0.0, 1 - sum(min(count / total, expected.get(p, 0.0))
                              for p, count in observed.items()))

    def report(self, target="uniform", groups=8):
        total = sum(self.observed.values())
        global_expected = Counter()
        local_tvs, oracle_tvs, intended_tvs = [], [], []
        epoch_totals = Counter()
        exclusions = Counter()
        address_trees = {}
        if target == "hierarchical":
            for epoch, peers in self.epochs.items():
                counts = Counter()
                children = defaultdict(set)
                for peer in peers:
                    address = synthetic_ip(peer, groups)
                    for depth in range(1, 5):
                        counts[address[:depth]] += 1
                        children[address[:depth - 1]].add(address[depth - 1])
                address_trees[epoch] = (counts, children)

        def intended_probability(epoch, source, peer):
            if peer == source or peer not in self.epochs[epoch]:
                return 0
            counts, children = address_trees[epoch]
            address, excluded = synthetic_ip(peer, groups), synthetic_ip(source, groups)
            probability = 1
            for depth in range(1, 5):
                parent = address[:depth - 1]
                branches = len(children[parent])
                if excluded[:depth - 1] == parent and counts[excluded[:depth]] == 1:
                    branches -= 1
                probability /= branches
            return probability

        for source, epochs in self.exposures.items():
            count = sum(epochs.values())
            support = self.by_source[source].keys() | self.oracle_by_source[source].keys()
            expected = Counter()
            intended = Counter()
            for epoch, n in epochs.items():
                peers = self.epochs[epoch]
                weight = n / (len(peers) - 1)
                epoch_totals[epoch] += weight
                exclusions[source] += weight
                for peer in support:
                    if peer in peers and peer != source:
                        expected[peer] += weight / count
                if target == "hierarchical":
                    for peer in self.by_source[source]:
                        intended[peer] += n * intended_probability(epoch, source, peer) / count
            local_tvs.append(self.tv(self.by_source[source], expected))
            oracle_tvs.append(self.tv(self.oracle_by_source[source], expected))
            if target == "hierarchical":
                intended_tvs.append(self.tv(self.by_source[source], intended))
        if total:
            for epoch, weight in epoch_totals.items():
                for peer in self.epochs[epoch]:
                    global_expected[peer] += weight / total
            for peer, weight in exclusions.items():
                global_expected[peer] -= weight / total
        outcomes = dict(self.outcomes)
        for key in ("live", "dead", "empty", "timeout", "self", "source_left"):
            outcomes.setdefault(key, 0)
        latency = sorted(self.latencies)
        mean = lambda xs: statistics.fmean(xs) if xs else None
        return {
            "requests": self.requests,
            "outcomes": outcomes,
            "live_sample_rate": total / self.requests if self.requests else None,
            "global_tv": self.tv(self.observed, global_expected),
            "iid_global_tv": self.tv(self.oracle, global_expected),
            "mean_local_tv": mean(local_tvs),
            "iid_mean_local_tv": mean(oracle_tvs),
            "local_tv_excess_over_iid": mean([a - b for a, b in zip(local_tvs, oracle_tvs)]),
            "mean_local_intended_tv": mean(intended_tvs),
            "consecutive_repeat_rate": self.repeats / self.pairs if self.pairs else None,
            "mean_latency_rounds": mean(latency),
            "p95_latency_rounds": latency[max(0, math.ceil(len(latency) * .95) - 1)] if latency else None,
            "target_histogram": dict(sorted(self.observed.items())),
        }


def overlay_snapshot(protocols, live):
    adjacency = {p: set(protocols[p].neighbors()) & live - {p} for p in live}
    undirected = {p: set(v) for p, v in adjacency.items()}
    stored = dead = 0
    for p in live:
        view = set(protocols[p].neighbors()) - {p}
        stored += len(view)
        dead += len(view - live)
        for q in adjacency[p]:
            undirected[q].add(p)
    remaining = set(live)
    sizes = []
    while remaining:
        root = min(remaining)
        stack, seen = [root], {root}
        while stack:
            for q in undirected[stack.pop()] - seen:
                seen.add(q)
                stack.append(q)
        remaining -= seen
        sizes.append(len(seen))
    # Strong components via iterative Kosaraju (no recursion depth limits).
    visited, order = set(), []
    for root in sorted(live):
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, iter(sorted(adjacency[root])))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                order.append(node)
                stack.pop()
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(sorted(adjacency[child]))))
    reverse = {p: set() for p in live}
    for p, peers in adjacency.items():
        for q in peers:
            reverse[q].add(p)
    visited, strong = set(), []
    for root in reversed(order):
        if root in visited:
            continue
        stack, size = [root], 0
        visited.add(root)
        while stack:
            node = stack.pop()
            size += 1
            for q in sorted(reverse[node] - visited):
                visited.add(q)
                stack.append(q)
        strong.append(size)
    n = len(live)
    return {
        "live_nodes": n,
        "largest_component_fraction": max(sizes, default=0) / n if n else 0,
        "largest_strong_component_fraction": max(strong, default=0) / n if n else 0,
        "isolated_fraction": sum(not adjacency[p] for p in live) / n if n else 0,
        "dead_view_fraction": dead / stored if stored else 0,
        "mean_view_size": stored / n if n else 0,
        "mean_state_descriptors": sum(protocols[p].state_size() for p in live) / n if n else 0,
    }
