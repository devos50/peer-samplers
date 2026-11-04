# PeerSwap repair recovery after churn stops

PeerSwap-repair can have a conditional recovery guarantee with a small graph-level change: replace opportunistic edge replacement with validated merges of distinct connected components. With persistent discovery, safe transactions, and a degree cap of at least two, the merge rule below reaches a connected graph after exactly one fewer successful merges than the initial number of components. Subsequent ideal PeerSwap swaps converge to uniform sampling.

This is a mathematical guarantee for a **proposed abstract protocol**, with a proof below. It is not a theorem about the current message-driven implementation. The distributed certification, transaction, discovery, and scheduling requirements are substantive implementation obligations. The existing experiments continue to describe the unchanged `peerswap_repair` implementation.

## Why the current repair rule cannot guarantee recovery

The obstruction is stronger than losing every contact to another component. In [`start_repairs`](../peer_sim/algorithms/peerswap_repair.py), a full view causes an immediate return, even if the reserve contains external contacts and `damaged` is true. Consider degree cap two and two disjoint triangles. Every peer has two live neighbors and can know all three peers in the other triangle, yet no peer initiates repair. Ordinary PeerSwap swaps preserve the components. For a peer in either triangle, the total variation distance from a uniform sample over all five other peers is at least

$$
1-\frac{2}{5}=\frac{3}{5}.
$$

This state is reachable after finite churn: start with the cycle `0–1–2–6–3–4–5–7–0`, remove peers 6 and 7, and let each surviving three-peer path close internally into a triangle. A favorable internal-repair schedule suffices; the example does not require continued failures.

The checker reproduces this connected-start execution with seed 1 and also a degree-cap-four case with seed 9: a single crash leaves two full five-peer cliques, with live cross-component contacts still in reserves. Both run for 100 rounds with no further membership changes. The cap-four obstruction therefore also applies to the active-view capacity selected in the matched-budget study.

The isolated admission rule has a second obstruction. With path `a–b–c`, cap two, and isolated peer `s`, accepting `s` at `b` by dropping `a–b` isolates `a`. Moving isolation is not a decreasing recovery measure. Removing an arbitrary edge can split a healthy component.

Two limits apply to any proposed replacement:

- Without an address discovery mechanism, components with no cross-component addresses or messages cannot discover one another. Protecting a contact that survives is different from guaranteeing that such a contact survives arbitrary failures.
- Maximum degree one cannot connect more than two peers. The theorem therefore requires a common cap $d\geq2$.

## Post-churn model and required services

Fix a finite surviving set $U$, with $|U|=n\geq2$. Let $T_0$ start the post-churn, post-reconciliation model. All joins and departures have stopped. At $T_0$, the committed sampling graph $G_0$ is simple and undirected, contains exactly these live peers, and has maximum degree at most $d$. It can be disconnected and irregular. Cleanup before $T_0$ may have removed edges; connectivity is not a cleanup premise.

The recovery theorem uses these explicit requirements:

1. **Stable failure handling.** After $T_0$, live peers are not incorrectly removed, dead descriptors cannot reappear, and old messages cannot overwrite a newer topology. Eventual delivery with retransmission and eventual accuracy of failure detection are sufficient environmental ingredients; stopping churn alone does not provide them. Adaptive timeouts under eventual synchrony are one implementation route. Fixed timeouts with indefinitely recurring packet loss do not establish this property.
2. **Persistent cross-component discovery.** While the sampling graph is disconnected, a contact across its components is eventually proposed. One sufficient realization is a fixed connected undirected discovery graph $D$ on $U$, whose edges represent retained, callable contacts in at least one direction, with every such contact retried fairly. Another is a continuing introducer service with eventual coverage. Discovery need not be uniform. A bounded, evictable cache is not by itself a proof of this requirement.
3. **Validated atomic merges with progress.** A merge commits only between two currently distinct components, using current free-capacity and cycle certificates. Its graph update is atomic at the abstract level. Concurrent operations are serializable, and discovery, certification, and commit scheduling cannot starve all eligible merges. Under randomized retries, the progress condition must hold almost surely.
4. **Restricted topology changes.** After reconciliation, the only graph changes are the merges below and complete PeerSwap swaps within components. In particular, no delayed drop, unconditional degree-filling operation, or partial swap can split a component. Same-component discovery does not change the graph.

Requirement 1 is an explicit failure-model assumption, in the tradition of separating completeness and accuracy in [failure-detector models](https://ecommons.cornell.edu/entities/publication/857e9f05-31bf-47ea-b434-dc4e8e3007d1); the cited work does not prove this repair protocol. Requirements 2 and 3 are service contracts to implement and verify, not access to the simulator's global membership or component observer.

## A merge rule that respects the degree cap

For a connected component $C$, find one of these two resources:

- A **free vertex** $u\in C$, with $\deg(u)<d$.
- If no free vertex exists, an edge $\{u,v\}$ on a cycle in $C$. Removing this edge leaves $C$ connected; such an edge is called a non-bridge.

At least one resource always exists. If there is no free vertex, every vertex has degree $d\geq2$. A finite graph with minimum degree at least two contains a cycle. Thus the full component has a non-bridge edge. This argument includes odd degree caps; an arbitrary edge of a full component need not be a non-bridge.

For **distinct** connected components $A$ and $B$, use the following rule. Named vertices in different components are necessarily distinct, and proposed cross edges do not already exist.

| Available resources | Atomic update |
| --- | --- |
| Free vertices $u\in A$, $x\in B$ | Add $\{u,x\}$. |
| Non-bridge $\{u,v\}$ in full $A$, free vertex $x\in B$ | Remove $\{u,v\}$, add $\{u,x\}$. Either endpoint of the removed edge can be used. |
| Non-bridges $\{u,v\}$ in full $A$, $\{x,y\}$ in full $B$ | Remove both edges; add $\{u,x\}$ and $\{v,y\}$. Either cross pairing works. |

The symmetric full/free case uses the second row with the components exchanged. A singleton always has free capacity, so no separate singleton rule is necessary.

**Merge lemma.** Each update produces a simple undirected graph, preserves the degree cap, and replaces exactly the two old components with one connected component.

**Proof.** In the first case, the added edge connects the components and consumes one free slot at each endpoint. In the second case, deleting a non-bridge leaves $A$ connected, and the added edge connects it to $B$. Vertex $u$ has unchanged degree, $v$ loses one, and $x$ uses its free slot. In the third case, each old component remains connected after its deletion; either cross edge connects the two, and each of the four endpoints loses and gains one edge. Other vertices are unchanged. Cross edges cannot create loops or duplicates. No other component is affected. ∎

The rule is conservative. A two-edge switch can also merge components when just one removed edge is a non-bridge. But removing a bridge from each component cannot merge them: the deletions create four pieces, and two cross edges leave two components. In particular, rewiring two separate edges produces two separate edges. This is why a blind degree-preserving switch is insufficient.

## Recovery theorem and its proof

**Theorem.** Under requirements 1–4, starting with $k_0$ connected components, the proposed protocol reaches a connected graph after exactly $k_0-1$ successful merges. Connectivity and the maximum-degree bound then persist. The time to connectivity is finite under eventual progress, or almost surely finite under almost-sure randomized progress.

**Proof.** Let $K$ be the number of connected components. Complete PeerSwap swaps relabel the graph within an existing component and leave $K$ unchanged. Each successful merge decreases $K$ by exactly one by the merge lemma. Thus $K$ never increases and is bounded below by one.

Whenever $K>1$, requirement 2 eventually supplies a cross-component proposal. For its discovery-graph realization, connectedness of $D$ guarantees a discovery edge crossing two current sampling components. Fair certification and commit eventually merge a pair. There are only $k_0-1$ decreases before $K=1$, so repeated progress reaches connectivity in finite time. For randomized progress, each of these finitely many waiting times is finite almost surely. Once connected, no distinct component pair exists, so no further merge can commit. Remaining complete swaps preserve connectedness and the degree cap. ∎

This provides **structural quiescence**: repair stops changing the graph even if discovery probes continue. Nodes do not need to know that the last failure has occurred or that the whole population is connected. However, validating that a particular proposed merge is between distinct components remains a real distributed task.

Fairness alone gives no useful numerical recovery-time bound. For a quantitative result, assume every window of length $w$, conditional on all history and still being disconnected at its start, has probability at least $p>0$ of a successful merge. Writing $\tau_c$ for the first connected time, additive drift gives

$$
\mathbb E[\tau_c-T_0]\leq \frac{w(k_0-1)}{p}.
$$

Independence between windows is unnecessary. The lower bound $p$ must cover discovery, certificate acquisition, contention, and successful commit. It is an additional assumption, not a parameter established by the current experiments. Cleanup before $T_0$, and any later handoff or draining delay, must be counted separately.

## Uniform sampling after recovery

The original [PeerSwap analysis](https://arxiv.org/html/2408.03829v2) treats atomic swaps with independent edge Poisson clocks on a fixed underlying graph. The authors' [Lean formalization](https://github.com/sacs-epfl/peerswap/blob/c562d64e2f35b89ddab05b0255ade1f528298187/lean/README.md) proves qualitative convergence for connected simple graphs, including irregular ones, and explicitly excludes verification of the distributed handlers and delay adaptation.

For the following theorem, require a further **sampling-phase contract**. From a finite stopping time $\tau\geq\tau_c$, all old topology-changing work has resolved, and swaps follow the ideal atomic process with fresh independent rate-$\alpha>0$ edge clocks. Discovery and rejected merge proposals do not alter its generator. The handoff must depend only on observed past and present state; it cannot be defined by knowing the future last failed transaction. In the ideal model with no pending work, take $\tau=\tau_c$.

**Convergence theorem.** Under the recovery theorem and the sampling-phase contract, for every fixed surviving requester $v$, a uniform draw from its current neighbors satisfies

$$
\lim_{t\to\infty} d_{\rm TV}\!\left(
\mathcal L(S_v(t)),\operatorname{Unif}(U\setminus\{v\})
\right)=0.
$$

**Proof.** Condition on the complete history at $\tau$, including the final connected underlying graph $H$ and the initial placement of peer labels on its vertices. Subsequent swaps are an interchange process on $H$. Each edge transposition has the same rate as its reverse, so the uniform distribution on all $n!$ placements is stationary. Edge transpositions on a connected graph generate all permutations, so this finite continuous-time chain is irreducible and converges to that distribution.

At a uniform placement, condition on the position of requester $v$. The other labels are uniformly assigned to the other positions. Choosing one of the requester's neighboring positions independently of those labels therefore yields each other peer with probability $1/(n-1)$, regardless of the degree of the requester's position. Convergence of placements implies convergence of this observation. ∎

To justify removing the conditioning on a random recovery graph and time, define $D_{n,d,\alpha}(s)$ as the worst total variation distance of the placement chain from uniform after elapsed time at least $s$, over all connected simple graphs on these $n$ vertices with maximum degree at most $d$, and all initial placements. There are finitely many such graphs and placements, so $D_{n,d,\alpha}(s)\to0$. Observation cannot increase total variation distance. For deterministic $t$ and $s\geq0$,

$$
d_{\rm TV}\!\left(\mathcal L(S_v(t)),\operatorname{Unif}(U\setminus\{v\})\right)
\leq \Pr[\tau>t-s]+D_{n,d,\alpha}(s).
$$

Before $\tau$, allow an empty or failed sample as an extra outcome with zero target probability. Its contribution is included in the recovery-tail term. Conditioning on $\tau\leq t-s$ does not restrict future fresh clock draws. Almost-sure finite recovery and mixing make both terms vanish by first choosing sufficiently large $s$, then sufficiently large $t$.

Ordered samples of $b$ distinct peers have the analogous result if $b$ is at most the minimum degree of every possible recovered graph. Our merge rule guarantees only connectedness, hence minimum degree one for $n\geq2$; it does not automatically guarantee larger batch sizes. The single-peer case matches this simulator's sampling interface. Convergence concerns a sample at a deterministic observation time, or an independent observation schedule, not arbitrary state-dependent stopping times or independence between successive samples.

There is no fast-mixing claim here. The recovered graph can have a narrow bottleneck, and ordinary PeerSwap preserves that shape. Connectivity is enough for asymptotic uniformity, but an expansion guarantee or additional topology design would be needed for a useful polylogarithmic mixing bound.

## Making the recovery phase finish

A finite set of discovery tasks gives a concrete abstract route to quiescence. In a stable recovery epoch, retain a finite connected discovery graph $D$. Assign one task to a known endpoint of each discovery edge $\{u,v\}$. A task either certifies that $u$ and $v$ are already in the same sampling component, or commits a merge of their components. It then finishes permanently for that epoch. Tasks must be retried until completion, even if both active views are full.

Completion remains valid because permitted swaps and merges never separate two already connected peers. Every unfinished task eventually completes under the certification and scheduling contracts, so finitely many tasks finish in finite time. Once all are done, the endpoints of every edge of connected $D$ lie in a common sampling component, implying global connectivity. After finite outstanding messages drain, recovery no longer takes locks or changes topology. No individual node needs to detect that every other task has finished.

With $m=|E(D)|$ tasks and conditional probability at least $q>0$ of finishing an outstanding task in each length-$w$ window while tasks remain, expected task completion time is at most $wm/q$. This includes same-component checks and is separate from the $w(k_0-1)/p$ connectivity bound. Final draining time is additional.

This construction requires correct initialization and invalidation of tasks when a new churn epoch occurs. A task completed before a crash is not a permanent connectivity certificate. Establishing a stable recovery epoch, rejecting old-epoch messages, and ensuring all affected tasks are restarted are implementation obligations. The construction does not assume nodes can predict the final crash. It also does not by itself prove that the subsequent message-driven swap scheduler has the required sampling law.

## Protocol changes and remaining implementation obligations

| Area | Required change from the current implementation | What needs verification |
| --- | --- | --- |
| Discovery | Probe or refresh recovery contacts even when the active view is full; retain designated discovery contacts or use a continuing introducer. | Cross-component discovery survives the allowed failure pattern and cannot be starved or silently evicted. |
| Merge trigger | Replace degree-deficit-only repair with proposals to join certified distinct components. | Full disconnected components can make progress. Same-component proposals cannot alter topology indefinitely. |
| Edge choice | Find a free vertex, or a current cycle edge when a component is full; use the merge table. | Cycle and free-slot witnesses remain valid at commit. No arbitrary live bridge is evicted. |
| Transactions | Version edges and membership incarnations; reserve slots; make commit decisions idempotent and retransmittable; reject stale epochs. Reconcile pre-stability transactions. | A merge or swap has an all-or-nothing logical effect. Sampling and topology queries do not observe an incompatible partial commit. Losing a reply cannot leave permanent asymmetry. |
| Certification | Establish current component identity and a free-slot or cycle witness using protocol messages. | Different cached leader IDs are not sufficient: they may be stale after a merge. Certification is complete and safe under concurrent swaps and merges. |
| Stable operation | Stop degree filling and other structural rewiring once only one component remains; continuing probes must leave the sampling process valid. | Connectivity is absorbing. No stale timeout or delayed disconnect can undo it. |
| Swap scheduling | Establish the ideal sampling-phase contract, or prove a separate stationary-uniform result for the actual scheduler. | Message locks, collision rejection, and variable transaction duration do not introduce label-dependent residence-time bias. |

A conservative implementation can temporarily serialize recovery work in the involved components, run an exploration/echo over their current edges to identify components and free capacity, and find a cycle when full. A spanning-tree exploration plus a non-tree edge supplies a cycle witness. The relevant topology must remain locked or its versions revalidated until commit. Component labels and certificates need refresh after a merge; competing explorations need a progress rule. This is a design route, not a completed distributed certification algorithm.

An exploration or cycle witness must not become a permanent sampling backbone whose edges are excluded from PeerSwap swaps. Such pinned peer identities would invalidate the interchange argument. A separate control overlay is possible, but its descriptors and traffic must be accounted for separately and must not constrain the sampling graph's swaps.

Linearizability alone also does not establish the Poisson timing law. A symmetric embedded sequence of successful swaps can still have biased wall-clock observations if some placements have longer holding times. An alternative proof can use a continuous-time placement chain with symmetric forward/reverse transition rates and irreducibility; for a scheduler with locks and history, this requires analysis of the enlarged state and its stationary marginal. Existing exact-replay tests do not discharge that obligation.

The merge lemma preserves active degree $\leq d$, not the existing study's entire memory budget. Retaining at most $r$ discovery descriptors gives at most $d+r$ active-plus-discovery slots, but certificate parents, leaders, witnesses, queued candidates, and commit records require explicit accounting. Component searches can take work proportional to a component's size. Recovery traffic, continuing discovery, and any changes to swap scheduling must be remeasured before making another matched-budget performance claim.

## Validation and next implementation target

[`scripts/check_recovery_lemmas.py`](../scripts/check_recovery_lemmas.py) exhaustively checks the merge rule on small labeled graphs and includes the current full-triangle obstruction. These checks complement the general proof; they do not prove a distributed implementation, liveness under arbitrary scheduling, or novelty.

Run the checks with:

```bash
python3 scripts/check_recovery_lemmas.py --max-n 6 --protocol-fixture
```

The enumeration covers 33,867 labeled graphs through six vertices, including 5,351 with exactly two components. Across 15,192 relevant graph/cap combinations, all 75,647 legal merge choices connect the components within the cap. A separate enumeration of 6,126 arbitrary two-edge switches confirms that merging succeeds exactly when at least one removed edge is a non-bridge.

The first implementation target should be a separate recovery variant with explicit discovery and transaction contracts, followed by adversarial schedules covering full disconnected components, trees, singletons, stale component certificates, lost acknowledgements, and delayed pre-recovery messages. Preserve the existing variant and saved experiments as the empirical baseline. A complete code-level theorem requires discharging the certification and timing obligations above; the graph merge and conditional convergence arguments are already available.
