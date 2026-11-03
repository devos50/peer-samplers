"""Peer position swaps with counted neighborhood locking and commit messages.

The original failure-free model is the fidelity target. Crash/loss cleanup and
bootstrap attachment below are explicitly experimental extensions.
"""
from ..protocol import register
from .common import RPCProtocol


@register
class PeerSwap(RPCProtocol):
    name = "peerswap"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.view = set()
        self.lock = None
        self.transaction = None
        self.tx_number = 0
        self.clock_generation = 0
        self.completed_swaps = 0

    def bootstrap(self, peers, initial):
        self.view = set(peers) - {self.me}
        if not initial:
            for peer in sorted(self.view):
                self.rpc(peer, "attach")
        self.reset_clock()

    def neighbors(self):
        return set(self.view)

    def reset_clock(self):
        self.clock_generation += 1
        # Every undirected edge has exactly one exponential clock, owned by its
        # smaller endpoint. Total rates do not favor high-ID or low-degree peers.
        edges = [p for p in self.view if self.me < p]
        if edges:
            delay = self.rng.expovariate(self.cfg.peerswap_rate * len(edges))
            self.ctx.timer(delay, "swap_clock", self.clock_generation)

    def acquire(self, tx):
        if self.lock is not None:
            return False
        self.lock = tx
        self.ctx.timer(3 * self.cfg.timeout, "lock_lease", tx)
        return True

    def release(self, tx):
        if self.lock == tx:
            self.lock = None
            self.reset_clock()

    def tick(self):
        if self.view and self.lock is None:
            self.rpc(self.rng.choice(sorted(self.view)), "swap_ping")

    def start_swap(self, peer):
        if self.lock is not None or peer not in self.view:
            return
        self.tx_number += 1
        tx = f"{self.me}:{self.tx_number}"
        self.acquire(tx)
        self.transaction = {"id": tx, "a": self.me, "b": peer,
                            "av": sorted(self.view), "stage": "offer"}
        self.rpc(peer, "swap_offer", {"tx": tx, "av": sorted(self.view)}, tag=tx)

    def handle_request(self, sender, kind, data):
        if kind == "swap_ping":
            return sorted(self.view)
        if kind == "attach":
            if self.lock is not None:
                return False
            self.view.add(sender)
            self.reset_clock()
            return True
        if kind == "swap_offer":
            if sender not in self.view or not self.acquire(data["tx"]):
                return None
            return sorted(self.view)
        if kind == "swap_prepare":
            a, b, av, bv = data["a"], data["b"], set(data["av"]), set(data["bv"])
            if (a in self.view) != (self.me in av) or (b in self.view) != (self.me in bv):
                return False
            return self.acquire(data["id"])
        return None

    def on_reply(self, kind, peer, data, tag):
        if kind == "attach":
            if not data:
                self.ctx.timer(self.cfg.timeout, "retry_attach", peer)
            return
        if kind == "swap_ping":
            return
        tx = self.transaction
        if tx is None or tx["id"] != tag:
            return
        if kind == "swap_offer":
            if data is None:
                self.abort()
                return
            tx["bv"] = data
            tx["participants"] = sorted(set(tx["av"]) | set(data) | {tx["a"], tx["b"]})
            tx["ready"] = {tx["a"], tx["b"]}
            tx["stage"] = "prepare"
            payload = {k: tx[k] for k in ("id", "a", "b", "av", "bv")}
            for p in tx["participants"]:
                if p not in tx["ready"]:
                    self.rpc(p, "swap_prepare", payload, tag=tag)
            self.maybe_commit()
        elif kind == "swap_prepare" and tx["stage"] == "prepare":
            if not data:
                self.abort()
            else:
                tx["ready"].add(peer)
                self.maybe_commit()

    @staticmethod
    def swapped_view(node, own, a, b, av, bv):
        def transform(peers):
            return {b if p == a else a if p == b else p for p in peers}
        if node == a:
            return transform(bv) - {a}
        if node == b:
            return transform(av) - {b}
        return transform(own) - {node}

    def maybe_commit(self):
        tx = self.transaction
        if tx is None or set(tx["participants"]) != tx["ready"]:
            return
        a, b, av, bv = tx["a"], tx["b"], set(tx["av"]), set(tx["bv"])
        tx["stage"] = "commit"
        tx["waiting"] = set(tx["participants"]) - {a}
        for p in tx["participants"]:
            if p == a:
                self.view = self.swapped_view(p, self.view, a, b, av, bv)
                continue
            # For non-endpoints only the a/b incident edges change. Participants
            # compute the rest from their own locked state; it is never read here.
            self.ctx.send(p, "swap_apply", {"id": tx["id"], "a": a, "b": b,
                                           "av": sorted(av), "bv": sorted(bv)})
        self.ctx.timer(self.cfg.timeout, "commit_expire", tx["id"])

    def handle_message(self, sender, kind, data):
        if kind == "swap_abort":
            self.release(data)
        elif kind == "swap_apply":
            accepted = self.lock == data["id"]
            if accepted:
                self.view = self.swapped_view(self.me, self.view, data["a"], data["b"],
                                              set(data["av"]), set(data["bv"]))
                self.release(data["id"])
            self.ctx.send(sender, "swap_ack", [data["id"], accepted])
        elif kind == "swap_ack":
            tx = self.transaction
            if tx and tx["id"] == data[0] and tx["stage"] == "commit":
                tx["waiting"].discard(sender)
                if not tx["waiting"]:
                    self.completed_swaps += 1
                    self.release(tx["id"])
                    self.transaction = None

    def abort(self):
        tx = self.transaction
        if tx is not None:
            participants = tx.get("participants", [tx["b"]])
            for p in participants:
                if p != self.me:
                    self.ctx.send(p, "swap_abort", tx["id"])
            self.release(tx["id"])
            self.transaction = None

    def on_timeout(self, kind, peer, tag):
        if kind in ("swap_offer", "swap_prepare"):
            if self.transaction and self.transaction["id"] == tag:
                self.abort()
        elif kind in ("swap_ping", "attach") and self.lock is None:
            self.view.discard(peer)
            self.reset_clock()

    def handle_timer(self, kind, data):
        if kind == "swap_clock" and data == self.clock_generation:
            candidates = sorted(p for p in self.view if self.me < p)
            if candidates and self.lock is None:
                self.start_swap(self.rng.choice(candidates))
            self.reset_clock()
        elif kind == "lock_lease" and self.lock == data:
            if self.transaction and self.transaction["id"] == data:
                self.abort()
            else:
                self.release(data)
        elif kind == "commit_expire" and self.transaction and self.transaction["id"] == data:
            self.abort()
        elif kind == "retry_attach" and self.lock is None and data in self.view:
            self.rpc(data, "attach")
