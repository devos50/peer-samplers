# PeerSwap repair and matched-budget comparison

This study compares `peerswap_repair` with the existing `cyclon`, `newscast`, `hyparview`, and `peerswap` implementations. It evaluates a minimal repair mechanism; it does not establish novelty or a new uniformity theorem. The original `peerswap.py` implementation is unchanged.

## Protocol

The new variant retains PeerSwap's swap transactions and learns a bounded reserve from already exchanged neighborhood lists. A separate repair RNG randomizes ties in reserve updates without changing the original swap/sampling RNG stream. In reliable static runs, the variant reproduces the original's samples, traffic, and graph evolution exactly.

Existing pings check whether an edge is reciprocal. Timeouts or confirmed asymmetry remove the descriptor and enable repair. Newcomers also start in repair mode. A maintenance tick attempts at most `peerswap_repair_attempts` admissions, using locally learned reserve contacts. The target degree is `view_size`; the reserve capacity is `peerswap_reserve`. Underfull initial graphs remain unchanged until damage or a join occurs.

Admissions respect swap locks and reserve capacity for outstanding connections. An isolated requester may displace one edge at a full introducer; a counted disconnect tells the displaced node to repair. Lost replies and partial commits are detected by later reciprocal checks. Negative swap acknowledgments abort instead of being counted as successful swaps. Nodes with no surviving known contacts cannot discover a disconnected component without an external introducer.

This is local recovery, not atomic commit. Repairs can change the graph's structure and sampling distribution. No claim of connectivity or uniformity under arbitrary churn follows from the static PeerSwap theorem. The baseline is the simulator's existing PeerSwap variant, including its documented join and timeout adaptations, rather than an exact reproduction of a fault-tolerant paper protocol.

The [post-churn recovery analysis](peerswap-recovery-guarantee.md) gives a counterexample to guaranteed recovery in this implementation, then derives a conditional connectivity and uniformity guarantee for a proposed component-merge extension. That extension has not been implemented or included in these results.

Wire-format choices also matter: this simulator's coordinator prepare/apply/ack exchange carries full neighborhood lists, whereas the [author implementation](https://github.com/sacs-epfl/peerswap/blob/c562d64e2f35b89ddab05b0255ade1f528298187/peerswap/simulation_lock.py) uses symmetric endpoint exchanges and smaller neighbor replacement messages. Communication rankings here apply to these simulator implementations, not a definitive comparison against the author's packet costs.

## Resource contract

| Regime | Retained membership descriptors per peer | Bytes per live peer per round |
|---|---:|---:|
| Small | 16 | 512 |
| Large | 32 | 2,048 |

Both limits are ceilings, not requirements to waste unused capacity. Descriptor counts include routing and reserve/passive/history entries. The maximum is checked after every bootstrap, tick, message, timer, and sample callback, including warmup and the final drain. Temporary allocations within callbacks, transaction snapshots, pending RPC/control buffers, and runtime memory are excluded: this is a retained-membership-memory comparison, not equal total RAM.

Traffic includes all attempted maintenance, sampling, bootstrap, and repair messages, including loss and dead targets. The unit is modeled compact-JSON UTF-8 bytes plus the configured header. The cost ceiling applies to each run's measured total divided by live-node rounds, not to each individual peer or instantaneous burst. Post-run drain traffic is charged. The initial warmup's traffic is excluded, consistently for all methods. Explicit repair-message bytes are reported separately; reserve learning and reciprocal checks piggyback on existing, fully counted messages.

The original PeerSwap can grow beyond its initial degree through joins. Its graph is not truncated to make it pass the cap. A configuration that exceeds either limit is marked out of budget, and its quality scores are diagnostic rather than a matched-budget win.

## Tuning and evaluation

All candidates receive the exact same explicit workload for a given population, scenario, and seed, including the initial degree-at-most-four graph, departures, joins, and bootstrap contacts. Protocol view capacities never change the workload-generation RNG stream.

Each method receives 16 candidate configurations. CYCLON varies cache size, exchange size, and maintenance interval; Newscast varies cache size and interval; HyParView varies active/passive capacity, shuffle size, and interval; original PeerSwap varies swap-clock rate and ping interval; the repair variant varies routing/reserve allocation, swap-clock rate, and interval. The full grid is saved before execution.

Tuning uses 160 peers, 160 rounds, 32 warmup rounds, seeds 201–203, and static/churn/crash scenarios: 720 runs. One configuration per method and resource regime is frozen across all scenarios. It must satisfy the memory ceiling and at most 85% of the traffic ceiling in every tuning run, leaving headroom for larger populations and longer runs.

Among eligible candidates, selection minimizes the mean of `(1 - live_sample_rate) + live_sample_rate * global_TV`, with lower mean traffic and then candidate ID breaking ties. This is an availability/global-uniformity surrogate, not an exact TV distance for outcomes including failures. Local temporal diversity is a separate diagnostic and is not optimized by this rule. The full candidate scores and nondominated frontier are retained. If no candidate qualifies, a clearly labeled diagnostic candidate is evaluated rather than silently relaxing the contract.

Held-out evaluation uses 250 and 1,000 peers, 400 rounds, 80 warmup rounds, seeds 301–310, and the same three scenarios: 600 runs. Steady churn replaces peers independently with probability 2% per round; the crash removes 50% at round 200. Each configuration's traffic and descriptor limits are checked again on every evaluation run. A group is labeled matched only if it qualified during tuning and all ten evaluation seeds fit both ceilings. No held-out retuning is allowed.

Reports show conditional global uniformity, local TV excess over a matched IID reference, live and final-quarter sampling rates, overlay connectivity, stale descriptors, traffic, state, and crash recovery. Student t 95% intervals are across seeds. Paired comparisons use identical membership traces; intervals are exploratory with no multiple-comparison correction. Recovery means are conditional on observed recovery, with recovery fractions reported separately.

## Reproduction

```bash
python3 scripts/budget_experiments.py prepare
python3 scripts/scale_experiments.py --jobs results/peerswap-budget/tuning-jobs.json \
  --output results/peerswap-budget/tuning --workers 8
python3 scripts/budget_experiments.py select
python3 scripts/scale_experiments.py --jobs results/peerswap-budget/evaluation-jobs.json \
  --output results/peerswap-budget/evaluation --workers 8
python3 scripts/budget_experiments.py analyze
python3 scripts/budget_report.py --analysis results/peerswap-budget/analysis.json \
  --output results/peerswap-budget/report.html
```

The plan freezes simulator and experiment-harness digests. Selection and analysis validate the complete prespecified job matrix, exact configurations, trace digests, and request accounting. Gzip checkpoints preserve every raw run. Use the source revision recorded with a study to resume it; historical studies from earlier simulator revisions remain available but cannot be mixed with new code.
