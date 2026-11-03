"""A deliberately biased extension: visits each initial neighbor in a fixed cycle.

python3 -m peer_sim --plugin examples.rotating --algorithms rotating --scenarios static
"""
from peer_sim.protocol import Protocol, register


@register
class Rotating(Protocol):
    name = "rotating"

    def bootstrap(self, peers, initial):
        self.view = sorted(set(peers) - {self.me})
        self.cursor = 0

    def neighbors(self):
        return set(self.view)

    def request_sample(self, token):
        peer = self.view[self.cursor % len(self.view)] if self.view else None
        self.cursor += 1
        self.ctx.complete(token, peer)
