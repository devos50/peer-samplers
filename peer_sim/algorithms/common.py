"""Counted request/reply timeouts shared by protocols, never a liveness oracle."""
import hashlib
from functools import lru_cache

from ..protocol import Protocol


@lru_cache(maxsize=262144)
def rank(seed: int, value) -> int:
    raw = f"{seed}:{value}".encode()
    return int.from_bytes(hashlib.blake2b(raw, digest_size=16).digest(), "big")


class RPCProtocol(Protocol):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._rpc_id = 0
        self._pending = {}

    def rpc(self, peer, kind, data=None, tag=None, channel="maintenance"):
        self._rpc_id += 1
        rid = self._rpc_id
        self._pending[rid] = (peer, kind, tag)
        self.ctx.send(peer, f"rpc:{kind}", {"id": rid, "data": data, "channel": channel}, channel)
        self.ctx.timer(self.cfg.timeout, "rpc_timeout", rid)
        return rid

    def on_message(self, sender, kind, body):
        if kind.startswith("reply:"):
            pending = self._pending.get(body["id"])
            if pending and pending[0] == sender and kind == f"reply:{pending[1]}":
                self._pending.pop(body["id"])
                self.on_reply(pending[1], sender, body["data"], pending[2])
        elif kind.startswith("rpc:"):
            request = kind[4:]
            response = self.handle_request(sender, request, body["data"])
            self.ctx.send(sender, f"reply:{request}", {"id": body["id"], "data": response},
                          body.get("channel", "maintenance"))
        else:
            self.handle_message(sender, kind, body)

    def on_timer(self, kind, data):
        if kind == "rpc_timeout":
            pending = self._pending.pop(data, None)
            if pending:
                self.on_timeout(pending[1], pending[0], pending[2])
        else:
            self.handle_timer(kind, data)

    def handle_request(self, sender, kind, data):
        return None  # ping, by default

    def on_reply(self, kind, peer, data, tag):
        pass

    def on_timeout(self, kind, peer, tag):
        pass

    def handle_message(self, sender, kind, data):
        pass

    def handle_timer(self, kind, data):
        pass
