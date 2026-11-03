"""The extension API. Protocols see local state, messages, timers, and bounded seeds."""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engine import Context


class Protocol:
    name = "abstract"
    sampling_target = "uniform"

    def __init__(self, ctx: "Context"):
        self.ctx = ctx
        self.rng = ctx.rng
        self.cfg = ctx.config
        self.me = ctx.node_id

    def bootstrap(self, peers: list[int], initial: bool) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        pass

    def on_message(self, sender: int, kind: str, body: Any) -> None:
        pass

    def on_timer(self, kind: str, data: Any) -> None:
        pass

    def request_sample(self, token: int) -> None:
        peers = self.sample_pool()
        self.ctx.complete(token, self.rng.choice(peers) if peers else None)

    def sample_pool(self) -> list[int]:
        return sorted(self.neighbors())

    def neighbors(self) -> set[int]:
        raise NotImplementedError

    def state_size(self) -> int:
        """Number of stored peer descriptors (including duplicate sample slots)."""
        return len(self.neighbors())


REGISTRY: dict[str, type[Protocol]] = {}


def register(cls):
    if cls.name in REGISTRY:
        raise ValueError(f"duplicate algorithm: {cls.name}")
    REGISTRY[cls.name] = cls
    return cls


def choose(rng, values, count):
    values = sorted(values)
    return rng.sample(values, min(count, len(values)))
