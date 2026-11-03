"""SCAMP subscriptions with variable-sized views, leases, and isolation recovery."""
from ..protocol import register
from .common import RPCProtocol


@register
class Scamp(RPCProtocol):
    name = "scamp"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.view = {}
        self.inview = {}
        self.renew_at = 0
        self.last_incoming = ctx.now
        self._ordered_view = None

    def peers(self):
        """Memoize deterministic iteration order; refresh only when keys change."""
        if self._ordered_view is None:
            self._ordered_view = tuple(sorted(self.view))
        return self._ordered_view

    def bootstrap(self, peers, initial):
        for p in peers:
            self.view[p] = self.ctx.now + self.cfg.lease_rounds * (1 + self.rng.random() * .2)
        if initial:
            self.inview.update((p, self.ctx.now + self.cfg.lease_rounds * 1.25) for p in peers)
        elif peers:
            self.ctx.send(peers[0], "subscribe", self.me)
        self.renew_at = self.ctx.now + self.cfg.lease_rounds * (.5 + .5 * self.rng.random())

    def neighbors(self):
        return set(self.view)

    def state_size(self):
        return len(self.view) + len(self.inview)

    def tick(self):
        for p in list(self.inview):
            if self.inview[p] <= self.ctx.now:
                del self.inview[p]
        for p in list(self.view):
            if self.view[p] <= self.ctx.now:
                del self.view[p]
                self._ordered_view = None
                self.ctx.send(p, "unsubscribe_edge", self.me)
        if self.view:
            self.rpc(self.rng.choice(self.peers()), "heartbeat")
        # Lease renewal republishes the subscription, never refreshes from global membership.
        if self.ctx.now >= self.renew_at or self.ctx.now - self.last_incoming > self.cfg.lease_rounds:
            candidates = sorted(set(self.view) | set(self.inview))
            if candidates:
                self.ctx.send(self.rng.choice(candidates), "subscribe", self.me)
            self.renew_at = self.ctx.now + self.cfg.lease_rounds * (.8 + .4 * self.rng.random())
            self.last_incoming = self.ctx.now

    def handle_request(self, sender, kind, data):
        self.last_incoming = self.ctx.now
        return None

    def handle_message(self, sender, kind, data):
        self.last_incoming = self.ctx.now
        if kind == "subscribe":
            peers = list(self.peers())
            if not peers:
                if data != self.me:
                    self._keep(data)
                return
            copies = peers + [self.rng.choice(peers) for _ in range(self.cfg.scamp_c)]
            for peer in copies:
                self.ctx.send(peer, "forward_subscription", [data, 4 * self.cfg.walk_length])
        elif kind == "forward_subscription":
            node, ttl = data
            if node != self.me and node not in self.view and self.rng.random() < 1 / (len(self.view) + 1):
                self._keep(node)
            else:
                if node in self.view:
                    self.view[node] = self.ctx.now + self.cfg.lease_rounds * 1.25
                if ttl > 0 and self.view:
                    self.ctx.send(self.rng.choice(self.peers()), kind, [node, ttl - 1])
        elif kind == "kept":
            self.inview[sender] = self.ctx.now + self.cfg.lease_rounds * 1.25
        elif kind == "unsubscribe_edge":
            self.inview.pop(sender, None)

    def _keep(self, node):
        if node not in self.view:
            self._ordered_view = None
        self.view[node] = self.ctx.now + self.cfg.lease_rounds * 1.25
        self.ctx.send(node, "kept", self.me)

    def on_timeout(self, kind, peer, tag):
        if peer in self.view:
            self._ordered_view = None
        self.view.pop(peer, None)
        self.inview.pop(peer, None)
