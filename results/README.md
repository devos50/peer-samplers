# Saved experiment results

Start with the [hosted interactive reports](https://devos50.github.io/peer-samplers/) or [scale-study.html](scale-study.html), the cross-population report for the completed 990-run study. For offline use, clone or download the repository and open the HTML in a browser; GitHub's file viewer shows the HTML source.

| Path | Contents |
|---|---|
| `peerswap-budget/` | Minimal PeerSwap repair versus four tuned baselines under common traffic/retained-descriptor ceilings: 720 tuning runs and 600 held-out runs. Includes [findings](peerswap-budget/README.md), [interactive report](peerswap-budget/report.html), frozen selections, and all raw checkpoints. |
| `scaled/` | Final study: 80, 250, and 1,000 peers; 400 rounds; ten seeds; eleven algorithm variants; static, churn, and crash scenarios. All 990 runs completed, with 125,818,000 measured requests accounted for. |
| `scaled/summary.csv` | Aggregate scores and Student t 95% intervals across seeds. |
| `scaled/paired_comparisons.csv` | Matched-seed comparisons, confidence intervals, and win/tie counts. Intervals have no multiple-comparison correction. |
| `scaled/run_metrics.csv` | Per-run scores. |
| `scaled/runs/*.json.gz` | All 990 compressed raw run checkpoints, including configurations and trace digests. |
| `scaled/*-peers-400-rounds*/` | Per-population HTML reports, full JSON exports, and CSV summaries/time series. |
| `scaled/jobs.json`, `scaled/manifest.json`, `scaled/status.json` | Replay configurations, implementation/provenance metadata, and completion status. |
| `scale-provenance/` | Prior SCAMP implementation and exact-replay receipt supporting reuse of checkpoints after caching sorted local views. |
| `comparison/` | Original 99-run comparison: 80 peers, 80 rounds, three seeds, eleven variants, three scenarios. |
| `scale-pilot/` | Eight operational pilot runs. These are separate from the final study. |
| `large/` | Earlier, interrupted expanded batch. Its retained checkpoints were incorporated into `scaled/`; this directory is incomplete and superseded. |
| `large-control/` | Earlier completed 330-run control batch, also incorporated into `scaled/`. Retained for provenance; do not count it again as independent evidence. |

The root [README](../README.md#larger-resumable-experiments) documents how to replay and analyze the study. Some preserved operational provenance records contain paths from the original machine; the corresponding files are included here under the same repository-relative paths.

Interpret rankings within the documented simulation variants. In particular, SCAMP's lease renewal can inflate long-run views, and BASALT's hierarchical address target differs from uniform identity sampling. Global uniformity, local temporal diversity, successful sampling, and overlay connectivity measure different properties.
