"""Build calculators/data/trump-sons.json for the Trump-sons board/advisory-role backtest page.

Re-runs the research engine in /workspace/trump-sons-bt/results (engine.py, data.py, load.py; Yahoo Finance daily
adjusted prices cached in results/raw/) to get daily growth curves for every variant, and copies the research
tables (per-name event study, event-study averages, pop vs drift, FF5+MOM regression, contributions, leave-one-out)
from the CSVs written by results/analyze.py. Numbers are the research results as reported on 2026-11-18
(data through the 2026-11-17 close); this script does not download anything.

Usage: python3 tools/build-trump-sons-data.py [research_dir]
Requires numpy, pandas (and statsmodels only for re-running analyze.py, not needed here).
"""
import sys, os, json, datetime as dt, warnings
warnings.filterwarnings("ignore")
RES = sys.argv[1] if len(sys.argv) > 1 else "/workspace/trump-sons-bt/results"
sys.path.insert(0, RES); os.chdir(RES)
import pandas as pd, numpy as np
from engine import run, stats, bench, UNIV, H, MAIN, FAM, SPAC, C, TS, END

def rnd(x, d=6):
    if x is None or (isinstance(x, float) and not np.isfinite(x)): return None
    return round(float(x), d)
def sd(s): return {k: (str(v) if isinstance(v, (dt.date,)) else rnd(v)) for k, v in s.items()}

out = {"built": dt.date.today().isoformat(), "end": str(END.date()), "windows": {}, "variants": {}, "bench": {}}
WIN = {"main": TS("2024-11-27"), "family": TS("2022-04-25")}
for w, st in WIN.items():
    days = C.index[(C.index >= st) & (C.index <= END)]
    out["windows"][w] = {"start": str(st.date()), "dates": [d.strftime("%Y-%m-%d") for d in days]}
UW = {"MAIN": "main", "PLUS_FAMILY": "family", "PLUS_SPACS": "family"}
for u, (nm, st) in UNIV.items():
    for mode in ["ew", "bh"]:
        for conv in ["a", "b", "c"]:
            for cb in [0, 50]:
                for sh in [False, True]:
                    df, c, tr = run(nm, st, conv, mode, cb, sh)
                    v = df["V"]; v = v / v.iloc[0]
                    key = f"{u}|{mode}|{conv}|{cb}|{'held' if sh else 'exit'}"
                    out["variants"][key] = {"stats": {**sd(stats(df["V"])), "turnover": rnd(tr, 3)}, "v": [rnd(x, 5) for x in v.values]}
                    assert len(v) == len(out["windows"][UW[u]]["dates"]), key
B = {"SPY": ["SPY"], "IWM": ["IWM"], "IWC": ["IWC"], "EW MSTR/COIN": ["MSTR", "COIN"], "BITO": ["BITO"], "BTC": ["BTC"]}
for w, st in WIN.items():
    out["bench"][w] = {}
    for k, cols in B.items():
        v = bench(cols, st); out["bench"][w][k] = {"stats": sd(stats(v)), "v": [rnd(x, 5) for x in (v / v.iloc[0]).values]}
# cross-check against the research CSV (as reported)
G = pd.read_csv("variants.csv")
for _, r in G[G.universe.isin(UNIV)].iterrows():
    k = f"{r.universe}|{r['mode']}|{r.entry}|{r.cost_bp}|{'held' if r.alts == 'still held' else 'exit'}"
    assert abs(out["variants"][k]["stats"]["total"] - r.total) < 1e-6, k
def recs(f): return json.loads(pd.read_csv(f).replace({np.nan: None}).to_json(orient="records", double_precision=6))
out["perName"] = recs("per_name_event_study.csv")
out["eventSummary"] = recs("event_study_summary.csv")
out["popDrift"] = recs("pop_vs_drift.csv")
out["regression"] = recs("ff5_mom_regression.csv")
out["contrib"] = recs("contribution_by_name.csv")
out["loo"] = recs("leave_one_out.csv")
out["holdings"] = {n: {"label": H[n][4], "day0": str(H[n][0].date()), "exit": str(H[n][1].date()) if H[n][1] is not None else None,
                       "timing": H[n][2], "micro": H[n][3]} for n in H}
out["universes"] = {"MAIN": MAIN, "PLUS_FAMILY": FAM, "PLUS_SPACS": SPAC}
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "calculators", "data", "trump-sons.json")
json.dump(out, open(dst, "w"), separators=(",", ":"))
print("wrote", os.path.normpath(dst), os.path.getsize(dst), "bytes;", len(out["variants"]), "variants")
