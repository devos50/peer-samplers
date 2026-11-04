#!/usr/bin/env python3
"""Build an offline interactive report from the matched-budget study analysis."""
import argparse
import json
from pathlib import Path


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PeerSwap repair: matched-budget experiments</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0d1623;color:#e7edf6;font-synthesis:none}*{box-sizing:border-box}body{max-width:1500px;margin:0 auto;padding:36px 28px 60px}h1{font-size:clamp(1.8rem,4vw,2.7rem);line-height:1.12;max-width:1000px;margin:10px 0 18px}h2{font-size:1.25rem;margin:28px 0 12px}p,li{line-height:1.65}p{color:#bac9dc}a{color:#9bd2ff;text-underline-offset:3px}a:hover{color:#fff}.eyebrow{color:#9bd2ff;font-weight:700;letter-spacing:.09em;font-size:.8rem;text-transform:uppercase}.intro{font-size:1.03rem}.panel{background:#142235;border:1px solid #33465f;border-radius:12px;padding:18px 22px;margin:22px 0}.panel p{margin:0}.notice{border-left:4px solid #edb664}.controls{display:flex;flex-wrap:wrap;gap:18px;align-items:end;margin:24px 0}label{display:flex;flex-direction:column;gap:7px;font-weight:600;font-size:.9rem}select{font:inherit;color:#edf4ff;background:#1c2d44;border:1px solid #62738c;border-radius:7px;padding:10px 12px;min-width:130px;max-width:100%}:focus-visible{outline:3px solid #9bd2ff;outline-offset:3px}.status{font-size:.72rem;font-weight:800;letter-spacing:.025em;padding:5px 7px;border-radius:4px;display:inline-block;white-space:nowrap;margin:2px 4px 2px 0}.matched{background:#164a3e;color:#a6f1d2}.invalid{background:#5b2929;color:#ffd4cb}.diagnostic{background:#533d1d;color:#ffe0a3}.muted,small{color:#a9bbd2}small{font-size:.78rem}.metric-note{min-height:3rem;margin:10px 0}.chart-box{background:#142235;border:1px solid #33465f;border-radius:12px;padding:8px;overflow:auto}svg{display:block;width:100%;min-width:670px;height:auto}svg text{fill:#d4dfef;font:13px system-ui,sans-serif}.chart-key{display:flex;gap:20px;flex-wrap:wrap;font-size:.85rem;margin:12px 0 20px}.key-dot{display:inline-block;width:10px;height:10px;background:#89c5ff;border-radius:50%;margin-right:7px}.key-square{display:inline-block;width:10px;height:10px;background:#edb664;margin-right:7px}.scroll{overflow:auto;border:1px solid #33465f;border-radius:9px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.86rem}caption{text-align:left;padding:13px 14px;color:#bac9dc;background:#142235}td,th{padding:13px 14px;border-bottom:1px solid #33465f;text-align:right;vertical-align:top;white-space:nowrap}thead th{background:#1a2a3e;color:#c4d3e7;font-size:.78rem;line-height:1.5;text-align:right}tbody th{text-align:left;font-size:.88rem}td:first-child,th:first-child{text-align:left}tr:last-child td,tr:last-child th{border-bottom:0}tr.over-budget{background:#2c2524}tr.training-bad{background:#30291f}.interval{display:block;font-size:.75rem;color:#a9bbd2;margin-top:4px}.parameters{min-width:300px;max-width:470px;white-space:normal;text-align:left}.parameters code{font-size:.75rem;display:inline-block;background:#142235;padding:3px 6px;margin:2px;border-radius:4px}.audit td{white-space:normal;min-width:120px}.audit td.parameters{min-width:300px}.downloads{display:flex;flex-wrap:wrap;gap:10px 20px;padding:0;list-style:none}.method{max-width:1050px}.method p{margin:13px 0}.hash{overflow-wrap:anywhere;font-family:ui-monospace,monospace;font-size:.73rem}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:640px){body{padding:24px 16px 40px}.panel{padding:15px}.controls{gap:14px}label{flex:1 1 42%}.metric-control{flex-basis:100%}select{width:100%}h2{margin-top:24px}}
</style>
</head>
<body>
<header>
<div class="eyebrow">Peer sampling research · resource-matched evaluation</div>
<h1>Does minimal churn repair improve PeerSwap?</h1>
<p class="intro">Compare a bounded repair extension with tuned CYCLON, Newscast, HyParView, and the existing PeerSwap implementation. Every diagnostic result stays visible when a configuration exceeds its budget.</p>
<p id="study-summary"></p>
</header>
<div class="panel notice"><p><strong>Read the budget status before comparing quality.</strong> “Matched” requires a feasible training configuration and zero evaluation runs above either resource ceiling in the selected case. “Out of budget” or “Training infeasible” results describe diagnostics and do not establish a matched-budget improvement.</p></div>
<div class="panel notice"><p><strong>Selection does not impose a connectivity constraint.</strong> High live-sample availability or low aggregate TV can coexist with a fragmented overlay. Inspect the largest strongly connected component and local sample diversity alongside availability and global uniformity.</p></div>
<div class="controls" role="group" aria-label="Experiment filters">
<label for="budget">Budget<select id="budget"></select></label>
<label for="population">Population<select id="population"></select></label>
<label for="scenario">Scenario<select id="scenario"></select></label>
<label for="metric" class="metric-control">Chart metric<select id="metric"></select></label>
</div>
<div class="panel"><p id="case-summary" aria-live="polite"></p></div>
<p id="metric-note" class="metric-note"></p>
<div id="chart" class="chart-box"></div>
<div class="chart-key"><span><span class="key-dot"></span>Matched budget</span><span><span class="key-square"></span>Diagnostic: budget or training screen failed</span><span>Error bars: Student t 95% confidence intervals across seeds</span></div>
<h2>Sampling quality and cost</h2>
<div id="results-table" class="scroll" tabindex="0" role="region" aria-label="Sampling results table; scroll horizontally for all metrics"></div>
<p class="muted">Each cell shows the mean and its 95% interval. Uniformity is conditional on a successful live, non-self result. Peak-descriptor means summarize each run’s highest per-node retained state; the budget audit below uses the maximum across all seeds.</p>
<h2>Budget audit and frozen configurations</h2>
<div id="audit-table" class="scroll" tabindex="0" role="region" aria-label="Budget audit and selected parameter table; scroll horizontally for all columns"></div>
<p class="muted">Violations count evaluation seeds exceeding either ceiling. Training maxima cover all training scenarios and seeds. A single frozen configuration is used across evaluation populations and scenarios for each method and budget.</p>
<h2>How to interpret the experiment</h2>
<div class="method">
<p id="design-note"></p>
<p><strong>Selection objective:</strong> minimize the training mean of <code>(1 − live-sample rate) + live-sample rate × global TV</code>; ties use mean traffic and then candidate ID. This combines availability with global uniformity. It does not optimize local sample diversity. “Tuned” means selected from the declared grid, not an exhaustive optimum.</p>
<p><strong>Resource scope:</strong> memory is retained membership descriptors per node, including routing, reserve, history, and passive descriptors. Peaks are checked after each protocol callback, including bootstrap and the final drain. Transient RPC state, transaction snapshots, control buffers, and runtime overhead are excluded; these are not total RAM limits. Traffic is modeled compact-JSON bytes plus a fixed header, divided by live-node rounds after warmup. All maintenance, sampling, bootstrap, lost sends, and sends to dead targets are charged. The traffic ceiling is a per-run average, not an instantaneous link-rate cap.</p>
<p><strong>Uniformity and resilience:</strong> global TV measures aggregate deviation from live-identity sampling; lower is better. Local TV excess compares empirical per-node sample diversity with a matched IID reference and is not a proof of marginal bias. Small negative excess values are possible from sampling variation. Final-quarter availability checks sustained churn. Recovery is the first observation after the crash with at least 95% in the largest strongly connected component, no more than 5% dead routing entries, and at least 95% successful samples. Recovery means and intervals include only recovered seeds; the recovered count is displayed alongside them.</p>
<p><strong>Protocol scope:</strong> original PeerSwap is the unchanged simulator baseline, including its existing experimental join and failure handling. The repair extension adds bounded local recovery and reserve state; its novelty and theoretical guarantees have not been established. Shared membership, bootstrap, and initial-graph traces prevent protocol-specific workload advantages. Settings are frozen before evaluation; failed budget checks remain visible.</p>
<p><strong>PeerSwap traffic model:</strong> this simulator uses a coordinator that sends full endpoint neighborhoods in prepare and apply messages, followed by acknowledgments. The <a href="https://github.com/sacs-epfl/peerswap/blob/c562d64e2f35b89ddab05b0255ade1f528298187/peerswap/simulation_lock.py">authors’ pinned implementation</a> exchanges neighborhoods between the two endpoints and sends small replacement messages to affected neighbors. Communication comparisons therefore apply to the simulator variants measured here, not directly to the authors’ implementation.</p>
<p><strong>Uncertainty:</strong> confidence intervals describe seed-to-seed variation. Paired comparisons use matching evaluation seeds and workloads; their intervals are exploratory and have no multiple-comparison correction. Conditional recovery comparisons can involve fewer than ten paired observations.</p>
</div>
<h2>Download the evidence</h2>
<ul class="downloads">
<li><a href="summary.csv" download>Summary CSV</a></li>
<li><a href="paired-comparisons.csv" download>Paired comparisons</a></li>
<li><a href="run-metrics.csv" download>Per-run metrics</a></li>
<li><a href="tuning-scores.csv" download>All tuning scores</a></li>
<li><a href="selected-configurations.csv" download>Selected configurations</a></li>
<li><a href="selection.json" download>Frozen selection JSON</a></li>
<li><a href="plan.json" download>Experiment plan</a></li>
<li><a href="analysis.json" download>Full analysis JSON</a></li>
</ul>
<p id="implementation" class="hash"></p>
<noscript><p>The interactive chart and tables require JavaScript. All numerical results and configuration records are available in the downloads above.</p></noscript>
<script id="data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('data').textContent);
const el=id=>document.getElementById(id);
const names={cyclon:'CYCLON',newscast:'Newscast',hyparview:'HyParView',peerswap:'PeerSwap (original)',peerswap_repair:'PeerSwap + repair'};
const algorithms=data.plan.algorithms;
const metrics=[
 ['live_sample_rate','Live-sample availability ↑','Share of all measured requests returning a live peer other than the requester. Higher is better.'],
 ['global_tv','Global TV ↓','Aggregate total-variation distance from live-identity sampling, conditional on successful results. Lower is better.'],
 ['global_tv_excess_over_iid','Global TV excess over IID ↓','Global TV minus the matched IID reference. Small negative values are possible.'],
 ['local_tv_excess_over_iid','Local TV excess over IID ↓','Empirical sample diversity over time compared with IID sampling. This does not directly test single-sample marginal uniformity.'],
 ['bytes_per_live_node_round','Bytes / live node / round ↓','All counted post-warmup traffic, including failed sends and bootstrap, divided by live-node exposure. The ceiling applies to every run.'],
 ['bytes_per_live_sample','Bytes / successful sample ↓','Total measured traffic divided by successful live, non-self samples. Lower is better.'],
 ['peak_retained_descriptors','Peak retained descriptors / node ↓','Mean across seeds of each run’s peak retained state. The ceiling is checked against every run’s peak; total RAM is not measured.'],
 ['mean_retained_descriptors','Mean retained descriptors / node ↓','Post-warmup node-time average retained membership state. The memory ceiling still uses the peak.'],
 ['final_strong_component','Final largest strongly connected component ↑','Fraction of live peers in the largest strongly connected routing component at the end. Higher is better.'],
 ['late_live_sample_rate','Final-quarter live-sample availability ↑','Availability from request cohorts in the final quarter of the run. Higher is better.'],
 ['final_dead_view_fraction','Final dead routing entries ↓','Fraction of routing descriptors pointing to peers that have left. Lower is better.'],
 ['recovery_rounds','Observed recovery rounds ↓','Conditional mean among recovered seeds only. The table reports how many seeds recovered; missing results do not mean zero recovery time.'],
 ['repair_bytes_per_live_node_round','Explicit repair bytes / live node / round ↓','Bytes from message kinds containing “repair”. This attribution excludes checks and reserve learning piggybacked on ordinary PeerSwap messages. All traffic is fully counted in the total; explicit repair bytes are not the full incremental cost versus the baseline.']
];
const percent=new Set(['live_sample_rate','late_live_sample_rate','final_strong_component','final_dead_view_fraction']);
const columns=[['live_sample_rate','Live availability'],['global_tv','Global TV'],['local_tv_excess_over_iid','Local TV excess'],['bytes_per_live_node_round','Bytes / node / round'],['peak_retained_descriptors','Peak descriptors'],['final_strong_component','Final largest SCC'],['late_live_sample_rate','Late availability'],['recovery_rounds','Recovery rounds']];
function text(tag,value,attrs={}){const n=document.createElement(tag);n.textContent=value;for(const [key,v] of Object.entries(attrs))n.setAttribute(key,v);return n;}
function option(select,value,label){const o=text('option',label);o.value=String(value);select.append(o);}
for(const b of data.plan.budgets)option(el('budget'),b.name,b.name[0].toUpperCase()+b.name.slice(1)+' · '+b.descriptors+' descriptors · '+b.bytes+' B/node/round');
for(const n of [...new Set(data.summary.map(r=>r.nodes))].sort((a,b)=>a-b))option(el('population'),n,n.toLocaleString()+' peers');
for(const s of data.plan.scenarios)option(el('scenario'),s,s==='static'?'Static':s==='churn'?'Continuous churn (2% / round)':'Crash (50% at midpoint)');
for(const [key,label] of metrics)option(el('metric'),key,label);
el('budget').value=data.plan.budgets[0].name;
el('population').value=String(Math.max(...data.summary.map(r=>r.nodes)));
el('scenario').value=data.plan.scenarios.includes('churn')?'churn':data.plan.scenarios[0];
el('metric').value='live_sample_rate';
el('study-summary').textContent=data.completed.toLocaleString()+' held-out runs · '+data.total_requests.toLocaleString()+' measured requests · '+data.plan.evaluation_rounds+' rounds · '+data.plan.evaluation_seeds.length+' fresh seeds per method, budget, population, and scenario';
const candidateCounts=algorithms.map(a=>data.plan.candidates.filter(c=>c.algorithm===a).length);
const gridText=new Set(candidateCounts).size===1?candidateCounts[0]+' configurations per method':'the published candidate grid';
el('design-note').textContent='Training evaluates '+gridText+' on '+data.plan.tuning_nodes+' peers for '+data.plan.tuning_rounds+' rounds, with seeds '+data.plan.tuning_seeds.join(', ')+', across all three scenarios. A candidate must satisfy its descriptor ceiling and at most '+(100*data.plan.traffic_tuning_fraction).toFixed(0)+'% of the traffic ceiling in every training run. This leaves '+(100*(1-data.plan.traffic_tuning_fraction)).toFixed(0)+'% traffic headroom. Evaluation uses '+data.plan.evaluation_nodes.map(n=>n.toLocaleString()).join(' and ')+' peers for '+data.plan.evaluation_rounds+' rounds (the first '+Math.floor(data.plan.evaluation_rounds/5)+' are warmup), with fresh seeds '+data.plan.evaluation_seeds[0]+'–'+data.plan.evaluation_seeds.at(-1)+'. All methods start from the same graph with degree at most '+data.plan.initial_degree_bound+'.';
el('implementation').textContent='Simulator implementation SHA-256: '+data.implementation_sha256;
function format(value,key){if(value==null||!Number.isFinite(value))return '—';if(percent.has(key))return (100*value).toFixed(2)+'%';if(key.includes('bytes'))return value.toLocaleString(undefined,{minimumFractionDigits:1,maximumFractionDigits:1});if(key.includes('descriptors')||key==='recovery_rounds')return value.toFixed(2);return value.toFixed(4);}
function appendStatus(parent,row){if(!row.training_feasible)parent.append(text('span','TRAINING INFEASIBLE',{class:'status diagnostic'}));if(row.violation_count>0)parent.append(text('span','OUT OF BUDGET',{class:'status invalid'}));if(row.matched_budget)parent.append(text('span','MATCHED',{class:'status matched'}));}
function rowClass(row){return row.violation_count>0?'over-budget':!row.training_feasible?'training-bad':'';}
function addMetric(parent,row,key){const cell=document.createElement('td'),v=row[key];if(v?.mean==null){cell.append(text('span',key==='recovery_rounds'?(row.scenario==='crash'?'Not observed':'Not applicable'):'—'));}else{cell.append(text('span',format(v.mean,key)));if(v.ci95_low!=null&&v.ci95_high!=null)cell.append(text('span','['+format(v.ci95_low,key)+', '+format(v.ci95_high,key)+']',{class:'interval'}));}if(key==='recovery_rounds'&&row.scenario==='crash')cell.append(text('span',(v?.n??0)+' / '+row.runs+' recovered',{class:'interval'}));parent.append(cell);}
function tableShell(caption,headers){const table=document.createElement('table');table.append(text('caption',caption));const head=document.createElement('thead'),tr=document.createElement('tr');for(const header of headers)tr.append(text('th',header,{scope:'col'}));head.append(tr);table.append(head);const body=document.createElement('tbody');table.append(body);return {table,body};}
function render(){const budget=data.plan.budgets.find(b=>b.name===el('budget').value),nodes=Number(el('population').value),scenario=el('scenario').value,key=el('metric').value;
 const rows=algorithms.map(a=>data.summary.find(r=>r.budget===budget.name&&r.nodes===nodes&&r.scenario===scenario&&r.algorithm===a)).filter(Boolean);
 const matched=rows.filter(r=>r.matched_budget).length,violations=rows.reduce((n,r)=>n+r.violation_count,0);
 el('case-summary').textContent=budget.descriptors+' retained descriptors per node · '+budget.bytes.toLocaleString()+' bytes per live node per round. '+matched+' / '+rows.length+' configurations match both ceilings and the training screen. '+violations+' evaluation runs exceed a ceiling; all are shown below.';
 el('metric-note').textContent=metrics.find(m=>m[0]===key)[2];
 const main=tableShell(nodes.toLocaleString()+' peers · '+scenario+' · '+budget.name+' budget · means with 95% intervals',['Algorithm','Budget status',...columns.map(c=>c[1])]);
 for(const row of rows){const tr=document.createElement('tr');tr.className=rowClass(row);tr.append(text('th',names[row.algorithm]??row.algorithm,{scope:'row'}));const status=document.createElement('td');appendStatus(status,row);tr.append(status);for(const [metric] of columns)addMetric(tr,row,metric);main.body.append(tr);}el('results-table').replaceChildren(main.table);
 const audit=tableShell('Ceilings apply to each run. Evaluation maxima include every seed.',['Algorithm','Budget status','Violating seeds','Max evaluation bytes','Max retained descriptors','Training feasibility','Frozen parameters']);audit.table.className='audit';
 for(const row of rows){const chosen=data.selected.find(s=>s.algorithm===row.algorithm&&s.budget===budget.name),tr=document.createElement('tr');tr.className=rowClass(row);tr.append(text('th',names[row.algorithm]??row.algorithm,{scope:'row'}));const status=document.createElement('td');appendStatus(status,row);tr.append(status,text('td',row.violation_count+' / '+row.runs),text('td',format(row.max_bytes,'bytes')+' / '+budget.bytes.toLocaleString()),text('td',row.max_descriptors+' / '+budget.descriptors));
  const training=document.createElement('td');training.append(text('span',(chosen?.feasible_candidates??0)+' / '+data.plan.candidates.filter(c=>c.algorithm===row.algorithm).length+' candidates fit'));if(chosen){training.append(text('span','Selected: '+chosen.candidate,{class:'interval'}),text('span','Max '+format(chosen.max_bytes,'bytes')+' bytes; '+chosen.peak_descriptors+' descriptors',{class:'interval'}));}tr.append(training);
  const params=document.createElement('td');params.className='parameters';if(chosen)for(const [k,v] of Object.entries(chosen.parameters).sort(([a],[b])=>a.localeCompare(b)))params.append(text('code',k+'='+v));tr.append(params);audit.body.append(tr);
 }el('audit-table').replaceChildren(audit.table);draw(rows,key,budget,nodes,scenario);
}
function draw(rows,key,budget,nodes,scenario){const ns='http://www.w3.org/2000/svg',svgTag=(tag,attrs={},content)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(content!=null)n.textContent=content;return n;};
 const height=110+rows.length*65,svg=svgTag('svg',{viewBox:'0 0 1120 '+height,role:'img','aria-labelledby':'chart-title chart-description'});svg.append(svgTag('title',{id:'chart-title'},metrics.find(m=>m[0]===key)[1]+' — '+nodes+' peers, '+scenario+', '+budget.name+' budget'),svgTag('desc',{id:'chart-description'},'Each row shows a mean and a 95% confidence interval. Squares indicate diagnostic results that fail training or evaluation budget checks. All values are also available in the result table.'));el('chart').replaceChildren(svg);
 const points=rows.filter(r=>r[key]?.mean!=null),ceiling=key==='bytes_per_live_node_round'?budget.bytes:key==='peak_retained_descriptors'?budget.descriptors:null;
 if(!points.length){svg.append(svgTag('text',{x:560,y:height/2,'text-anchor':'middle'},key==='recovery_rounds'?'No observed recovery values for this case.':'No values available for this case.'));return;}
 const values=points.flatMap(r=>[r[key].mean,r[key].ci95_low??r[key].mean,r[key].ci95_high??r[key].mean]);if(ceiling!=null)values.push(ceiling);
 let lo=Math.min(0,...values),hi=Math.max(...values);if(hi<=lo)hi=lo+1;const pad=(hi-lo)*.055;lo-=pad;hi+=pad;
 const left=220,right=930,top=58,bottom=top+(rows.length-1)*65,x=v=>left+(right-left)*(v-lo)/(hi-lo);
 for(let i=0;i<=5;i++){const v=lo+(hi-lo)*i/5,at=x(v);svg.append(svgTag('line',{x1:at,x2:at,y1:top-22,y2:bottom+25,stroke:'#30435b'}),svgTag('text',{x:at,y:bottom+53,'text-anchor':'middle'},format(v,key)));}
 if(ceiling!=null){svg.append(svgTag('line',{x1:x(ceiling),x2:x(ceiling),y1:top-22,y2:bottom+25,stroke:'#f4bc69','stroke-width':1.5,'stroke-dasharray':'5 4'}),svgTag('text',{x:x(ceiling)-5,y:top-30,'text-anchor':'end'},'ceiling: '+format(ceiling,key)));}
 for(const [index,row] of rows.entries()){const y=top+index*65,v=row[key],color=row.matched_budget?'#89c5ff':'#edb664';svg.append(svgTag('text',{x:left-15,y:y+5,'text-anchor':'end'},names[row.algorithm]??row.algorithm));if(v?.mean==null){svg.append(svgTag('text',{x:left+10,y:y+5},'No observation'));continue;}
  if(v.ci95_low!=null&&v.ci95_high!=null){svg.append(svgTag('line',{x1:x(v.ci95_low),x2:x(v.ci95_high),y1:y,y2:y,stroke:color,'stroke-width':2}));for(const end of [v.ci95_low,v.ci95_high])svg.append(svgTag('line',{x1:x(end),x2:x(end),y1:y-7,y2:y+7,stroke:color,'stroke-width':2}));}
  const marker=row.matched_budget?svgTag('circle',{cx:x(v.mean),cy:y,r:5.5,fill:color}):svgTag('rect',{x:x(v.mean)-5.5,y:y-5.5,width:11,height:11,fill:color});marker.append(svgTag('title',{},(names[row.algorithm]??row.algorithm)+': '+format(v.mean,key)+(row.matched_budget?' (matched budget)':' (diagnostic)')));svg.append(marker,svgTag('text',{x:right+20,y:y+5},format(v.mean,key)));}
}
for(const id of ['budget','population','scenario','metric'])el(id).addEventListener('change',render);
render();
</script>
</body>
</html>
'''


def render_report(analysis):
    """Keep report data small; the full paired evidence remains downloadable."""
    required = ("plan", "selected", "summary", "completed", "total_requests",
                "implementation_sha256")
    payload = {key: analysis[key] for key in required}
    if not payload["summary"]:
        raise ValueError("analysis has no completed summary groups")
    seen = set()
    for row in payload["summary"]:
        key = (row["budget"], row["nodes"], row["scenario"], row["algorithm"])
        if key in seen:
            raise ValueError(f"duplicate summary group: {key}")
        seen.add(key)
        if row["matched_budget"] != (row["training_feasible"] and row["violation_count"] == 0):
            raise ValueError(f"inconsistent budget status: {key}")
    plan = payload["plan"]
    expected = {(budget["name"], nodes, scenario, algorithm)
                for budget in plan["budgets"] for nodes in plan["evaluation_nodes"]
                for scenario in plan["scenarios"] for algorithm in plan["algorithms"]}
    if seen != expected:
        raise ValueError("analysis must contain every planned method, budget, population and scenario")
    selected = {(row["budget"], row["algorithm"]) for row in payload["selected"]}
    if len(selected) != len(payload["selected"]) or selected != {
            (budget["name"], algorithm) for budget in plan["budgets"] for algorithm in plan["algorithms"]}:
        raise ValueError("analysis must contain one frozen configuration per method and budget")
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace("&", "\\u0026")
    return HTML.replace("__DATA__", encoded)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path,
                        default=Path("results/peerswap-budget/analysis.json"))
    parser.add_argument("--output", type=Path,
                        help="output HTML (default: report.html beside analysis.json)")
    args = parser.parse_args(argv)
    output = args.output or args.analysis.parent / "report.html"
    result = render_report(json.loads(args.analysis.read_text()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result)
    print(output.resolve())


if __name__ == "__main__":
    main()
