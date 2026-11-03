"""Active/passive views, forwarded joins, neighbor handshakes, routed shuffles."""
from ..protocol import choose, register
from .common import RPCProtocol


@register
class HyParView(RPCProtocol):
    name = "hyparview"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.active = set()
        self.passive = set()
        self.connecting = set()
        self.attempted = set()
        self.shuffles = {}
        self.shuffle_id = 0

    def bootstrap(self, peers, initial):
        self.add_passive(peers)
        # Negotiate active edges, including at startup; arbitrary local truncation
        # of a shared graph would create asymmetric active views.
        if peers and not initial:
            self.ctx.send(peers[0], "join", self.me)
        self.repair()

    def neighbors(self):
        return set(self.active)

    def state_size(self):
        return len(self.active) + len(self.passive)

    def add_passive(self, peers, preferred=()):
        for peer in peers:
            if peer != self.me and peer not in self.active:
                if peer not in self.passive and len(self.passive) >= self.cfg.view_size:
                    victims = (set(preferred) & self.passive) or self.passive
                    self.passive.remove(self.rng.choice(sorted(victims)))
                self.passive.add(peer)

    def add_active(self, peer, force=False):
        if peer == self.me:
            return False
        if peer in self.active:
            return True
        if len(self.active) >= self.cfg.active_size:
            if not force:
                return False
            victim = self.rng.choice(sorted(self.active))
            self.active.remove(victim)
            self.ctx.send(victim, "disconnect", None)
            self.add_passive([victim])
        self.active.add(peer)
        self.passive.discard(peer)
        return True

    def repair(self):
        candidates = self.passive - self.connecting - self.attempted
        free = self.cfg.active_size - len(self.active) - len(self.connecting)
        for peer in choose(self.rng, candidates, max(0, free)):
            self.connecting.add(peer)
            self.attempted.add(peer)
            self.rpc(peer, "neighbor", not self.active)

    def tick(self):
        self.attempted.clear()
        for peer in sorted(self.active):
            self.rpc(peer, "ping")
        self.repair()
        if self.active:
            selected = choose(self.rng, self.passive, max(0, self.cfg.exchange_size - 2))
            entries = [self.me] + choose(self.rng, self.active, 1) + selected
            self.shuffle_id += 1
            sid = self.shuffle_id
            self.shuffles[sid] = selected
            self.ctx.send(self.rng.choice(sorted(self.active)), "hp_shuffle",
                          [self.me, sid, 3, entries])
            self.ctx.timer(self.cfg.timeout, "shuffle_expire", sid)

    def handle_request(self, sender, kind, data):
        if kind == "neighbor":
            return self.add_active(sender, force=bool(data))
        return None

    def on_reply(self, kind, peer, data, tag):
        if kind == "neighbor":
            self.connecting.discard(peer)
            if data:
                if not self.add_active(peer):
                    self.ctx.send(peer, "disconnect", None)
            self.repair()

    def on_timeout(self, kind, peer, tag):
        self.active.discard(peer)
        self.passive.discard(peer)
        self.connecting.discard(peer)
        self.repair()

    def handle_message(self, sender, kind, data):
        if kind == "disconnect":
            self.active.discard(sender)
            self.add_passive([sender])
            self.repair()
        elif kind == "join":
            node = data
            previous = sorted(self.active)
            self.rpc(node, "neighbor", True)
            self.connecting.add(node)
            for peer in previous:
                self.ctx.send(peer, "forward_join", [node, 4])
        elif kind == "forward_join":
            node, ttl = data
            if ttl == 2:
                self.add_passive([node])
            candidates = self.active - {sender, node}
            if ttl <= 0 or not candidates:
                if node != self.me:
                    self.connecting.add(node)
                    self.rpc(node, "neighbor", True)
            else:
                self.ctx.send(self.rng.choice(sorted(candidates)), kind, [node, ttl - 1])
        elif kind == "hp_shuffle":
            origin, sid, ttl, entries = data
            candidates = self.active - {sender, origin}
            if ttl > 0 and candidates:
                self.ctx.send(self.rng.choice(sorted(candidates)), kind, [origin, sid, ttl - 1, entries])
            else:
                reply = choose(self.rng, self.passive, len(entries))
                self.ctx.send(origin, "hp_shuffle_reply", [sid, reply])
                self.add_passive(entries, reply)
        elif kind == "hp_shuffle_reply":
            sid, entries = data
            sent = self.shuffles.pop(sid, None)
            if sent is not None:
                self.add_passive(entries, sent)

    def handle_timer(self, kind, data):
        if kind == "shuffle_expire":
            self.shuffles.pop(data, None)
