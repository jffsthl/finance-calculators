#!/usr/bin/env python3
"""Builds calculators/data/fi-risk-on-off.json for the Fixed-Income Risk-On / Risk-Off backtest.

Signals (month-end values only; the state decided at the end of month t sets the weights for month t+1):
  * main  : Moody's Baa minus 10-year Treasury (FRED BAA10Y, daily, month-end value) from 1986-01. Percentile/median history
            before 1986 (burn-in, 1953-04..1985-12) uses FRED BAA - GS10 monthly averages. First signal: Dec 1986.
  * baa86 : same spread, but history from 1986-01 only, 60-month burn-in. First signal: Dec 1990.
  * ice   : ICE BofA US High Yield OAS (BAMLH0A0HYM2), month-end. FRED serves only the last 3 years, so the history is
            rebuilt from github.com/csaladenes/eco-archive (pre-truncation FRED copy, 1996-12..2021-03) + convextrade.com
            (CC BY 4.0, 2021-11..; identical to FRED on every overlapping day) + FRED. Month-ends 2021-04..2021-10 are in
            none of them and are filled by OLS on BAA10Y (fit reported in "iceFill"). 60-month burn-in; first signal Dec 2001.
Features at month-end t: pct = expanding percentile rank (share of history <= today, incl. today); med = rolling 120-month
median (incl. t; expanding until 120 months exist); pk3 = max of t-2..t; lo6 = min of t-5..t.
States (fixed rules):
  neutral 40 HY / 60 VBMFX
  risk-on 80/20: enter pct > 70 and spread <= 0.85*pk3; exit when spread < med, after >= 12 months held ("s2": no hold)
  risk-off 0/50/50 (VBMFX + risk-off fund): enter pct < 20 and spread >= 1.15*lo6 ("s1": no widening test); exit pct > 40
  Each month-end the current state's exit test runs first, then entries from neutral (risk-on first; entries are exclusive).
Returns: Yahoo Finance adjusted close (distributions reinvested), month-end. VFISX before Nov 1991 (its first full month) is a
proxy: DGS2(t-1)/12 + a - D*dDGS2, a and D fitted on the VFISX overlap. T-bills: FRED TB3MS (monthly average).
Requires numpy.  Usage: python3 tools/build-fi-risk-on-off-data.py
"""
import json, csv, io, datetime as dt, subprocess, os
import numpy as np

UA = "Mozilla/5.0"
FUNDS = ["VWEHX", "FAGIX", "VBMFX", "VFISX", "VUSTX"]
ICE_ARCHIVE = "https://raw.githubusercontent.com/csaladenes/eco-archive/main/BAMLH0A0HYM2.csv"
ICE_CONVEX = "https://convextrade.com/metrics/bamlh0a0hym2/data.csv"

def get(url):
    return subprocess.run(["curl", "-sfL", "--http1.1", "--retry", "3", "-A", UA if "yahoo" in url else "curl/8", url], check=True, capture_output=True, timeout=120).stdout

def monthly_tr(t):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&period1=0&period2=9999999999&events=div%7Csplit"))
    r = j["chart"]["result"][0]; out = {}
    for s, a in zip(r["timestamp"], r["indicators"]["adjclose"][0]["adjclose"]):
        if a is None: continue
        d = dt.datetime.fromtimestamp(s, dt.timezone.utc); out[f"{d.year:04d}-{d.month:02d}"] = a
    ks = sorted(out)
    return {ks[i]: out[ks[i]] / out[ks[i-1]] - 1 for i in range(1, len(ks))}, r["meta"].get("longName"), ks[0]

def daily_csv(txt):
    o = {}
    for row in csv.reader(io.StringIO(txt)):
        if len(row) > 1 and row[0][:2] in ("19", "20"):
            try: o[row[0]] = float(row[1])
            except ValueError: pass
    return o
def fred_daily(sid): return daily_csv(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}").decode())
def month_end(d): o = {}; [o.__setitem__(k[:7], d[k]) for k in sorted(d)]; return o
def month_avg(d):
    o = {}
    for k, v in d.items(): o.setdefault(k[:7], []).append(v)
    return {k: sum(v) / len(v) for k, v in o.items()}
def pm(m): y, mo = int(m[:4]), int(m[5:]); return f"{y-1:04d}-12" if mo == 1 else f"{y:04d}-{mo-1:02d}"
def nm(m): y, mo = int(m[:4]), int(m[5:]); return f"{y+(mo == 12):04d}-{mo % 12 + 1:02d}"
def mrange(a, b):
    out = []
    while a <= b: out.append(a); a = nm(a)
    return out

def features(sig, med_win=120):
    ks = list(sig); v = np.array([sig[k] for k in ks]); out = {}
    for i, k in enumerate(ks):
        h = v[:i+1]
        out[k] = dict(s=float(v[i]), pct=float(100 * np.mean(h <= v[i])), med=float(np.median(v[max(0, i-med_win+1):i+1])),
                      pk3=float(v[max(0, i-2):i+1].max()), lo6=float(v[max(0, i-5):i+1].min()))
    return out

def states(F, sig_months, s1=False, s2=False, hold=12):
    st, age, out = "N", 0, {}
    for t in sig_months:
        f = F[t]
        if st == "ON":
            age += 1
            if f["s"] < f["med"] and (s2 or age >= hold): st = "N"
        elif st == "OFF":
            age += 1
            if f["pct"] > 40: st = "N"
        if st == "N":
            if f["pct"] > 70 and f["s"] <= 0.85 * f["pk3"]: st, age = "ON", 0
            elif f["pct"] < 20 and (s1 or f["s"] >= 1.15 * f["lo6"]): st, age = "OFF", 0
        out[t] = st
    return out

def main():
    today = dt.date.today(); last_full = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    rets, names, firsts = {}, {}, {}
    for t in FUNDS: rets[t], names[t], firsts[t] = monthly_tr(t)
    baa10y, dgs2 = fred_daily("BAA10Y"), fred_daily("DGS2")
    baa_m, gs10_m, tb = month_avg(fred_daily("BAA")), month_avg(fred_daily("GS10")), month_avg(fred_daily("TB3MS"))
    # --- VFISX splice ---
    y2 = month_end(dgs2)
    vf_first = min(m for m in rets["VFISX"] if m > firsts["VFISX"])   # first full month
    ov = [m for m in rets["VFISX"] if m >= vf_first and m in y2 and pm(m) in y2 and m <= last_full]
    X = np.array([y2[pm(m)] / 1200 for m in ov]); dY = np.array([(y2[m] - y2[pm(m)]) / 100 for m in ov]); R = np.array([rets["VFISX"][m] for m in ov])
    c = np.polyfit(dY, R - X, 1); D, a0 = -c[0], c[1]
    prox = lambda m: y2[pm(m)] / 1200 + a0 - D * (y2[m] - y2[pm(m)]) / 100
    pr = np.array([prox(m) for m in ov]); splice = dict(firstActual=vf_first, D=round(float(D), 3), aPerYear=round(float(a0 * 12), 5),
        corr=round(float(np.corrcoef(R, pr)[0, 1]), 3), trackingError=round(float(np.std(R - pr, ddof=1) * 12 ** 0.5), 5))
    for m in y2:
        if m < vf_first and pm(m) in y2: rets["VFISX"][m] = prox(m)
    # --- signals ---
    be = month_end(baa10y)
    main_sig = {**{m: baa_m[m] - gs10_m[m] for m in sorted(gs10_m) if m in baa_m and "1953-04" <= m < "1986-01"}, **{m: v for m, v in be.items() if m <= last_full}}
    main_sig = dict(sorted(main_sig.items()))
    b86 = {m: v for m, v in main_sig.items() if m >= "1986-01"}
    ice_d = {**daily_csv(get(ICE_ARCHIVE).decode()), **daily_csv(get(ICE_CONVEX).decode()), **fred_daily("BAMLH0A0HYM2")}
    ice = {m: v for m, v in month_end(ice_d).items() if m <= last_full}
    ovm = [m for m in ice if m in be and m < "2021-04"]
    fit = np.polyfit([be[m] for m in ovm], [ice[m] for m in ovm], 1); r_fit = float(np.corrcoef([be[m] for m in ovm], [ice[m] for m in ovm])[0, 1])
    filled = [m for m in mrange(min(ice), last_full) if m not in ice]
    for m in filled: ice[m] = float(np.polyval(fit, be[m]))
    ice = dict(sorted(ice.items()))
    # --- return months ---
    start = "1987-01"
    months = [m for m in mrange(start, last_full) if all(m in rets[t] for t in FUNDS) and m in tb]
    SIGS = {"main": (main_sig, "1986-12", "Moody's Baa − 10-year Treasury (1953+ history)"),
            "baa86": (b86, "1990-12", "Moody's Baa − 10-year Treasury (history from 1986 only)"),
            "ice": (ice, "2001-12", "ICE BofA US High Yield OAS (history from Dec 1996)")}
    sigs = {}
    for k, (sig, first, label) in SIGS.items():
        F = features(sig); sm = [m for m in sig if m >= first]
        vs = {v: states(F, sm, s1=(v == "s1"), s2=(v == "s2")) for v in ("std", "s1", "s2")}
        sigs[k] = {"label": label, "firstSignal": first,
                   "spread": [round(F[pm(m)]["s"], 3) if pm(m) in F and pm(m) >= first else None for m in months],
                   "pct": [round(F[pm(m)]["pct"], 1) if pm(m) in F and pm(m) >= first else None for m in months],
                   "median": [round(F[pm(m)]["med"], 3) if pm(m) in F and pm(m) >= first else None for m in months],
                   "states": {v: "".join({"N": "N", "ON": "U", "OFF": "D"}.get(st.get(pm(m)), ".") for m in months) for v, st in vs.items()}}
    data = {
        "built": today.isoformat(), "start": months[0], "end": months[-1], "months": months,
        "names": names, "returns": {t: [round(rets[t][m], 6) for m in months] for t in FUNDS},
        "tbill": [round(tb[m], 3) for m in months], "signals": sigs, "vfisxSplice": splice,
        "iceFill": {"slope": round(float(fit[0]), 4), "intercept": round(float(fit[1]), 4), "r": round(r_fit, 3), "months": filled},
        "stateCodes": {"N": "neutral", "U": "risk-on", "D": "risk-off", ".": "no signal yet"},
        "weights": {"N": [0.4, 0.6, 0], "U": [0.8, 0.2, 0], "D": [0, 0.5, 0.5]},  # [HY fund, VBMFX, risk-off fund]
        "sources": {
            "prices": "Yahoo Finance adjusted close (total return, distributions reinvested), month-end",
            "tbill": "FRED TB3MS, 3-month Treasury bill, monthly average, %",
            "baa": "FRED BAA10Y (Moody's Baa corporate yield minus 10-year Treasury, daily; month-end value); before 1986, FRED BAA minus GS10 monthly averages (history only)",
            "ice": "ICE BofA US High Yield OAS (BAMLH0A0HYM2): github.com/csaladenes/eco-archive (1996-12 to 2021-03), convextrade.com (CC BY 4.0, 2021-11 on), FRED (last 3 years)",
            "vfisxProxy": "FRED DGS2 (2-year Treasury, month-end) carry plus duration return, fitted to VFISX",
        },
    }
    p = os.path.join(os.path.dirname(__file__), "..", "calculators", "data", "fi-risk-on-off.json")
    with open(p, "w") as f: json.dump(data, f, separators=(",", ":"))
    print("wrote", p, months[0], "->", months[-1], len(months), "months; splice", splice, "; ICE filled", filled)

if __name__ == "__main__":
    main()
