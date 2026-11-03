"""Brahms: bounded pushes/pulls, history samplers, and explicit stale probes."""
from ..protocol import register
from .common import RPCProtocol, rank


@register
class Brahms(RPCProtocol):
    name = "brahms"

    def __init__(self, ctx):
        super().__init__(ctx)
        if self.cfg.view_size < 3:
            raise ValueError("Brahms requires view_size >= 3 for push, pull, and history quotas")
        self.view = []
        self.seeds = [self.rng.getrandbits(128) for _ in range(self.cfg.view_size)]
        self.samples = [None] * self.cfg.view_size
        self.best = [None] * self.cfg.view_size
        self.pushes, self.pulls = [], []
        self.round_id = 0
        self.probe_cursor = 0
        self.alpha = max(1, self.cfg.view_size // 3)
        self.beta = max(1, self.cfg.view_size // 3)

    def bootstrap(self, peers, initial):
        self.view = [p for p in peers[:self.cfg.view_size] if p != self.me]
        self.observe(self.view)

    def neighbors(self):
        return set(self.view)

    def state_size(self):
        return len(self.view) + sum(p is not None for p in self.samples)

    def observe(self, peers):
        for peer in sorted(set(peers) - {self.me, None}):
            for i, seed in enumerate(self.seeds):
                score = rank(seed, peer)
                if self.best[i] is None or score < self.best[i]:
                    self.best[i], self.samples[i] = score, peer

    def tick(self):
        self.round_id += 1
        self.pushes, self.pulls = [], []
        if self.view:
            for _ in range(self.alpha):
                self.ctx.send(self.rng.choice(self.view), "limited_push", self.round_id)
            for _ in range(self.beta):
                self.rpc(self.rng.choice(self.view), "brahms_pull", tag=self.round_id)
        # Probe a rotating batch; not every sample on every round.
        for _ in range(min(self.cfg.exchange_size, len(self.samples))):
            i = self.probe_cursor % len(self.samples)
            self.probe_cursor += 1
            if self.samples[i] is not None:
                self.rpc(self.samples[i], "sample_probe", tag=(i, self.seeds[i]))
        self.ctx.timer(self.cfg.timeout + .01, "finish_round", self.round_id)

    def handle_request(self, sender, kind, data):
        if kind == "brahms_pull":
            return list(self.view)
        return None

    def handle_message(self, sender, kind, data):
        if kind == "limited_push":
            self.pushes.append(sender)

    def on_reply(self, kind, peer, data, tag):
        if kind == "brahms_pull" and tag == self.round_id:
            self.pulls.extend(p for p in data if p != self.me)

    def handle_timer(self, kind, data):
        if kind != "finish_round" or data != self.round_id:
            return
        pushes = [p for p in self.pushes if p != self.me]
        history = [p for p in self.samples if p is not None]
        if 0 < len(pushes) <= self.alpha and self.pulls and history:
            history_count = max(0, self.cfg.view_size - self.alpha - self.beta)
            self.view = (self.rng.choices(pushes, k=self.alpha) +
                         self.rng.choices(self.pulls, k=self.beta) +
                         self.rng.choices(history, k=history_count))
        self.observe(pushes + self.pulls)

    def on_timeout(self, kind, peer, tag):
        self.view = [p for p in self.view if p != peer]
        if kind == "sample_probe":
            i, seed = tag
            if self.seeds[i] == seed and self.samples[i] == peer:
                self.seeds[i] = self.rng.getrandbits(128)
                self.samples[i] = self.best[i] = None

    def sample_pool(self):
        # Preserve duplicate slots: deduplication would alter the sampling law.
        return [p for p in self.samples if p is not None]
