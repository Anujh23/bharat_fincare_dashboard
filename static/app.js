"use strict";

const $ = (s)=>document.querySelector(s);
const ACCENT = ["#4a90e2", "#9b59d0"];               // product A (blue), product B (purple)
const ACCENT_LITE = ["#7fb2ec", "#bd8ae0"];
let chartInst = null;
let STATE = { pair:"eli_nbl" };

const REFRESH_MS = 5 * 60 * 1000;      // auto-refresh every 5 minutes (silent) — change here
let refreshTimer = null;

/* ---------- money ---------- */
const inrC = (n)=>{ n=Number(n)||0; const a=Math.abs(n);
  if(a>=1e7) return "₹"+(n/1e7).toFixed(2)+" Cr";
  if(a>=1e5) return "₹"+(n/1e5).toFixed(2)+" L";
  if(a>=1e3) return "₹"+(n/1e3).toFixed(0)+"K";
  return "₹"+Math.round(n); };
const inrF = (n)=> "₹"+Math.round(Number(n)||0).toLocaleString("en-IN");
const hexA = (hex,a)=>{ const n=parseInt(hex.slice(1),16); return `rgba(${(n>>16)&255},${(n>>8)&255},${n&255},${a})`; };

/* ---------- cache (stale-while-revalidate) ---------- */
const CACHE_PREFIX = "bfc_board_";       // one entry per pair
let shownPair = null;                    // which pair's data is currently on the board
function cacheGet(pair){ try{ const s=localStorage.getItem(CACHE_PREFIX+pair); return s?JSON.parse(s):null; }catch{ return null; } }
function cacheSet(pair,d){ try{ localStorage.setItem(CACHE_PREFIX+pair, JSON.stringify(d)); }catch{} }

function showEndpointErrs(d){
  const errs=[]; d.products.forEach(p=>Object.keys(p.errors||{}).forEach(k=>errs.push(`${p.key}/${k}`)));
  if(errs.length){ $("#errbar").hidden=false; $("#errbar").textContent=`⚠ ${errs.length} endpoint(s) failed: ${errs.join(", ")}`; }
  else{ $("#errbar").hidden=true; }
}

function paint(d, pair){
  render(d); showEndpointErrs(d);
  $("#board").hidden=false; $("#loader").hidden=true; shownPair=pair;
}

/* ---------- fetch ---------- */
async function load(){
  if(refreshTimer){ clearTimeout(refreshTimer); refreshTimer = null; }   // no double-trigger mid-load
  const pair = STATE.pair;

  // Keep the board visible during refresh. Only blank to the loader when we have
  // nothing at all to show for this pair (first load, or a pair with no cache yet).
  if(shownPair !== pair){
    const cached = cacheGet(pair);
    if(cached){ paint(cached, pair); }        // instant stale data — no blank flash
    else{
      $("#board").hidden=true; $("#loader").hidden=false; $("#errbar").hidden=true;
      $("#loadmsg").textContent=`Loading ${pair.replace("_"," vs ").toUpperCase()} — fetching daily data…`;
    }
  }
  $("#refresh").classList.add("spinning");

  try{
    const r = await fetch(`/api/board?pair=${pair}`);
    const d = await r.json();
    if(!r.ok) throw new Error(d.error||"Request failed");
    cacheSet(pair, d);
    paint(d, pair);                            // swap in fresh data only on success
  }catch(err){
    // Refresh failed — keep the last good data on screen, just flag it.
    $("#errbar").hidden=false;
    $("#errbar").textContent = (shownPair===pair)
      ? "⚠ Refresh failed — showing last loaded data. "+err.message
      : "Error: "+err.message;
  }finally{
    $("#loader").hidden=true;
    $("#refresh").classList.remove("spinning");
    refreshTimer = setTimeout(load, REFRESH_MS);   // silent auto-refresh every 5 min
  }
}

/* ---------- render ---------- */
function render(d){
  const [A,B] = d.products;
  renderTotal(d.company);
  renderProgress($("#pA"), A, 0, d.days_left);
  renderProgress($("#pB"), B, 1, d.days_left);
  renderLeaders($("#leadA"), A, 0);
  renderLeaders($("#leadB"), B, 1);
  $("#chartTitle").textContent = `${A.key} vs ${B.key}`;
  renderChart(d);
}

function renderProgress(el, p, i, daysLeft){
  const pct = p.pct;
  el.style.setProperty("--pc", ACCENT[i]);
  el.innerHTML = `
    <div class="lbl">${p.name} Progress</div>
    <div class="big">${pct.toFixed(2)}%</div>
    <div class="track"><i style="width:${Math.min(pct,100)}%;
       background:linear-gradient(90deg,${ACCENT_LITE[i]},${ACCENT[i]})"></i></div>
    <div class="sub">${pct.toFixed(2)}% of <b>${inrC(p.target)}</b> (${inrC(p.achievement)}) ·
       Need <b>${inrC(p.need_per_day)}</b>/day (${daysLeft}d left)</div>
    <div class="loans">${(p.loans||0).toLocaleString("en-IN")} loans</div>`;
}

function renderTotal(c){
  const pct = c.pct;
  $("#cTotal").innerHTML = `
    <div class="lbl">Company Total Progress</div>
    <div class="track" style="margin-top:14px"><i style="width:${Math.min(pct,100)}%;
       background:linear-gradient(90deg,${ACCENT[0]},${ACCENT[1]})"></i></div>
    <div class="big2">${pct.toFixed(2)}% of <b>${inrC(c.target)}</b> (${inrC(c.achievement)})</div>`;
}

function renderLeaders(el, p, i){
  el.style.setProperty("--pc", ACCENT[i]);
  const top = (p.top_branches || [])[0];
  const cms = p.top_cms || [];
  const medal = ["g1","g2","g3"];
  el.innerHTML = `
    <div class="lead-head"><h3>${p.key} Leaders</h3><span class="rule"></span></div>
    <ul class="cm-list">
      ${cms.length ? cms.map((c,idx)=>`<li>
        <span class="rnk ${medal[idx]||''}">${idx+1}</span>
        <span class="cm-name">${c.name || "—"}</span>
        <span class="cm-amt">${inrC(c.amount)}</span>
      </li>`).join("") : `<li><span class="cm-name">No collection data</span></li>`}
    </ul>
    <div class="topbranch">
      <div class="tb-lbl">${p.key} Top Branch</div>
      <div class="tb-name">${top ? top.branch : "—"}</div>
      <div class="tb-amt">${top ? inrC(top.amount) : "₹0"}</div>
    </div>`;
}

function renderChart(d){
  const dim = d.days_in_month, today = d.day_of_month;
  const labels = Array.from({length:dim}, (_,k)=>k+1);
  const series = d.products.map((p,i)=>{
    const map = {}; (p.daily||[]).forEach(x=>{ map[x.day]=x.amount; });
    const data = labels.map(day => day<=today ? (map[day]??0) : null);
    return { label:p.key, data, borderColor:ACCENT[i],
      pointBackgroundColor:ACCENT[i], pointRadius:3, pointHoverRadius:5,
      borderWidth:3, tension:.35, fill:true, spanGaps:false,
      backgroundColor:(ctx)=>{
        const ch=ctx.chart, area=ch.chartArea;
        if(!area) return hexA(ACCENT[i],0.12);
        const g=ch.ctx.createLinearGradient(0,area.top,0,area.bottom);
        g.addColorStop(0,hexA(ACCENT[i],0.38)); g.addColorStop(1,hexA(ACCENT[i],0.02));
        return g;
      } };
  });

  const ink = "#8a93a8", grid = "rgba(150,160,180,.18)";
  if(chartInst) chartInst.destroy();
  chartInst = new Chart($("#chart"), {
    type:"line",
    data:{ labels, datasets:series },
    options:{
      responsive:true, maintainAspectRatio:false,
      interaction:{ mode:"index", intersect:false },
      plugins:{
        legend:{ position:"bottom", labels:{ color:ink, usePointStyle:true, pointStyle:"circle", padding:18, font:{size:13} } },
        tooltip:{ callbacks:{ label:(c)=> ` ${c.dataset.label}: ${inrF(c.raw||0)}` } }
      },
      scales:{
        x:{ ticks:{ color:ink }, grid:{ display:false }, border:{ display:false } },
        y:{ ticks:{ color:ink, callback:(v)=>inrC(v) }, grid:{ display:false }, border:{ display:false }, beginAtZero:true }
      }
    }
  });
}

/* ---------- controls ---------- */
document.querySelectorAll("#seg button").forEach(b=>b.onclick=()=>{
  if(b.classList.contains("on")) return;
  document.querySelectorAll("#seg button").forEach(x=>x.classList.remove("on"));
  b.classList.add("on");
  STATE.pair = b.dataset.pair;
  load();
});
$("#refresh").onclick = load;

load();
