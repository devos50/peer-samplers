"""PeerSwap with bounded, local, eventually consistent churn repair.

Swaps are the original PeerSwap transactions. A passive reserve is learned from
counted neighborhood exchanges; timeout/reciprocity checks detect damaged edges.
Once damaged (or newly joined), a node negotiates a bounded number of replacement
edges per maintenance tick. An isolated joiner may displace one edge at a full
introducer. These repairs change topology and do not inherit PeerSwap's static
uniformity theorem. Lost commits, replies, and disconnects heal through subsequent
checks; neither atomicity nor recovery of a partition without surviving contacts
is promised.
"""
import random

from ..protocol import register
from .peerswap import PeerSwap


@register
class PeerSwapRepair(PeerSwap):
    name = "peerswap_repair"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.reserve = {}  # insertion order is bounded descriptor recency
        # Pending candidates pin reserve slots. Reciprocal admission can promote
        # one into view before its outgoing request finishes; count that slot once.
        self.connecting = set()
        self.repair_lock = None
        self.repair_number = 0
        self.damaged = False
        self.suspect = None
        # Learning a reserve must not consume the original swap/sampling RNG.
        self.repair_rng = random.Random(f"repair:{self.cfg.seed}:{self.me}")

    def bootstrap(self, peers, initial):
        peers = set(peers) - {self.me}
        if initial:
            if len(peers) > self.cfg.view_size:
                raise ValueError("peerswap_repair initial degree exceeds view_size")
            # Preserve an underfull initial topology until an actual failure is
            # observed. Filling it immediately would alter failure-free swaps.
            super().bootstrap(sorted(peers), True)
        else:
            self.damaged = True
            self.learn(peers)
            self.start_repairs()

    def state_size(self):
        """Persistent routing + passive descriptor slots, as in other protocols."""
        return len(self.view) + len(self.reserve)

    def learn(self, peers):
        peers = sorted(set(peers))
        # Descriptors in one advertisement have the same observation age. A
        # sorted insertion order would systematically retain the highest IDs
        # when a neighborhood is larger than the reserve.
        self.repair_rng.shuffle(peers)
        for peer in peers:
            if peer == self.me or peer in self.view or self.cfg.peerswap_reserve == 0:
                continue
            if peer in self.reserve:
                # Re-observation refreshes recency without extra random draws.
                self.reserve.pop(peer)
            elif len(self.reserve) >= self.cfg.peerswap_reserve:
                victim = next((p for p in self.reserve if p not in self.connecting), None)
                if victim is None:
                    continue
                self.reserve.pop(victim)
            self.reserve[peer] = None

    def changed(self):
        for peer in self.view:
            self.reserve.pop(peer, None)
        if self.suspect not in self.view:
            self.suspect = None
        self.reset_clock()

    def drop(self, peer, retain=False):
        if peer in self.view:
            self.view.remove(peer)
            self.damaged = True
            if retain:
                self.learn([peer])
            else:
                self.reserve.pop(peer, None)
            self.changed()

    def tick(self):
        if self.lock is None and self.suspect in self.view:
            peer, self.suspect = self.suspect, None
            self.rpc(peer, "swap_ping", tag=tuple(sorted(self.view)))
        elif self.view and self.lock is None:
            # Same choice as the original PeerSwap when no damage occurs.
            self.rpc(self.rng.choice(sorted(self.view)), "swap_ping",
                     tag=tuple(sorted(self.view)))
        self.start_repairs()

    def start_repairs(self):
        if not self.damaged or self.lock is not None:
            return
        available = self.cfg.view_size - len(self.view)
        candidates = sorted(set(self.reserve) - self.view)
        count = min(available, self.cfg.peerswap_repair_attempts, len(candidates))
        if count <= 0:
            return
        self.repair_number += 1
        self.repair_lock = f"repair:{self.me}:{self.repair_number}"
        self.acquire(self.repair_lock)
        selected = self.repair_rng.sample(candidates, count)
        self.connecting.update(selected)
        for peer in selected:
            self.rpc(peer, "repair_attach", {"isolated": not self.view},
                     tag=self.repair_lock)

    def finish_repair(self, peer):
        self.connecting.discard(peer)
        if not self.connecting and self.repair_lock is not None:
            lock, self.repair_lock = self.repair_lock, None
            self.release(lock)

    def advertisement(self):
        candidates = sorted(self.view | set(self.reserve))
        return self.repair_rng.sample(candidates, min(self.cfg.exchange_size, len(candidates)))

    def handle_request(self, sender, kind, data):
        if kind == "repair_attach":
            accepted = sender in self.view
            repair_only = self.lock is None or self.lock == self.repair_lock
            if not accepted and sender != self.me and repair_only:
                # Reserve slots for outgoing requests while admitting incoming
                # requests. Rejecting all requests during a repair lock would
                # deadlock underfull peers that tick at the same instant.
                occupied = self.view | self.connecting
                removable = self.view - self.connecting
                if (sender not in occupied and len(occupied) >= self.cfg.view_size
                        and data.get("isolated") and removable):
                    victim = self.repair_rng.choice(sorted(removable))
                    self.drop(victim, retain=True)
                    self.ctx.send(victim, "repair_drop")
                    occupied.discard(victim)
                if sender in self.connecting or len(occupied) < self.cfg.view_size:
                    self.view.add(sender)
                    self.changed()
                    accepted = True
            if not accepted:
                self.learn([sender])
            return {"accepted": accepted, "peers": self.advertisement()}
        if kind == "attach":
            # Bound even legacy admissions; joins of this variant use the
            # richer repair_attach exchange above.
            if sender in self.view:
                return True
            if sender == self.me or self.lock is not None or len(self.view) >= self.cfg.view_size:
                return False
            self.view.add(sender)
            self.changed()
            return True
        if kind == "swap_offer":
            self.learn(data["av"])
        return super().handle_request(sender, kind, data)

    def on_reply(self, kind, peer, data, tag):
        if kind == "repair_attach":
            if tag != self.repair_lock or peer not in self.connecting:
                return
            self.learn(data["peers"])
            if data["accepted"]:
                if self.lock == tag and len(self.view) < self.cfg.view_size:
                    self.view.add(peer)
                    self.changed()
                elif peer not in self.view:
                    self.ctx.send(peer, "repair_drop")
            self.finish_repair(peer)
            return
        if kind == "swap_ping":
            self.learn(data)
            if peer in self.view and self.me not in data:
                if self.lock is None and tuple(sorted(self.view)) == tag:
                    self.drop(peer, retain=True)
                else:
                    self.suspect = peer
            return
        if kind == "swap_offer" and data is not None:
            self.learn(data)
        super().on_reply(kind, peer, data, tag)
        # Endpoint swaps can turn passive descriptors into routing entries.
        for active in self.view:
            self.reserve.pop(active, None)

    def on_timeout(self, kind, peer, tag):
        if kind == "repair_attach":
            if tag == self.repair_lock and peer in self.connecting:
                self.reserve.pop(peer, None)
                self.finish_repair(peer)
            return
        if kind == "swap_ping":
            if self.lock is None and tuple(sorted(self.view)) == tag:
                self.drop(peer)
            elif peer in self.view:
                self.suspect = peer
            return
        super().on_timeout(kind, peer, tag)

    def handle_message(self, sender, kind, data):
        if kind == "repair_drop":
            if self.lock is None:
                self.drop(sender, retain=True)
            elif sender in self.view:
                self.suspect = sender
            return
        if kind == "swap_ack" and not data[1]:
            tx = self.transaction
            if tx and tx["id"] == data[0] and tx["stage"] == "commit":
                self.damaged = True
                self.abort()
            return
        super().handle_message(sender, kind, data)
        if kind == "swap_apply":
            self.learn(data["av"])
            self.learn(data["bv"])
        for active in self.view:
            self.reserve.pop(active, None)

    def handle_timer(self, kind, data):
        if kind == "lock_lease" and data == self.repair_lock:
            # Defensive cleanup; ordinary admission RPC timeouts occur first.
            self.connecting.clear()
            self.repair_lock = None
            self.release(data)
            return
        if kind == "commit_expire" and self.transaction and self.transaction["id"] == data:
            self.damaged = True
        super().handle_timer(kind, data)
