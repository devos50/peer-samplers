# Peer sampling simulator

A dependency-free Python 3.11+ discrete-event simulator for comparing decentralized peer sampling. Eleven implementations share one transport, churn trace, sampling workload, metric evaluator, and export pipeline.

The repository includes the completed [990-run scale study](results/scale-study.html), its [summary CSV](results/scaled/summary.csv), and all raw checkpoints. Download or clone the repository and open the HTML report locally. See the [results inventory](results/README.md) for the original comparison, provenance, and earlier experiment batches.

```bash
python3 -m peer_sim --list
python3 -m peer_sim --nodes 100 --rounds 120 --seeds 1,2,3 --output results/comparison
```

Open `results/comparison/report.html` directly in a browser. It contains scenario selection, sortable seed summaries, and time-series charts. `results.json` retains raw runs and configurations; `summary.csv` contains means and uncertainty across seeds; `timeseries.csv` contains observations. No server, Python packages, CDN, or internet connection is needed to run experiments or open reports. Installation with `pip install -e .` optionally provides the `peer-sim` command.

## Algorithms

| CLI name | Implementation | Source and simulation scope |
|---|---|---|
| `cyclon` | Oldest-descriptor selection, age increments, bounded bidirectional shuffles, preferential replacement of sent entries, timeout-based removal | [CYCLON, 2005](https://www.distributed-systems.net/my-data/papers/2005.jnsm.pdf), enhanced shuffling in §2; initial graph setup and bounded bootstrap replace the paper's specialized join walks. |
| `newscast` | Timestamped descriptors, push/pull exchange, deduplication, freshest-entry retention | [Newscast Computing, 2003](https://research.vu.nl/ws/files/74857859/IR-CS-006), membership portion; timestamps use synchronized simulation time and ties are randomized. |
| `scamp` | Probabilistically forwarded subscriptions, acceptance probability `1/(view size + 1)`, inverse views, lease renewal, heartbeats, isolation resubscription | [SCAMP, 2003](https://people.maths.bris.ac.uk/~maajg/ieeetocs03-scamp.pdf), §2. Simulation variant uses explicit expiring leases, bounded subscription forwarding, and abrupt departures; omits indirection and graceful unsubscription rewiring. |
| `hyparview` | Active/passive views, priority neighbor admission, disconnect messages, forwarded joins, routed passive shuffles, failure-triggered promotion | [HyParView, 2007](https://joaoleitao.org/pdf/HyParView.pdf), §4. Counted request/reply probes stand in for TCP failure detection; active/passive walk lengths are 4/2 and shuffle TTL is 3. |
| `random_walk` | Ordinary neighbor-uniform walk on a maintained underlying graph | Baseline for [Stutzbach et al., 2006](https://conferences.sigcomm.org/imc/2006/papers/p3-stutzbach1.pdf). Every proposed hop queries the destination's neighborhood through the requesting node. |
| `metropolis_hastings` | Proposal acceptance `min(1, degree(current)/degree(proposal))`; rejected moves count as Markov steps | Same source, §§4–5. Requires undirected neighborhoods for the usual stationary-uniform argument. Query timeouts fail the request. |
| `mrwb` | Metropolized walk with a local path stack, backtracking after a failed query, and bounded retry work | Same source, §5. This is a message-driven backtracking variant; its coordinator queries are not the paper's exact network-measurement implementation. |
| `brahms` | Limited identity pushes, authenticated-by-request pull replies, push/pull/history quotas, independently seeded min-hash history samplers, periodic stale-sample probes | [Brahms, PODC 2008](https://iditkeidar.com/wp-content/uploads/files/ftp/Brahms-PODC.pdf), §3/Figures 2–3. Hashes approximate random permutations; quotas use approximately one third each; history probes rotate in batches. Requires view size ≥3. |
| `basalt` | Greedy independently seeded ranking slots, hit-counter peer selection, push/pull, round-robin sample consumption and refresh, hierarchical IP ranking | [BASALT, 2021](https://arxiv.org/pdf/2102.04063), Algorithm 1/§3.3. Synthetic address hierarchy and request-driven sample consumption; timeout removal is a churn extension. |
| `basalt_uniform` | Same BASALT machinery using uniform identity rankings | Same source, uniform-ranking variant. Useful when comparing all algorithms against the same target distribution. |
| `peerswap` | Per-edge exponential clocks, whole-neighborhood position swaps, participant locks, prepare/commit/ack messages, lease-based abort | [PeerSwap, 2024](https://arxiv.org/html/2408.03829v2), §§III/VI. Preserves graph structure in reliable, failure-free runs. Attach-on-join and timeout cleanup are experimental extensions. Partial commits under crashes/loss can damage the overlay; this simulator does not claim Byzantine or atomic-commit fault tolerance. |

These are distinct algorithm implementations with documented simulation choices, not wrappers around a common shuffling algorithm. They are intended for controlled experimentation, not a claim to reproduce every paper's published measurements. The tests validate core behaviors and invariants; they do not establish the papers' mathematical guarantees. No Byzantine attackers are included in the current workloads.

## Experiments

By default the CLI runs `static,churn,crash`. Available scenarios:

- `static`: fixed population.
- `churn`: independent per-peer departure probability each round after warmup; every departure is replaced by a fresh identity.
- `crash`: one simultaneous crash event; departed nodes are not replaced.
- `mixed`: both steady replacement churn and one crash event.

Examples:

```bash
# Failure recovery, including steady churn after a 70% crash
python3 -m peer_sim --scenarios mixed --nodes 200 --rounds 150 \
  --warmup 30 --crash-round 60 --crash-fraction 0.7 --churn 0.02 \
  --seeds 10,11,12 --output results/mixed

# Degree bias and mixing on a star, using odd-length walks
python3 -m peer_sim --algorithms random_walk,metropolis_hastings,mrwb \
  --scenarios static --topology star --walk-length 9 --output results/walks

# Transport loss, cache size, latency, sample load
python3 -m peer_sim --algorithms cyclon,newscast,hyparview \
  --loss 0.03 --latency 0.04 --timeout 0.4 --view-size 24 \
  --exchange-size 8 --samples-per-node 2 --output results/loss

# Load an experiment configuration; command-line fields take precedence
python3 -m peer_sim --config examples/experiment.json --seeds 1,2,3
```

Run `python3 -m peer_sim --help` for every configuration field. A round is a simulation time unit. Periodic ticks run at integer rounds in a seeded shuffled order; network deliveries and timers use continuous event time, and PeerSwap has separate exponential clocks. This synchronized periodic schedule is a modeling choice, not an implementation of the papers' unsynchronized clocks. Latency is fixed and identical for every message; loss is independent Bernoulli loss. RPC timeout must exceed a round trip and be below 0.8 rounds. There is no bandwidth queueing, CPU-cost model, geographic latency, transport retransmission, or NAT model. Message loss can therefore have a different effect than on a protocol implemented over reliable TCP.

Initial overlays are shared connected undirected graphs: a ring, a star, or a union of random Hamiltonian cycles (`random`). Random overlays have degree at most the requested view size, rounded down to an even bound. Tiny populations can be complete; a star can have a high-degree hub. Cache protocols enforce their bounds; walk protocols and PeerSwap retain the underlying graph rather than truncating it asymmetrically. HyParView negotiates its smaller active overlay from the initial contacts. SCAMP starts from this shared graph and then adapts view sizes through subscriptions. This initialization is part of the experiment, not a stationary distribution assumption.

The full membership/churn/bootstrap trace is generated before an algorithm runs. Each scenario/seed combination uses the same trace for every algorithm; its SHA-256 digest is exported. A join receives only `bootstrap_size` live introducers (default one); there is no automatic global reseeding of isolated nodes. Bootstrap information is charged as a message and bytes. Algorithms receive no departure notifications and learn failures through message timeouts. Node RNGs, transport RNG, workload RNG, and observer RNGs are separate. Runs are repeatable; stochastic transport events depend on each protocol's message sequence.

Per-algorithm protocol parameters can be supplied without changing the shared workload:

```bash
python3 -m peer_sim --algorithm-config examples/algorithm-config.json
```

Only protocol fields can be overridden this way. Nodes, trace, transport, sampling demand, and measurement timing remain shared. The initial graph uses the base configuration, while each exported run includes the effective protocol configuration. Equal view-size parameters do not mean equal memory: HyParView has two views and Brahms stores history slots. State-descriptor counts are exported to make this visible.

## Metrics and interpretation

Uniformity is measured against the live population at **completion time**, excluding the requester, and conditional on a live non-self result. The target adapts to membership changes. Its expected distribution is accumulated from the exact completion epochs and requester identities, rather than assuming a fixed denominator or including dead peers. This completion-time estimand is particularly relevant to asynchronous walk requests; it differs from sampling a snapshot at request time.

- **Global TV:** total variation distance of the aggregate target histogram from its exposure-weighted uniform target. `0` is ideal; `1` is maximally different.
- **Mean local TV:** TV computed separately per requester and averaged equally over requesters that returned live samples. Reveals persistent local bias that balanced global counts can conceal.
- **IID reference:** an independent ideal uniform draw for each successful result, with the same requester and live population. The local excess subtracts this reference's empirical TV. Negative values can occur through finite-sample noise; this is a diagnostic, not a significance test or proof of unbiasedness.
- **BASALT intended local TV:** additionally evaluates hierarchical BASALT against uniform `/8 → /16 → /24 → address` selection. Uniform-identity TV is still exported for comparison; intentional prefix weighting can make that score high. Synthetic addresses put approximately half the identities in one `/8` and distribute the remainder among the other configured groups.
- **Availability:** live-sample rate plus separate `dead`, `empty`, `timeout`, `self`, and `source_left` counts. All measured requests resolve to exactly one outcome; departed requesters remain in the denominator. No output is silently retried until it becomes live. A walk ending at its requester is a self outcome.
- **Churn resilience:** dead descriptors in routing views, fraction without live outgoing neighbors, and largest weak/strong component fractions over live nodes. An extra snapshot immediately after a mass crash captures damage before repair ticks run. Empty views have dead-view fraction zero, so read isolation too. Snapshot metrics use routing views; separate descriptor-state counts include passive/history storage. Component observations can catch a multi-message transaction in progress.
- **Recovery:** first observation after the crash with largest SCC ≥95%, dead routing descriptors ≤5%, and live-sample rate ≥95%. Request cohorts can straddle a crash. This is observation-granularity recovery, not exact detection time. `null` means recovery was not observed (or the scenario has no crash); `recovery_observed_fraction` prevents silently averaging away unrecovered runs.
- **Communication:** sent messages and compact-JSON UTF-8 payload bytes plus a configurable fixed header. Failed/lost sends cost traffic. Maintenance, sampling, and bootstrap channels are separate. Walk queries and replies, probes, view transfers, and PeerSwap locking/commit traffic are included. Local cache reads cost zero messages. These are comparable modeled bytes, not real packet-capture byte counts.

Warmup runs the same sampling demand but excludes its requests and sends from measurements. Outstanding requests drain for up to `sample_timeout` after the final round with membership frozen and periodic maintenance disabled. Tail messages are charged to measured cost; the denominator is live-node rounds during the measurement interval. Costs per live sample therefore include maintenance, bootstrap, failures, and drain work. Time-series request windows retain late completions; the last row may include a short final cohort. Cumulative traffic rows show sends observed at their snapshot time, whereas final totals also include drain traffic.

Short runs over large populations have substantial sampling noise. Use the IID reference, more rounds, and several independent seeds. Summary confidence half-widths use `1.96 * sample standard deviation / sqrt(seed count)` and are absent for one seed; they are approximate normal intervals and can be unreliable with very few seeds. No algorithm is declared a universal winner.

## Adding an algorithm

The extension point is `peer_sim.protocol.Protocol`, registered with `@register`. The engine does not dispatch by algorithm name. Each node gets a private instance and a `Context` exposing `node_id`, `now`, `rng`, `config`, `send`, `timer`, and `complete`. A protocol implements:

```python
from peer_sim.protocol import Protocol, register

@register
class MySampler(Protocol):
    name = "my_sampler"

    def bootstrap(self, peers, initial):
        self.view = set(peers)

    def neighbors(self):
        return set(self.view)

    # Optional: tick(), on_message(sender, kind, body), on_timer(kind, data),
    # request_sample(token), sample_pool(), state_size().
```

The default `request_sample` draws locally from `sample_pool`. An asynchronous algorithm instead calls `ctx.complete(token, peer)` once it has an answer; `None` means empty/unavailable. The engine expires unresolved requests and ignores late completions. Sampling messages use `ctx.send(..., channel="sampling")`; maintenance is the default. Message bodies must be JSON-serializable and are copied at send time. New algorithms should not reach through the context to simulator internals; this is an architectural boundary, not a security sandbox for untrusted plugins.

Put a module on Python's import path and run `python3 -m peer_sim --plugin my_module --algorithms my_sampler`. See `examples/rotating.py` for an intentionally biased sampler useful for checking the metrics. Built-ins use `RPCProtocol` for counted requests, replies, and timeout callbacks; plugins may use that helper or implement their own message patterns.

Core modules: `engine.py` (events/transport), `workload.py` (shared trace), `metrics.py` (observer), `experiment.py` (matrices/aggregation), `report.py` (exports), `algorithms/` (independent protocol implementations).

## Validation

```bash
python3 -m unittest discover -s tests -v
```

Tests include deterministic replay of every algorithm, request-outcome conservation across asynchronous windows, shared churn traces, traffic-channel conservation, payload copying and lost-send accounting, changing-population target calculations, local versus global bias, cache bounds, age/freshness rules, history duplicate invariance, BASALT counters, HyParView symmetry, PeerSwap degree/triangle/symmetry preservation, degree-bias correction, MRWB recovery, plugin extension, and the CLI/export path.

## Larger, resumable experiments

`scripts/scale_experiments.py` runs independent jobs in separate processes, writes each result as a compressed JSON checkpoint, and resumes completed jobs. A job manifest is a JSON list of objects with `tier`, `algorithm`, and `config` (a complete or partial `Config` object). The runner saves an implementation digest and refuses to mix checkpoints from different simulator versions or job manifests.

The expanded study uses 250 and 1,000 peers, 400 rounds (80 warmup), ten seeds (101–110), all eleven variants, and static/churn/crash scenarios: 660 runs. A separate 330-run control keeps the original 80-peer population with the same longer run length and ten seeds. Other protocol parameters stay at their original defaults. Observation intervals are 20 rounds, including the extra immediate crash snapshot. The crash removes 50% at round 200; steady churn remains 2% per peer per round. Late availability aggregates request cohorts whose observation times are in the final quarter of the run.

```bash
# Replay/resume the saved study; reduce workers to fit the machine.
python3 scripts/scale_experiments.py --jobs results/scaled/jobs.json \
  --output results/scaled --workers 8

# Validate all checkpoints and produce per-tier HTML/JSON/CSV reports.
python3 scripts/analyze_scale.py results/scaled --reports
python3 scripts/study_report.py --analyses results/scaled/analysis.json \
  --output results/scale-study.html
```

Analysis verifies shared trace digests and complete request accounting. `analysis.json` and `summary.csv` include Student t 95% intervals across seeds; `paired_comparisons.csv` compares algorithms on matching seeds and exact membership traces, with win/tie counts and confidence intervals for the differences. Pairwise intervals are exploratory and have no multiple-comparison correction. Recovery means are conditional on observed recovery, alongside its observed fraction. Per-run measurements remain in `run_metrics.csv` and `runs/*.json.gz`.

Inspect `final_mean_view_size` as well as sampling scores: the SCAMP lease variant can inflate its views over long static runs, because renewal uses ordinary subscriptions with extra copies and refreshes existing advertised entries. Its resulting diversity and cost should not be read as a scaling guarantee for the paper protocol. The cross-population report exposes view size to make this effect visible. The study freezes protocol behavior rather than tuning variants after seeing their scores.

The combined 990-run output is in `results/scaled`. Its manifest records the source digest of reused checkpoints and an exact-replay receipt in `results/scale-provenance`: caching SCAMP's sorted local-view order reproduced every core result field in four complete runs (80 peers in all three scenarios and a 250-peer static run). Other protocols were unchanged. A fresh output directory reruns every job with the current implementation; resuming the saved directory preserves the provenance metadata.

Bounded memoization of pure hash/ranking calculations accelerates the simulator without changing protocol messages, random choices, or metrics. Cached values contain no live-membership information or protocol objects. This is a host-side computation optimization; its memory is not part of the simulated descriptor-state metric. Regression checks compare cached hashes to an independent uncached reference, and saved BASALT/Brahms runs reproduce exactly. Worker wall time is recorded for operational planning, not used to rank algorithm communication efficiency.
