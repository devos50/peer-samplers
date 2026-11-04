"""Deterministic discrete-event transport and common experiment execution."""
from collections import Counter
import copy
import heapq
import itertools
import json
import random

from .config import Config
from .metrics import Samples, overlay_snapshot
from .protocol import REGISTRY
from .workload import Workload, make_workload


class Context:
    """Local capabilities. No online-peer list or liveness query is exposed."""
    __slots__ = ("node_id", "config", "rng", "__sim")

    def __init__(self, sim, node_id):
        self.__sim = sim
        self.node_id = node_id
        self.config = sim.config
        self.rng = random.Random(f"protocol:{sim.config.seed}:{node_id}")

    @property
    def now(self):
        return self.__sim.now

    def send(self, peer, kind, body=None, channel="maintenance"):
        self.__sim.send(self.node_id, peer, kind, body, channel)

    def timer(self, delay, kind, data=None):
        self.__sim.schedule(self.now + delay, "timer", (self.node_id, kind, copy.deepcopy(data)))

    def complete(self, token, peer):
        self.__sim.complete(self.node_id, token, peer)


class Simulation:
    def __init__(self, algorithm: str, config: Config, workload: Workload | None = None):
        from . import algorithms  # noqa: F401 - register built-in protocols
        if algorithm not in REGISTRY:
            raise ValueError(f"unknown algorithm {algorithm!r}; choose from {', '.join(REGISTRY)}")
        self.algorithm, self.config = algorithm, config
        self.workload = workload or make_workload(config)
        self.now = 0.0
        self.live = set()
        self.protocols = {}
        self.queue = []
        self.sequence = itertools.count()
        self.network_rng = random.Random(f"network:{config.seed}")
        self.traffic = Counter()
        self.measured_traffic = Counter()
        self.by_kind = Counter()
        self.measured_kind_messages = Counter()
        self.measured_kind_bytes = Counter()
        self.epoch = 0
        self.live_snapshot = frozenset()
        self.samples = Samples(config.seed + 87123)
        self.window = Samples(config.seed + 87123)
        self.pending = {}
        self.tokens = itertools.count()
        self.series = []
        self._windows = []
        self.exposure = 0.0
        self._last_exposure_time = float(config.warmup)
        # Observer bookkeeping never enters protocol state or consumes randomness.
        # Keep one scalar pair per live node; only remeasure the touched protocol.
        self._resource_values = {}
        self._resource_totals = [0, 0]
        self._resource_area = [0.0, 0.0]
        self._resource_measured_area = [0.0, 0.0]
        self._resource_peak = [0, 0]
        self._resource_measured_peak = [0, 0]
        self._resource_last_time = 0.0
        self._resource_all_exposure = 0.0
        self._resource_measurement_started = False
        self._started = False

    def schedule(self, at, event, data):
        heapq.heappush(self.queue, (at, next(self.sequence), event, data))

    def _count(self, key, amount=1):
        self.traffic[key] += amount
        if self.config.warmup <= self.now:
            self.measured_traffic[key] += amount

    def send(self, source, target, kind, body=None, channel="maintenance"):
        if channel not in ("maintenance", "sampling", "bootstrap"):
            raise ValueError(f"invalid traffic channel: {channel}")
        if source not in self.live:
            return
        wire = json.dumps([kind, body], separators=(",", ":"), sort_keys=True, allow_nan=False)
        size = self.config.header_bytes + len(wire.encode("utf-8"))
        self._count("messages_sent")
        self._count("bytes_sent", size)
        self._count(f"{channel}_messages")
        self._count(f"{channel}_bytes", size)
        self.by_kind[kind] += 1
        # Count attempted sends before loss/liveness handling. The synthetic
        # bootstrap descriptor delivery in _add remains in bootstrap_* totals.
        if self.now >= self.config.warmup:
            self.measured_kind_messages[kind] += 1
            self.measured_kind_bytes[kind] += size
        if self.network_rng.random() < self.config.loss:
            self._count("messages_lost")
            return
        self.schedule(self.now + self.config.latency, "message",
                      (source, target, kind, copy.deepcopy(body), size))

    def complete(self, source, token, peer):
        pending = self.pending.pop(token, None)
        if pending is None:
            return
        owner, started, measured, window = pending
        if owner != source:
            raise ValueError("a protocol completed another node's sample request")
        if not measured:
            return
        outcome = ("source_left" if source not in self.live else
                   "empty" if peer is None else "self" if peer == source else
                   "live" if peer in self.live else "dead")
        for metrics in (self.samples, window):
            metrics.result(source, peer, outcome, self.now - started, self.epoch, self.live_snapshot)

    def _timeout(self, token):
        pending = self.pending.pop(token, None)
        if pending and pending[2]:
            source, started, _, window = pending
            outcome = "timeout" if source in self.live else "source_left"
            for metrics in (self.samples, window):
                metrics.result(source, None, outcome, self.now - started, self.epoch, self.live_snapshot)

    def _add(self, node, peers, initial=False):
        self.live.add(node)
        protocol = REGISTRY[self.algorithm](Context(self, node))
        self.protocols[node] = protocol
        # Explicit setup cost; no free full-membership refreshes after bootstrap.
        size = self.config.header_bytes + len(json.dumps(peers, separators=(",", ":")).encode())
        self._count("bootstrap_messages")
        self._count("bootstrap_bytes", size)
        self._count("messages_sent")
        self._count("bytes_sent", size)
        self._count("messages_delivered")
        self._count("bytes_delivered", size)
        protocol.bootstrap(list(peers), initial)
        self._record_resources(node)

    def _resource_expose_until(self, at):
        """Integrate retained state between callbacks, clipped to the run horizon."""
        stop = min(at, self.config.rounds)
        start = self._resource_last_time
        if stop <= start:
            return
        elapsed = stop - start
        measured_elapsed = max(0.0, stop - max(start, self.config.warmup))
        for index, total in enumerate(self._resource_totals):
            self._resource_area[index] += total * elapsed
            self._resource_measured_area[index] += total * measured_elapsed
        self._resource_all_exposure += len(self._resource_values) * elapsed
        self._resource_last_time = stop

    def _begin_resource_measurement(self):
        # Include state carried across warmup even if a protocol never ticks again.
        # Read cached counts once at the boundary, not protocol state each event.
        if not self._resource_measurement_started and self.now >= self.config.warmup:
            self._resource_measurement_started = True
            for retained, routing in self._resource_values.values():
                self._resource_measured_peak[0] = max(self._resource_measured_peak[0], retained)
                self._resource_measured_peak[1] = max(self._resource_measured_peak[1], routing)

    def _record_resources(self, node):
        self._resource_expose_until(self.now)
        self._begin_resource_measurement()
        protocol = self.protocols[node]
        values = (protocol.state_size(), len(protocol.neighbors()))
        previous = self._resource_values.get(node, (0, 0))
        for index, value in enumerate(values):
            self._resource_totals[index] += value - previous[index]
            self._resource_peak[index] = max(self._resource_peak[index], value)
            if self.now >= self.config.warmup:
                self._resource_measured_peak[index] = max(self._resource_measured_peak[index], value)
        self._resource_values[node] = values

    def _remove_resources(self, node):
        self._resource_expose_until(self.now)
        self._begin_resource_measurement()
        previous = self._resource_values.pop(node, (0, 0))
        for index, value in enumerate(previous):
            self._resource_totals[index] -= value

    def _resource_report(self):
        self._resource_expose_until(self.config.rounds)
        return {
            "unit": "peer descriptors per node",
            "scope": "Retained protocol state reported by state_size(); includes routing, "
                     "history, reserve and passive descriptors, including duplicate slots. "
                     "Excludes transient message/RPC/control buffers and simulator memory. "
                     "Peaks are checked after every bootstrap, tick, message, timer and sample "
                     "callback, including the drain; temporary values within a callback are excluded.",
            "peak_retained_descriptors": self._resource_peak[0],
            "peak_routing_descriptors": self._resource_peak[1],
            "measured_peak_retained_descriptors": self._resource_measured_peak[0],
            "measured_peak_routing_descriptors": self._resource_measured_peak[1],
            "mean_retained_descriptors": self._resource_measured_area[0] / self.exposure if self.exposure else None,
            "mean_routing_descriptors": self._resource_measured_area[1] / self.exposure if self.exposure else None,
            "all_time_mean_retained_descriptors": self._resource_area[0] / self._resource_all_exposure if self._resource_all_exposure else None,
            "all_time_mean_routing_descriptors": self._resource_area[1] / self._resource_all_exposure if self._resource_all_exposure else None,
            "mean_interval": [self.config.warmup, self.config.rounds],
            "all_time_mean_interval": [0, self.config.rounds],
            "all_time_live_node_rounds": self._resource_all_exposure,
        }

    def _membership_epoch(self):
        self.epoch += 1
        self.live_snapshot = frozenset(self.live)

    def _expose_until(self, at):
        start = max(self._last_exposure_time, self.config.warmup)
        stop = min(at, self.config.rounds)
        if stop > start:
            self.exposure += len(self.live) * (stop - start)
        self._last_exposure_time = max(self._last_exposure_time, at)

    def _observe(self):
        row = {"time": round(self.now, 6), **overlay_snapshot(self.protocols, self.live)}
        row["traffic"] = dict(self.measured_traffic)
        self.series.append(row)
        # Keep the request cohort alive until outstanding asynchronous walks finish.
        self._windows.append((row, self.window))
        self.window = Samples(self.config.seed + 87123 + len(self.series))

    @property
    def target(self):
        return REGISTRY[self.algorithm].sampling_target

    def run(self):
        if self._started:
            raise RuntimeError("Simulation instances can only be run once")
        self._started = True
        # Instantiate all initial nodes before protocol bootstrap messages can arrive.
        for node, peers in self.workload.initial:
            self._add(node, peers, initial=True)
        self._membership_epoch()
        changes = {c.round: c for c in self.workload.changes}
        for round_ in range(self.config.rounds):
            self.schedule(float(round_), "round", (round_, changes.get(round_)))
            self.schedule(round_ + 0.75, "sample", None)
            if (round_ + 1) % self.config.observation_interval == 0:
                self.schedule(round_ + 0.99, "observe", None)
        end = self.config.rounds + self.config.sample_timeout
        while self.queue:
            at, _, event, data = heapq.heappop(self.queue)
            if at > end:
                break
            self.now = at
            self._begin_resource_measurement()
            if event == "round":
                round_, change = data
                self._expose_until(at)
                if change:
                    self.live.difference_update(change.leaving)
                    for departed in change.leaving:
                        self._remove_resources(departed)
                        self.protocols.pop(departed, None)
                    for node, seeds in change.joining:
                        self._add(node, seeds)
                    self._membership_epoch()
                    if (self.config.scenario in ("crash", "mixed") and
                            round_ == self.config.crash_round and self.config.crash_fraction > 0):
                        self._observe()  # capture damage before any repair ticks run
                # Seeded shuffle avoids systematic low-ID initiation priority.
                order = sorted(self.live)
                random.Random(f"tick:{self.config.seed}:{round_}").shuffle(order)
                for node in order:
                    if (round_ + node) % self.config.maintenance_interval == 0:
                        self.protocols[node].tick()
                        self._record_resources(node)
            elif event == "message":
                source, target, kind, body, size = data
                if target in self.live:
                    self._count("messages_delivered")
                    self._count("bytes_delivered", size)
                    self.protocols[target].on_message(source, kind, body)
                    self._record_resources(target)
                else:
                    self._count("messages_to_dead")
            elif event == "timer":
                node, kind, payload = data
                if node in self.live and at < self.config.rounds:
                    self.protocols[node].on_timer(kind, payload)
                    self._record_resources(node)
            elif event == "sample":
                for source in sorted(self.live):
                    for _ in range(self.config.samples_per_node):
                        token = next(self.tokens)
                        measured = self.now >= self.config.warmup
                        self.pending[token] = (source, self.now, measured, self.window)
                        if measured:
                            self.samples.requests += 1
                            self.window.requests += 1
                        self.schedule(self.now + self.config.sample_timeout, "deadline", token)
                        self.protocols[source].request_sample(token)
                        self._record_resources(source)
            elif event == "deadline":
                self._timeout(data)
            elif event == "observe":
                self._observe()
        self._expose_until(self.config.rounds)
        # Complete every request, including messages still outstanding at the horizon.
        for token in list(self.pending):
            self._timeout(token)
        if not self.series or self.series[-1]["time"] < self.config.rounds - 1:
            self._observe()
        for row, metrics in self._windows:
            report = metrics.report(self.target, self.config.address_groups)
            report.pop("target_histogram")
            row["samples"] = report
        final = overlay_snapshot(self.protocols, self.live)
        return {
            "algorithm": self.algorithm, "config": self.config.to_dict(),
            "workload_digest": self.workload.digest, "sampling_target": self.target,
            "samples": self.samples.report(self.target, self.config.address_groups),
            "traffic": dict(self.traffic), "measured_traffic": dict(self.measured_traffic),
            "messages_by_kind": dict(sorted(self.by_kind.items())),
            "measured_traffic_by_kind": {
                kind: {"messages": self.measured_kind_messages[kind],
                       "bytes": self.measured_kind_bytes[kind]}
                for kind in sorted(self.measured_kind_messages)
            },
            "live_node_rounds": self.exposure,
            "resource_usage": self._resource_report(),
            "bytes_per_live_node_round": self.measured_traffic["bytes_sent"] / self.exposure if self.exposure else None,
            "messages_per_live_node_round": self.measured_traffic["messages_sent"] / self.exposure if self.exposure else None,
            "bytes_per_live_sample": self.measured_traffic["bytes_sent"] / self.samples.outcomes["live"] if self.samples.outcomes["live"] else None,
            "final_overlay": final, "timeseries": self.series,
        }
