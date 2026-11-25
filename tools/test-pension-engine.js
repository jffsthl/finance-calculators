const fs=require('fs'),path=require('path');
// Extracts the engine from calculators/pension.html and checks it against the research CSVs in /workspace/pension-bt.
const H=fs.readFileSync(path.join(__dirname,'../calculators/pension.html'),'utf8');const src=H.slice(H.indexOf('// ENGINE START'),H.indexOf('// ENGINE END'));const PX=new Function(src+';return PX;')();
const D=JSON.parse(fs.readFileSync(path.join(__dirname,'../calculators/data/pension.json')));
const csv=f=>{const L=fs.readFileSync(f,'utf8').trim().split('\n'),h=L[0].split(',');return L.slice(1).map(l=>{const v=l.split(',');return Object.fromEntries(h.map((k,i)=>[k,v[i]]))})};
const base={pension:50000,ss:40000,eshare:.95,tips:'tips_R1',hair:false,from:1927,to:1996};
let maxd=0,bad=0,n=0;
const chk=(a,b,tag)=>{n++;const d=Math.abs(a-b);if(d>maxd)maxd=d;if(d>1.01){bad++;if(bad<20)console.log('MISMATCH',tag,a,b)}};
function cmpSumm(rows,scen,opts){
  for(const W0 of [500000,1000000,2000000]){const r=PX.simulate(D,{...base,...opts,W0});
   for(const row of rows.filter(x=>+x.start===W0)){const s=r.res[row.alloc],t=scen+' '+row.alloc+' '+W0;
    chk(s.success*100,+row.success_pct,t+' succ');chk(s.median,+row.median_end_real,t+' med');chk(s.p10,+row.p10_end_real,t+' p10');chk(s.worst,+row.worst_end_real,t+' worst');
    chk(s.medianMin,+row.median_min_real,t+' medmin');chk(s.worstMin,+row.worst_min_real,t+' wmin');chk(s.high.median,+row.highinfl_median_end,t+' hmed');chk(s.high.p10,+row.highinfl_p10_end,t+' hp10');chk(s.low.median,+row.lowinfl_median_end,t+' lmed');
    if(String(s.worstStart)!==row.worst_start||s.worst5.join(' ')!==row.worst5_starts){bad++;console.log('YR MISMATCH',t,s.worstStart,row.worst_start,s.worst5.join(' '),row.worst5_starts)}}}}
cmpSumm(csv('/workspace/pension-bt/summary_main.csv'),'main',{});
const sens=csv('/workspace/pension-bt/sensitivity.csv');
const SC={'TIPS R2 const 2% real':{tips:'tips_R2'},'TIPS R3 const 1% real':{tips:'tips_R3'},'TIPS R4 const 3% real':{tips:'tips_R4'},'TIPS R5 = R1 clipped to [-1%,5%]':{tips:'tips_R5'},
 'NR proxy minus 2%/yr pre-2010 (US-vs-global haircut)':{hair:true},'SS thresholds indexed to CPI':{idxThr:true}};
for(const k in SC)cmpSumm(sens.filter(r=>r.scenario===k),k,SC[k]);
// per-window
const win=csv('/workspace/pension-bt/windows_by_start_year.csv');
for(const W0 of [500000,1000000,2000000]){const r=PX.simulate(D,{...base,W0});
 r.win.forEach((w,i)=>{const row=win[i];chk(w.fw,+row.first_withdrawal_year,'fw');chk(w.realWd,+row.total_real_gross_withdrawals_2026usd,'wd');if(w.terc!==row.infl_tercile){bad++;console.log('terc',w.start)}
  for(const a in PX.ALLOC){const x=r.res[a].runs[i],t=`${a}_${W0/1000}k_`;chk(x.end,+row[t+'end_real'],t+'end '+w.start);chk(x.min,+row[t+'min_real'],t+'min');chk(x.dep,+row[t+'depleted_year'],t+'dep');chk(+x.success,+row[t+'success'],t+'s');
   if(W0===500000)chk(x.cagr*100,+row[a+'_real_cagr_pct'],a+' cagr '+w.start)}})}
console.log('checks',n,'mismatches',bad,'max abs diff',maxd);
