"""CYCLON's age-based shuffles and Newscast's freshest-descriptor merge."""
from ..protocol import choose, register
from .common import RPCProtocol


@register
class Cyclon(RPCProtocol):
    name = "cyclon"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.view = {}

    def bootstrap(self, peers, initial):
        self.view = {p: 0 for p in peers[:self.cfg.view_size] if p != self.me}

    def neighbors(self):
        return set(self.view)

    def merge(self, entries, sent, partner=None):
        incoming = {}
        for p, age in entries:
            if p != self.me:
                incoming[p] = min(age, incoming.get(p, age))
        for p in incoming.keys() & self.view.keys():
            self.view[p] = min(self.view[p], incoming[p])
        new = [p for p in incoming if p not in self.view]
        self.rng.shuffle(new)
        eligible = set(sent) | ({partner} if partner is not None else set())
        victims = [p for p in sorted(eligible) if p in self.view and p not in incoming]
        self.rng.shuffle(victims)
        for p in new:
            if len(self.view) >= self.cfg.view_size:
                if not victims:
                    continue
                self.view.pop(victims.pop())
            self.view[p] = incoming[p]

    def tick(self):
        for p in self.view:
            self.view[p] += 1
        if not self.view:
            return
        oldest = max(self.view.values())
        peer = self.rng.choice(sorted(p for p in self.view if self.view[p] == oldest))
        selected = choose(self.rng, self.view.keys() - {peer}, self.cfg.exchange_size - 1)
        entries = [[p, self.view[p]] for p in selected] + [[self.me, 0]]
        self.rpc(peer, "shuffle", entries, selected)

    def handle_request(self, sender, kind, data):
        if kind == "shuffle":
            selected = choose(self.rng, self.view, self.cfg.exchange_size)
            reply = [[p, self.view[p]] for p in selected]
            self.merge(data, selected)
            return reply

    def on_reply(self, kind, peer, data, tag):
        if kind == "shuffle":
            self.merge(data, tag, partner=peer)

    def on_timeout(self, kind, peer, tag):
        self.view.pop(peer, None)


@register
class Newscast(RPCProtocol):
    name = "newscast"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.view = {}

    def bootstrap(self, peers, initial):
        self.view = {p: self.ctx.now for p in peers[:self.cfg.view_size] if p != self.me}

    def neighbors(self):
        return set(self.view)

    def entries(self):
        return [[p, ts] for p, ts in sorted(self.view.items())] + [[self.me, self.ctx.now]]

    def merge(self, entries):
        for p, timestamp in entries:
            if p != self.me:
                self.view[p] = max(timestamp, self.view.get(p, -1))
        items = list(self.view.items())
        self.rng.shuffle(items)  # timestamp ties must not favor small identifiers
        items.sort(key=lambda entry: entry[1], reverse=True)
        self.view = dict(items[:self.cfg.view_size])

    def tick(self):
        if self.view:
            peer = self.rng.choice(sorted(self.view))
            self.rpc(peer, "news", self.entries())

    def handle_request(self, sender, kind, data):
        if kind == "news":
            reply = self.entries()
            self.merge(data)
            return reply

    def on_reply(self, kind, peer, data, tag):
        if kind == "news":
            self.merge(data)

    def on_timeout(self, kind, peer, tag):
        self.view.pop(peer, None)
