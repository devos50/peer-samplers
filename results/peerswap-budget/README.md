# PeerSwap repair: completed matched-budget study

Open the [interactive report](report.html), also [hosted on GitHub Pages](https://devos50.github.io/peer-samplers/results/peerswap-budget/report.html). The [methodology](../../docs/peerswap-budget-study.md) defines the protocol, resource contract, tuning grid, and reproduction commands.

The study completed 720 tuning runs and 600 held-out runs. Evaluation used 250 and 1,000 peers, 400 rounds, ten new seeds, and static/churn/crash scenarios, accounting for **107,500,000 measured requests**. All 60 evaluation groups passed both resource ceilings on all ten seeds. The ceilings were 16 retained membership descriptors plus 512 bytes/live-peer/round, or 32 descriptors plus 2,048 bytes/live-peer/round. These are common ceilings, not equal measured usage; transient control buffers and total RAM are excluded.

## Findings

Repair substantially improves the existing simulator PeerSwap's sustained-churn availability and connectivity. It does not become the best overall sampler in this experiment. At 1,000 peers with 2% churn per round, under the smaller ceiling:

| Method | Live samples | Global TV ↓ | Local TV excess ↓ | Bytes/live-peer/round ↓ | Final largest SCC | Peak retained descriptors |
|---|---:|---:|---:|---:|---:|---:|
| CYCLON | 95.99% | 0.0666 | 0.00320 | 186.2 | 99.18% | 4 |
| Newscast | 96.53% | 0.0750 | 0.01402 | 378.3 | 5.18% | 8 |
| HyParView | 98.68% | 0.0433 | 0.02432 | 422.7 | 3.64% | 8 |
| PeerSwap, original simulator implementation | 77.25% | 0.2225 | 0.02027 | 154.6 | 1.20% | 9 |
| PeerSwap with repair | 95.31% | 0.0789 | 0.02142 | 336.6 | 99.08% | 16 |

Means are across ten seeds; the last column is the maximum across all seeds and callbacks. Full seed intervals and paired differences are in the report and CSVs.

Relative to original PeerSwap, repair raises live sampling by **18.06 percentage points** (paired Student t 95% interval **17.62–18.49**) and reduces global TV by **0.14366** (interval **0.14093–0.14640**). These improvements occur in all ten matched seeds. Traffic increases by **181.90 bytes/live-peer/round**. Local TV excess increases by **0.00115**, so the global-uniformity improvement does not imply improved per-requester temporal diversity.

Under the larger ceiling, repair selects the same configuration and therefore has the same results. Original PeerSwap selects a faster swap rate; repair's availability advantage is **18.31 percentage points** (interval **17.91–18.72**). Newscast selects a 16-entry view and reaches **97.13%** availability, **99.99%** final SCC coverage, and **0.00126** local TV excess at **585.3 bytes/live-peer/round**. HyParView reaches **99.72%** availability but only **4.62%** SCC coverage. CYCLON again uses the same inexpensive four-entry configuration.

The 250-peer churn results show the same main tradeoff: repair reaches **95.33%** availability versus original PeerSwap's **77.33%** / **76.56%** under the smaller/larger ceilings. CYCLON reaches **95.90%** at **184.1 bytes/live-peer/round**, versus repair's **332.7**.

After a 50% crash at 1,000 peers, repair and CYCLON satisfy the combined recovery criterion in all ten seeds at the first qualifying observation, approximately **20 rounds** after the crash. Original PeerSwap never satisfies that criterion before the end in either regime. Recovery is observed every ten rounds and requires connectivity, stale-entry, and availability thresholds together; it is not an exact recovery timestamp.

## Interpretation

The tuning rule optimizes availability and aggregate global TV, with no connectivity constraint and no local-diversity objective. This permits fragmented overlays to score well: the selected HyParView active degree is two, and the smaller-budget Newscast has an eight-entry view. Neither is an unqualified resilience winner despite high live-sample availability. A future study can declare connectivity/local-diversity constraints before tuning; this study does not retune after observing held-out outcomes.

Static comparisons use independently selected swap rates. The extension itself reproduces original PeerSwap's static samples, traffic, and graph evolution exactly when both receive the same parameters; its passive reserve adds retained memory. Repairs alter topology under failures and have no new proved uniformity guarantee.

Communication figures describe the simulator implementations and compact JSON accounting. In particular, the original PeerSwap model's coordinator transactions differ from the author's smaller replacement-message wire format. These numbers do not establish real-network packet costs or a universal ranking of the paper protocols.

## Evidence and reproduction

| File/directory | Contents |
|---|---|
| `plan.json`, `tuning-jobs.json` | Frozen source/harness identities, budgets, candidate grid, seeds, and tuning jobs. |
| `tuning/runs/` | All 720 raw tuning checkpoints. |
| `tuning-scores.csv` | Every candidate's score, resource maxima, and nondominated-frontier flag. |
| `selection.json`, `selected-configurations.csv` | The ten frozen choices, feasibility, and selected parameters. |
| `evaluation-jobs.json`, `evaluation/runs/` | All 600 held-out jobs and raw checkpoints. |
| `summary.csv`, `run-metrics.csv`, `paired-comparisons.csv`, `analysis.json` | Complete numerical results, budget checks, and uncertainty. |
| `validation.json` | Executed validation and independent audit receipt. |

The 58-test suite passes, including repair fault injection, descriptor and traffic accounting, shared-workload isolation, training/test separation, and budget-violation handling. An independent recomputation verified all 60 summary groups and 1,680 paired comparisons, all request/byte accounting, and zero held-out budget violations. Repeated CYCLON/repair configurations under both budget labels reproduce identical core results. The interactive report passed all 156 control combinations in V8 with a DOM harness; this was not a browser visual test.
