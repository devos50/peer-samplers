"""Generate a trace once; algorithms never influence churn or bootstrap choices."""
from dataclasses import dataclass
import hashlib
import json
import random

from .config import Config


@dataclass(frozen=True)
class Change:
    round: int
    leaving: tuple[int, ...]
    joining: tuple[tuple[int, tuple[int, ...]], ...]


@dataclass(frozen=True)
class Workload:
    initial: tuple[tuple[int, tuple[int, ...]], ...]
    changes: tuple[Change, ...]

    @property
    def digest(self):
        payload = [(c.round, c.leaving, c.joining) for c in self.changes]
        return hashlib.sha256(json.dumps([self.initial, payload]).encode()).hexdigest()


def make_workload(config: Config) -> Workload:
    rng = random.Random(config.seed)
    n = config.nodes
    edges = {i: set() for i in range(n)}
    # Undirected initial graph, shared even by directed-view protocols.
    for i in range(n):
        j = (i + 1) % n
        edges[i].add(j)
        edges[j].add(i)
    if config.topology == "star":
        edges = {i: ({0} if i else set(range(1, n))) for i in range(n)}
    elif config.topology == "random":
        # Union of random Hamiltonian cycles: connected, bounded degree <= view_size
        # for even sizes (an odd requested size is rounded down).
        for _ in range(max(0, config.view_size // 2 - 1)):
            order = list(range(n))
            rng.shuffle(order)
            for a, b in zip(order, order[1:] + order[:1]):
                edges[a].add(b)
                edges[b].add(a)
    initial = tuple((i, tuple(sorted(edges[i]))) for i in range(n))
    live = set(range(n))
    next_id = n
    changes = []
    for round_ in range(config.rounds):
        leaving = set()
        if config.scenario in ("crash", "mixed") and round_ == config.crash_round:
            k = min(len(live) - 1, int(len(live) * config.crash_fraction))
            leaving.update(rng.sample(sorted(live), k))
        survivors = live - leaving
        replacements = []
        if config.scenario in ("churn", "mixed") and round_ >= config.warmup:
            replacements = [p for p in sorted(survivors) if rng.random() < config.churn]
            # Keep one live introducer; algorithms get only the bounded bootstrap list.
            replacements = replacements[:max(0, len(survivors) - 1)]
            leaving.update(replacements)
        live.difference_update(leaving)
        joining = []
        for _ in replacements:
            seeds = tuple(rng.sample(sorted(live), min(config.bootstrap_size, len(live))))
            joining.append((next_id, seeds))
            live.add(next_id)
            next_id += 1
        if leaving or joining:
            changes.append(Change(round_, tuple(sorted(leaving)), tuple(joining)))
    return Workload(initial, tuple(changes))
