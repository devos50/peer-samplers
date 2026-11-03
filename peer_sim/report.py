"""Portable JSON/CSV exports and a self-contained interactive HTML report."""
import csv
import json
from pathlib import Path


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_results(directory, results, summary):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "runs": results, "summary": summary}
    (directory / "results.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    write_csv(directory / "summary.csv", summary)
    series = []
    for run in results:
        for row in run["timeseries"]:
            flat = {"algorithm": run["algorithm"], "scenario": run["config"]["scenario"],
                    "seed": run["config"]["seed"]}
            flat.update({k: v for k, v in row.items() if k not in ("samples", "traffic")})
            for key, value in row["samples"].items():
                if key != "outcomes":
                    flat["samples_" + key] = value
            for key in ("messages_sent", "bytes_sent", "maintenance_messages", "sampling_messages", "bootstrap_messages"):
                flat[key] = row["traffic"].get(key, 0)
            series.append(flat)
    write_csv(directory / "timeseries.csv", series)
    chart_data = {"summary": summary, "runs": [
        {"algorithm": r["algorithm"], "config": r["config"], "timeseries": r["timeseries"]}
        for r in results]}
    data = json.dumps(chart_data, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    (directory / "report.html").write_text(HTML.replace("__DATA__", data))


HTML = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Peer sampling comparison</title>
<style>
:root{color-scheme:light dark;font-family:system-ui,sans-serif;background:#101722;color:#e3eaf5}*{box-sizing:border-box}body{margin:0;padding:32px;max-width:1600px;margin-inline:auto}h1{font-size:30px;margin:0 0 8px}p{line-height:1.6;color:#bac7dc;max-width:1100px}a{color:#8bc9ff}.controls{display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin:24px 0}select,button{background:#1a283b;color:inherit;border:1px solid #42516b;padding:8px;border-radius:5px}.tablewrap{overflow-x:auto;border:1px solid #33425a;border-radius:8px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:12px;border-bottom:1px solid #29374b;white-space:nowrap}th:first-child,td:first-child{text-align:left}th button{border:0;padding:0;background:none;cursor:pointer}th{background:#172237}small{color:#a9b8cf}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:20px;margin:28px 0}.chart{background:#162132;border:1px solid #33425a;border-radius:8px;padding:18px}.chart h2{font-size:16px;margin:0 0 10px}svg{width:100%;height:auto;overflow:visible}svg text{fill:#b9c7db;font-size:11px}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;margin:18px 0}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}.notes{border-left:3px solid #7099d8;padding-left:18px}details{margin-top:24px}pre{white-space:pre-wrap;color:#bac7dc}@media(max-width:560px){body{padding:16px}.grid{grid-template-columns:1fr}}
</style>
<h1>Decentralized peer sampling</h1>
<p>Shared membership traces and sampling demand, local protocol state, counted message delivery. Select a scenario to compare sampling quality, availability, and communication cost.</p>
<div class="controls"><label>Scenario <select id="scenario"></select></label><label>Sort by <select id="sort"></select></label><label><input id="showOracle" type="checkbox" checked> Show IID reference</label></div>
<div id="metadata"></div><div id="table" class="tablewrap"></div><div id="legend" class="legend"></div><div id="charts" class="grid"></div>
<div class="notes"><p><b>Reading the results.</b> Total variation (TV) ranges from 0 to 1; lower is better. Uniformity is conditional on returning a live, non-self peer. Always read it alongside live-sample rate. “Local excess” subtracts a matched ideal IID sampler's local TV; finite sampling noise can make it slightly negative. Small samples produce high empirical TV even for ideal samplers.</p>
<p>Table values are means across seeds; ± values are approximate normal 95% confidence half-widths (absent for one seed). Curves average matching observation times. Sampling outcomes are grouped by request window, including later replies. Traffic is cumulative since warmup; final table costs include the drain of outstanding messages. Bytes use compact JSON payloads plus a configurable header, not measured TCP/IP traffic.</p>
<p>BASALT's hierarchical mode targets an IP-prefix distribution, so nonzero TV against uniform identities is expected. Its intended-distribution local TV is available in the CSV/JSON. PeerSwap assumes no failures in its paper model; join attachment and timeout cleanup here are experimental extensions. These runs do not evaluate Byzantine resistance.</p></div>
<details><summary>Experiment configuration</summary><pre id="config"></pre></details>
<p><a href="results.json">Raw runs (JSON)</a> · <a href="summary.csv">Seed summaries (CSV)</a> · <a href="timeseries.csv">Time series (CSV)</a></p>
<script id="data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent);
const palette=['#65b8ff','#ffb86b','#8ee2b4','#ef8bc6','#c1a0ff','#f2df87','#79dddd','#ff8e8e','#a6c783','#b5bccc','#dbab87'];
const names=[...new Set(data.runs.map(r=>r.algorithm))];const colors=Object.fromEntries(names.map((n,i)=>[n,palette[i%palette.length]]));
const columns=[['algorithm','Algorithm'],['live_sample_rate','Live samples'],['global_tv','Global TV ↓'],['iid_global_tv','IID global TV'],['local_tv_excess_over_iid','Local excess ↓'],['bytes_per_live_node_round','Bytes / node / round ↓'],['final_strong_component','Final largest SCC'],['recovery_rounds','Recovery rounds ↓']];
const el=id=>document.getElementById(id);let ascending=true;
function option(value,label){const o=document.createElement('option');o.value=value;o.textContent=label;return o;}
for(const s of [...new Set(data.runs.map(r=>r.config.scenario))])el('scenario').append(option(s,s));
for(const [key,label] of columns)el('sort').append(option(key,label));
el('sort').value='algorithm';
function number(value,key){if(value==null)return '—';if(key.includes('rate')||key==='final_strong_component')return (100*value).toFixed(1)+'%';return value.toFixed(key.includes('bytes')||key.includes('rounds')?1:3);}
function render(){
const scenario=el('scenario').value,runs=data.runs.filter(r=>r.config.scenario===scenario),sort=el('sort').value;
const rows=data.summary.filter(r=>r.scenario===scenario).sort((a,b)=>{let x=a[sort],y=b[sort];if(x==null)return 1;if(y==null)return -1;return (typeof x==='string'?x.localeCompare(y):x-y)*(ascending?1:-1);});
const table=document.createElement('table'),head=document.createElement('tr');
for(const [key,label] of columns){const th=document.createElement('th'),b=document.createElement('button');b.textContent=label;b.onclick=()=>{ascending=sort===key?!ascending:true;el('sort').value=key;render();};th.append(b);head.append(th);}table.append(head);
for(const row of rows){const tr=document.createElement('tr');for(const [key] of columns){const td=document.createElement('td');td.textContent=key==='algorithm'?row[key]:number(row[key],key);if(key!=='algorithm'&&row[key+'_ci95']!=null){const small=document.createElement('small');small.textContent=' ± '+number(row[key+'_ci95'],key);td.append(small);}tr.append(td);}table.append(tr);}el('table').replaceChildren(table);
el('legend').replaceChildren();for(const n of names){const span=document.createElement('span'),dot=document.createElement('i');dot.className='dot';dot.style.background=colors[n];span.append(dot,document.createTextNode(n));el('legend').append(span);}
const cfg=runs[0].config;el('metadata').textContent=cfg.nodes+' initial peers · '+cfg.rounds+' rounds · '+cfg.warmup+' warmup · '+new Set(runs.map(r=>r.config.seed)).size+' seed(s) · '+cfg.samples_per_node+' requests / peer / round';
el('config').textContent=JSON.stringify(runs.map(r=>({algorithm:r.algorithm,config:r.config})),null,2);
el('charts').replaceChildren();
plot(runs,'Live-sample rate',r=>r.samples.live_sample_rate,[0,1]);
plot(runs,'Global TV against uniform live peers',r=>r.samples.global_tv,[0,1],el('showOracle').checked?r=>r.samples.iid_global_tv:null);
plot(runs,'Local TV excess over matched IID reference',r=>r.samples.local_tv_excess_over_iid);
plot(runs,'Dead descriptors in routing views',r=>r.dead_view_fraction,[0,1]);
plot(runs,'Largest strongly connected component',r=>r.largest_strong_component_fraction,[0,1]);
plot(runs,'Cumulative messages after warmup',r=>r.traffic.messages_sent||0);
}
function plot(runs,title,get,limits,reference){
const ns='http://www.w3.org/2000/svg';function tag(name,attrs={},text){const e=document.createElementNS(ns,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!=null)e.textContent=text;return e;}
const panel=document.createElement('div');panel.className='chart';const heading=document.createElement('h2');heading.textContent=title;panel.append(heading);const svg=tag('svg',{viewBox:'0 0 560 250',role:'img','aria-label':title});panel.append(svg);el('charts').append(panel);
const lines=[];for(const name of names){for(const [fn,dashed] of [[get,false],...(reference?[[reference,true]]:[])]){const points=new Map();for(const run of runs.filter(r=>r.algorithm===name))for(const row of run.timeseries){const value=fn(row);if(value!=null){const old=points.get(row.time)||[];old.push(value);points.set(row.time,old);}}lines.push({name,dashed,points:[...points].sort((a,b)=>a[0]-b[0]).map(([t,vs])=>[t,vs.reduce((a,b)=>a+b,0)/vs.length])});}}
const all=lines.flatMap(l=>l.points);if(!all.length){svg.append(tag('text',{x:50,y:100},'No measured samples in this window'));return;}
let low=limits?limits[0]:Math.min(0,...all.map(p=>p[1])),high=limits?limits[1]:Math.max(...all.map(p=>p[1]));if(high<=low)high=low+1;
const xmax=Math.max(1,...all.map(p=>p[0]));const x=t=>54+480*t/xmax,y=v=>210-180*(v-low)/(high-low);
for(let i=0;i<=4;i++){const v=low+(high-low)*i/4;svg.append(tag('line',{x1:54,x2:534,y1:y(v),y2:y(v),stroke:'#33425a'}));svg.append(tag('text',{x:46,y:y(v)+4,'text-anchor':'end'},v.toFixed(high>100?0:2)));const t=xmax*i/4;svg.append(tag('text',{x:x(t),y:231,'text-anchor':'middle'},t.toFixed(0)));}svg.append(tag('text',{x:292,y:248,'text-anchor':'middle'},'Simulation round'));
for(const line of lines){if(!line.points.length)continue;const path=tag('path',{d:line.points.map(([t,v],i)=>(i?'L':'M')+x(t)+','+y(v)).join(' '),fill:'none',stroke:colors[line.name],'stroke-width':line.dashed?1:2,'stroke-dasharray':line.dashed?'5 5':'','opacity':line.dashed?.5:.95});path.append(tag('title',{},line.name+(line.dashed?' IID reference':'')));svg.append(path);}
}
el('scenario').onchange=render;el('sort').onchange=()=>{ascending=true;render();};el('showOracle').onchange=render;render();
</script></html>'''
