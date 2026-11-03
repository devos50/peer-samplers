"""BASALT's hit counters, greedy ranking, and round-robin seed refresh."""
from functools import lru_cache
from ..metrics import synthetic_ip
from ..protocol import register
from .common import RPCProtocol, rank


@lru_cache(maxsize=262144)
def _ranking(seed, peer, hierarchical, address_groups):
    """Bounded simulator-side memoization; contains no protocol or membership state."""
    if not hierarchical:
        return (rank(seed, peer),)
    address = synthetic_ip(peer, address_groups)
    return tuple(rank(seed, address[:i]) for i in range(1, 5))


@register
class Basalt(RPCProtocol):
    name = "basalt"
    hierarchical = True
    sampling_target = "hierarchical"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.seeds = [self.rng.getrandbits(128) for _ in range(self.cfg.view_size)]
        self.slots = [None] * self.cfg.view_size
        self.ranks = [None] * self.cfg.view_size
        self.hits = [0] * self.cfg.view_size
        self.cursor = 0

    def ranking(self, seed, peer):
        return _ranking(seed, peer, self.hierarchical, self.cfg.address_groups)

    def bootstrap(self, peers, initial):
        self.update(peers)

    def update(self, peers):
        for peer in peers:
            if peer is None or peer == self.me:
                continue
            for i, seed in enumerate(self.seeds):
                if self.slots[i] == peer:
                    self.hits[i] += 1
                    continue
                score = self.ranking(seed, peer)
                if self.ranks[i] is None or score < self.ranks[i]:
                    self.slots[i], self.ranks[i], self.hits[i] = peer, score, 1

    def select_peer(self):
        candidates = [i for i, p in enumerate(self.slots) if p is not None]
        if not candidates:
            return None
        minimum = min(self.hits[i] for i in candidates)
        i = self.rng.choice([i for i in candidates if self.hits[i] == minimum])
        self.hits[i] += 1
        return self.slots[i]

    def neighbors(self):
        return set(self.sample_pool())

    def sample_pool(self):
        return [p for p in self.slots if p is not None]

    def state_size(self):
        return len(self.sample_pool())

    def tick(self):
        p, q = self.select_peer(), self.select_peer()
        if p is not None:
            self.rpc(p, "basalt_pull")
        if q is not None:
            self.ctx.send(q, "basalt_push", self.sample_pool())
        # A fixed background refresh rate makes maintenance independent of query load.
        # Queries consume their selected slot too (see request_sample).
        for _ in range(self.cfg.basalt_refresh):
            self.refresh()

    def refresh(self):
        i = self.cursor % len(self.slots)
        self.cursor += 1
        peer = self.slots[i]
        candidates = self.sample_pool()
        self.seeds[i] = self.rng.getrandbits(128)
        self.slots[i] = self.ranks[i] = None
        self.hits[i] = 0
        self.update(candidates)
        return peer

    def request_sample(self, token):
        self.ctx.complete(token, self.refresh())

    def handle_request(self, sender, kind, data):
        if kind == "basalt_pull":
            return self.sample_pool()
        return None

    def handle_message(self, sender, kind, data):
        if kind == "basalt_push":
            self.update(data + [sender])

    def on_reply(self, kind, peer, data, tag):
        if kind == "basalt_pull":
            self.update(data + [peer])

    def on_timeout(self, kind, peer, tag):
        # Explicit liveness extension to the static pseudocode, driven by timeouts.
        candidates = [p for p in self.sample_pool() if p != peer]
        for i, p in enumerate(self.slots):
            if p == peer:
                self.slots[i] = self.ranks[i] = None
                self.hits[i] = 0
                self.seeds[i] = self.rng.getrandbits(128)
        self.update(candidates)


@register
class BasaltUniform(Basalt):
    name = "basalt_uniform"
    hierarchical = False
    sampling_target = "uniform"
