from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class Config:
    nodes: int = 100
    rounds: int = 100
    warmup: int = 20
    seed: int = 1
    view_size: int = 12
    exchange_size: int = 6
    active_size: int = 4
    samples_per_node: int = 1
    churn: float = 0.02
    crash_fraction: float = 0.5
    crash_round: int = 50
    scenario: str = "static"
    topology: str = "random"
    latency: float = 0.02
    loss: float = 0.0
    timeout: float = 0.4
    sample_timeout: float = 2.0
    walk_length: int = 8
    lease_rounds: int = 20
    scamp_c: int = 1
    header_bytes: int = 32
    observation_interval: int = 5
    bootstrap_size: int = 1
    maintenance_interval: int = 1
    peerswap_rate: float = 0.5
    peerswap_reserve: int = 8
    peerswap_repair_attempts: int = 1
    basalt_refresh: int = 0
    address_groups: int = 8

    def __post_init__(self):
        positive = ("nodes", "rounds", "view_size", "exchange_size", "active_size",
                    "walk_length", "lease_rounds", "observation_interval", "bootstrap_size",
                    "address_groups", "maintenance_interval", "peerswap_repair_attempts")
        for name in positive:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("samples_per_node", "scamp_c", "header_bytes", "basalt_refresh",
                     "peerswap_reserve"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.nodes < 2 or not 0 <= self.warmup < self.rounds:
            raise ValueError("need nodes >= 2 and 0 <= warmup < rounds")
        for name in ("warmup", "crash_round", "seed"):
            if not isinstance(getattr(self, name), int) or isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be an integer")
        if self.address_groups > 200:
            raise ValueError("address_groups must be <= 200 for unique synthetic IPv4 addresses")
        if self.exchange_size > self.view_size or self.active_size > self.view_size:
            raise ValueError("exchange_size and active_size must be <= view_size")
        for name in ("churn", "crash_fraction", "loss"):
            if not math.isfinite(getattr(self, name)) or not 0 <= getattr(self, name) < 1:
                raise ValueError(f"{name} must be in [0, 1)")
        for name in ("latency", "timeout", "sample_timeout", "peerswap_rate"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.latency * 2 >= self.timeout:
            raise ValueError("timeout must exceed a message round trip (2 * latency)")
        if self.timeout >= 0.8:
            raise ValueError("timeout must be < 0.8 round for round-based exchanges")
        if self.scenario not in ("static", "churn", "crash", "mixed"):
            raise ValueError("unknown scenario")
        if self.topology not in ("random", "ring", "star"):
            raise ValueError("unknown topology")
        if self.scenario in ("crash", "mixed") and not 0 <= self.crash_round < self.rounds:
            raise ValueError("crash_round must be inside the experiment")

    def to_dict(self):
        return asdict(self)
