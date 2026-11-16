#!/usr/bin/env python3
"""Builds calculators/data/risk-parity.json for the Risk Parity backtest.

Sources (fetched at build time, baked into static JSON so the page has no runtime API calls):
  * Yahoo Finance daily chart API, adjusted close (dividends + capital-gain distributions reinvested).
    Month-end value = adjusted close on the last trading day of each month.
  * FRED FEDFUNDS (effective federal funds rate, monthly average) -> margin benchmark.
  * FRED TB3MS (3-month Treasury bill, secondary market, monthly average) -> cash rate / Sharpe.
Data fix: Yahoo's VGSLX (Admiral) history omits part of the fund's distributions before 2010 (it trails the
Investor share class VGSIX and the ETF share class VNQ by 1.3-1.7%/yr in 2004-2009, while all three agree after).
For Dec 2004 - Dec 2009 we use VGSIX's monthly return (same portfolio, matches Vanguard's published returns) plus
the Admiral/Investor expense-ratio gap (0.14%/yr). Every substituted month is listed in "patches".
Usage: python3 tools/build-risk-parity-data.py   (writes calculators/data/risk-parity.json)
"""
import json, csv, io, datetime as dt, subprocess, os

UA = {"User-Agent": "Mozilla/5.0"}
RP = ["VIPIX", "QQQ", "VGSLX", "GLD", "PNRZX", "VBTLX"]
BM = ["VFINX", "VBMFX"]
AUX = ["VGSIX", "VNQ"]

def get(url):
    return subprocess.run(["curl", "-sfL", "--http1.1", "--retry", "3", "-A", UA["User-Agent"] if "yahoo" in url else "curl/8", url], check=True, capture_output=True, timeout=120).stdout

def monthly_tr(t):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&period1=0&period2=9999999999&events=div%7Csplit"))
    r = j["chart"]["result"][0]
    out = {}
    for s, a in zip(r["timestamp"], r["indicators"]["adjclose"][0]["adjclose"]):
        if a is None: continue
        d = dt.datetime.fromtimestamp(s, dt.timezone.utc)
        out[f"{d.year:04d}-{d.month:02d}"] = a  # last trading day of month wins
    ks = sorted(out)
    return {ks[i]: out[ks[i]] / out[ks[i-1]] - 1 for i in range(1, len(ks))}, r["meta"].get("longName")

def fred(sid):
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}").decode()
    return {row[0][:7]: float(row[1]) for row in list(csv.reader(io.StringIO(txt)))[1:] if row[1] not in ("", ".")}

def main():
    today = dt.date.today()
    last_full = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    rets, names = {}, {}
    for t in RP + BM + AUX:
        rets[t], names[t] = monthly_tr(t)
    ff, tb = fred("FEDFUNDS"), fred("TB3MS")
    patches = []
    for m, v in sorted(rets["VGSLX"].items()):
        a = rets["VGSIX"].get(m)
        if m <= "2009-12" and a is not None:
            nv = a + 0.0014 / 12
            patches.append({"ticker": "VGSLX", "month": m, "yahoo": round(v, 6), "used": round(nv, 6), "VGSIX": round(a, 6), "VNQ": rets["VNQ"].get(m) and round(rets["VNQ"][m], 6)})
            rets["VGSLX"][m] = nv
    # common window: first month every RP fund + benchmark has a full-month return, through last complete month with rates
    start = max(min(rets[t]) for t in RP + BM)
    months = [m for m in sorted(rets["GLD"]) if start <= m <= last_full and all(m in rets[t] for t in RP + BM) and m in ff and m in tb]
    data = {
        "built": today.isoformat(),
        "start": months[0], "end": months[-1],
        "months": months,
        "names": {t: names[t] for t in RP + BM},
        "returns": {t: [round(rets[t][m], 6) for m in months] for t in RP + BM},
        "fedfunds": [ff[m] for m in months],
        "tbill": [tb[m] for m in months],
        "patches": [p for p in patches if p["month"] >= months[0]],
        "sources": {
            "prices": "Yahoo Finance adjusted close (total return, distributions reinvested), month-end",
            "fedfunds": "FRED FEDFUNDS, effective federal funds rate, monthly average, %",
            "tbill": "FRED TB3MS, 3-month Treasury bill secondary market rate, monthly average, %",
        },
    }
    p = os.path.join(os.path.dirname(__file__), "..", "calculators", "data", "risk-parity.json")
    with open(p, "w") as f: json.dump(data, f, separators=(",", ":"))
    print("wrote", p, months[0], "->", months[-1], len(months), "months; patches:", data["patches"])

if __name__ == "__main__":
    main()
