#!/usr/bin/env python3
"""Combine completed scale analyses into an offline cross-population report."""
import argparse
import json
import os
from pathlib import Path


HTML = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Peer sampling: larger experiments</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#101722;color:#e4ecf8}body{max-width:1450px;margin:30px auto;padding:0 24px}h1{font-size:30px}p{line-height:1.6;color:#bdcbe0}a{color:#8bc9ff}label{display:inline-block;margin:12px 20px 12px 0}select{padding:8px;background:#1c2c43;color:inherit;border:1px solid #55627a;border-radius:5px}svg{width:100%;height:auto;background:#162132;border-radius:10px}svg text{fill:#becce0;font-size:12px}.legend{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0;font-size:12px}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:12px;border-bottom:1px solid #344359;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}.note{padding:16px;border-left:3px solid #e6b969;background:#1d283a}small{color:#aab9cf}
</style><h1>Peer sampling: larger experiments</h1>
<p id="intro"></p><p id="reports"></p>
<div class="note">These are results for the implemented variants at fixed parameters, not a ranking of all possible configurations. Local TV excess measures empirical sample diversity over time relative to an IID reference; it does not directly test the theoretical marginal distribution of a single sample. Hierarchical BASALT intentionally targets IP-prefix weighting. SCAMP's lease variant can inflate its views during long static runs; inspect final view size before interpreting its apparent uniformity or overhead. PeerSwap's churn handling remains experimental.</div>
<label>Scenario <select id="scenario"><option>static</option><option>churn</option><option>crash</option></select></label>
<label>Metric <select id="metric"></select></label>
<label><input id="log" type="checkbox"> Logarithmic cost axis</label>
<div id="legend" class="legend"></div><div id="chart"></div><div id="table" class="wrap"></div>
<p>Means and Student t 95% confidence intervals across ten independent seeds. Pairwise comparisons use matching seeds and exact membership traces; their intervals are exploratory, with no multiple-comparison correction. Recovery means include only runs that met the recovery criterion; select recovery fraction to check censoring.</p>
<p>Uniformity excludes failed, dead, and self results. Availability includes every measured request. The final-quarter rate pools late request cohorts. Traffic is modeled compact-JSON bytes plus a fixed header, including maintenance, sampling, bootstrap, and failed sends. Protocol settings are view_size=12, exchange_size=6, active_size=4, and walk_length=8 where applicable. SCAMP's adaptive view is not capped by view_size.</p>
<script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent), el=id=>document.getElementById(id);
const metrics=[['local_tv_excess_over_iid','Local TV excess over IID ↓'],['global_tv_excess_over_iid','Global TV excess over IID ↓'],['global_tv','Global TV ↓'],['live_sample_rate','Live-sample rate ↑'],['late_live_sample_rate','Final-quarter live-sample rate ↑'],['bytes_per_live_node_round','Bytes / live node / round ↓'],['bytes_per_live_sample','Bytes / successful sample ↓'],['final_strong_component','Final largest SCC ↑'],['final_dead_view_fraction','Final dead routing descriptors ↓'],['final_mean_view_size','Final mean routing-view size'],['recovery_rounds','Observed recovery rounds ↓'],['recovery_observed_fraction','Fraction of seeds recovered ↑']];
for(const [value,text] of metrics){const o=document.createElement('option');o.value=value;o.textContent=text;el('metric').append(o);}
const sizes=[...new Set(data.summary.map(r=>r.nodes))].sort((a,b)=>a-b), names=[...new Set(data.summary.map(r=>r.algorithm))].sort();
const palette=['#65b8ff','#ffb86b','#8ee2b4','#ef8bc6','#c1a0ff','#f2df87','#79dddd','#ff8e8e','#a6c783','#b5bccc','#dbab87'];const colors=Object.fromEntries(names.map((n,i)=>[n,palette[i%palette.length]]));
el('intro').textContent=data.completed+' completed runs · '+sizes.join(', ')+' peers · 400 rounds (80 warmup) · 10 seeds per method/scenario/population · 2% churn or a 50% crash at round 200 · '+data.total_requests.toLocaleString()+' measured requests';
for(const link of data.links){const a=document.createElement('a');a.href=link.href;a.textContent=link.label;el('reports').append(a,document.createTextNode(' · '));}
for(const name of names){const span=document.createElement('span'),dot=document.createElement('span');dot.className='dot';dot.style.background=colors[name];span.append(dot,document.createTextNode(name));el('legend').append(span);}
function format(v,key){if(v==null)return '—';return key.includes('rate')||key.includes('fraction')||key==='final_strong_component'?(100*v).toFixed(2)+'%':v.toFixed(key.includes('bytes')||key.includes('rounds')||key.includes('size')?1:4);}
function render(){const scenario=el('scenario').value,key=el('metric').value,rows=data.summary.filter(r=>r.scenario===scenario);const points=[];
const table=document.createElement('table'),head=document.createElement('tr');for(const text of ['Algorithm',...sizes.map(n=>n+' peers')]){const th=document.createElement('th');th.textContent=text;head.append(th);}table.append(head);
for(const name of names){const tr=document.createElement('tr'),label=document.createElement('td');label.textContent=name;tr.append(label);for(const n of sizes){const row=rows.find(r=>r.algorithm===name&&r.nodes===n);let v=row?row[key]:null;if(typeof v==='number')v={mean:v,ci95_low:null,ci95_high:null};const td=document.createElement('td');td.textContent=format(v?.mean,key);if(v?.ci95_low!=null){const small=document.createElement('small');small.textContent=' ['+format(v.ci95_low,key)+', '+format(v.ci95_high,key)+']';td.append(small);}tr.append(td);if(v?.mean!=null)points.push({name,n,...v});}table.append(tr);}el('table').replaceChildren(table);draw(points,key);}
function draw(points,key){const ns='http://www.w3.org/2000/svg';function tag(name,attrs={},text){const e=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;return e;}
const svg=tag('svg',{viewBox:'0 0 1100 420',role:'img','aria-label':metrics.find(m=>m[0]===key)[1]});el('chart').replaceChildren(svg);if(!points.length)return;
const log=el('log').checked&&key.includes('bytes'),transform=v=>log?Math.log10(Math.max(v,1e-6)):v;
const values=points.flatMap(p=>[p.mean,p.ci95_low??p.mean,p.ci95_high??p.mean]).map(transform);let low=log?Math.min(...values):Math.min(0,...values),high=Math.max(...values);if(high<=low)high=low+1;const pad=.06*(high-low);low-=pad;high+=pad;
const xn=n=>100+940*(Math.log10(n)-Math.log10(sizes[0]))/(Math.log10(sizes.at(-1))-Math.log10(sizes[0])||1),yn=v=>350-300*(transform(v)-low)/(high-low);
for(let i=0;i<=5;i++){const z=low+(high-low)*i/5,v=log?10**z:z,y=yn(v);svg.append(tag('line',{x1:100,x2:1040,y1:y,y2:y,stroke:'#344359'}));svg.append(tag('text',{x:90,y:y+4,'text-anchor':'end'},format(v,key)));}for(const n of sizes)svg.append(tag('text',{x:xn(n),y:380,'text-anchor':'middle'},n+' peers'));svg.append(tag('text',{x:570,y:405,'text-anchor':'middle'},'Population (logarithmic spacing)'));
for(const name of names){const series=points.filter(p=>p.name===name).sort((a,b)=>a.n-b.n);if(!series.length)continue;svg.append(tag('path',{d:series.map((p,i)=>(i?'L':'M')+xn(p.n)+','+yn(p.mean)).join(' '),fill:'none',stroke:colors[name],'stroke-width':2}));for(const p of series){if(p.ci95_low!=null)svg.append(tag('line',{x1:xn(p.n),x2:xn(p.n),y1:yn(p.ci95_low),y2:yn(p.ci95_high),stroke:colors[name],'stroke-width':2}));const dot=tag('circle',{cx:xn(p.n),cy:yn(p.mean),r:4,fill:colors[name]});dot.append(tag('title',{},name+' / '+p.n+' peers: '+format(p.mean,key)));svg.append(dot);}}}
el('scenario').onchange=render;el('metric').onchange=render;el('log').onchange=render;render();
</script></html>'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyses", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    combined = {"summary": [], "links": [], "completed": 0, "total_requests": 0}
    digests = set()
    for path in args.analyses:
        analysis = json.loads(path.read_text())
        if analysis["completed"] != analysis["planned"]:
            raise ValueError(f"{path}: study is not complete")
        combined["summary"].extend(analysis["summary"])
        combined["completed"] += analysis["completed"]
        combined["total_requests"] += analysis["total_requests"]
        digests.add(analysis["implementation_sha256"])
        for tier in sorted({row["tier"] for row in analysis["summary"]}):
            combined["links"].append({"label": tier, "href": os.path.relpath(path.parent / tier / "report.html", args.output.parent)})
        combined["links"].append({"label": path.parent.name + " paired comparisons",
                                  "href": os.path.relpath(path.parent / "paired_comparisons.csv", args.output.parent)})
    if len(digests) != 1:
        raise ValueError("analyses use different implementations")
    data = json.dumps(combined, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(HTML.replace("__DATA__", data))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
