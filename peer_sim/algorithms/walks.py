"""Sampling existing undirected overlays: ordinary, metropolized, backtracking walks."""
from ..protocol import register
from .common import RPCProtocol


@register
class RandomWalk(RPCProtocol):
    name = "random_walk"
    metropolis = False
    backtracking = False

    def __init__(self, ctx):
        super().__init__(ctx)
        self.view = set()
        self.walks = {}

    def bootstrap(self, peers, initial):
        self.view = set(peers) - {self.me}
        if not initial:
            for peer in sorted(self.view):
                self.rpc(peer, "attach")

    def neighbors(self):
        return set(self.view)

    def tick(self):
        if self.view:
            self.rpc(self.rng.choice(sorted(self.view)), "ping")

    def handle_request(self, sender, kind, data):
        if kind == "attach":
            self.view.add(sender)
        if kind == "neighbors":
            return sorted(self.view)
        return None

    def request_sample(self, token):
        self.walks[token] = {"current": self.me, "neighbors": sorted(self.view),
                             "steps": 0, "attempts": 0, "path": []}
        self.ctx.timer(self.cfg.sample_timeout, "walk_expire", token)
        self.advance(token)

    def advance(self, token):
        walk = self.walks.get(token)
        if walk is None:
            return
        if walk["steps"] >= self.cfg.walk_length:
            self.finish(token, walk["current"])
            return
        if not walk["neighbors"] or walk["attempts"] >= self.cfg.walk_length * 4:
            self.finish(token, None)
            return
        peer = self.rng.choice(walk["neighbors"])
        walk["proposed"] = peer
        walk["attempts"] += 1
        # Query before accepting; both query and reply carry sampling overhead.
        self.rpc(peer, "neighbors", tag=token, channel="sampling")

    def finish(self, token, peer):
        self.walks.pop(token, None)
        self.ctx.complete(token, peer)

    def on_reply(self, kind, peer, data, tag):
        if kind != "neighbors":
            return
        walk = self.walks.get(tag)
        if walk is None:
            return
        degree = len(data)
        accept = (not self.metropolis or
                  (degree > 0 and self.rng.random() < min(1, len(walk["neighbors"]) / degree)))
        if accept:
            walk["path"].append((walk["current"], walk["neighbors"]))
            walk["current"], walk["neighbors"] = peer, data
        walk["steps"] += 1  # rejected moves are real self-loop Markov steps
        self.advance(tag)

    def on_timeout(self, kind, peer, tag):
        self.view.discard(peer)
        if kind != "neighbors":
            return
        walk = self.walks.get(tag)
        if walk is None:
            return
        if not self.backtracking:
            self.finish(tag, None)
            return
        # Remove the failed proposal locally and recover the last known path state.
        walk["neighbors"] = [p for p in walk["neighbors"] if p != peer]
        if walk["path"]:
            walk["current"], neighbors = walk["path"].pop()
            walk["neighbors"] = [p for p in neighbors if p != peer]
        self.advance(tag)

    def handle_timer(self, kind, data):
        if kind == "walk_expire":
            self.walks.pop(data, None)


@register
class MetropolisHastings(RandomWalk):
    name = "metropolis_hastings"
    metropolis = True


@register
class MRWB(MetropolisHastings):
    name = "mrwb"
    backtracking = True
