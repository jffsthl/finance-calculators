#!/usr/bin/env python3
"""Builds calculators/data/risk-parity.json for the Risk Parity backtest.

Model ("R3f + carry rule"), seven funds: VIPIX, QQQ, VGSLX, GLD, PNRZX, VBTLX, VGENX.
  * Weights (computed here, baked into the JSON): constrained risk budgeting (Richard & Roncalli 2019) on the trailing
    36-month covariance (expanding window for the first 3 years, minimum 12 months; month t's weights only use months < t):
        minimize 0.5*y'Cy - (1/n)*sum(log y)  subject to  measured rate-risk share <= 20%,  w = y/sum(y).
    Without the constraint this is exactly equal risk contribution (ERC). Rate-risk share = (w.b)^2 var(dY) / w'Cw, where
    b = each fund's beta to monthly changes in the 10-year Treasury yield (FRED DGS10, month-end), shrunk toward 0 by
    max(0, 1 - 1/t^2), and floored at 0 (min(b,0): a fund that rises when yields rise does not offset bond rate risk).
  * Bond yields for the carry rule (applied on the page): month-end, annual %.
      VBTLX ~ Bloomberg US Aggregate yield-to-worst proxy = DGS7 + 0.25*CorpOAS + 0.27*(MORTGAGE30US - DGS10 - mean) + k
        CorpOAS = ICE BofA US Corporate OAS (FRED BAMLC0A0CM; FRED carries only the last 3 years); earlier months use
        a * mean(Moody's AAA10Y, BAA10Y), a = ratio of the two series' means over the overlap.
        k = mean residual vs published Agg YTW: 4.68% (12/31/2022) and 4.53% (12/31/2023) [Meketa 2024 CME],
        4.73% (6/30/2026) [Hartford Funds].
      VIPIX ~ duration-matched (about 7 years) TIPS yield: DFII7 (7-year TIPS real yield) + T7YIEM (7-year breakeven).
    Vanguard's historical 30-day SEC yields are not published as a series, so these are proxies.
Sources (fetched at build time; the page makes no runtime API calls):
  * Yahoo Finance daily chart API, adjusted close (distributions reinvested); month-end = last trading day's close.
  * FRED: FEDFUNDS (margin benchmark), TB3MS (cash), DGS10, DGS7, BAMLC0A0CM, AAA10Y, BAA10Y, MORTGAGE30US, DFII7, T7YIEM.
Data fix: Yahoo's VGSLX (Admiral) history omits part of the fund's distributions before 2010 (it trails VGSIX and VNQ
by 1.3-1.7%/yr in 2004-2009). For Dec 2004 - Dec 2009 we use VGSIX's monthly return plus the 0.14%/yr expense-ratio
gap. Every substituted month is listed in "patches".
Requires numpy and scipy.  Usage: python3 tools/build-risk-parity-data.py   (writes calculators/data/risk-parity.json)
"""
import json, csv, io, math, datetime as dt, subprocess, os
import numpy as np
from scipy.optimize import minimize

UA = {"User-Agent": "Mozilla/5.0"}
RP = ["VIPIX", "QQQ", "VGSLX", "GLD", "PNRZX", "VBTLX", "VGENX"]
BM = ["VFINX", "VBMFX"]
AUX = ["VGSIX", "VNQ"]
BONDS = ["VBTLX", "VIPIX"]
LB, MINH, RATE_CAP = 36, 12, 0.20
AGG_YTW = {"2022-12": 4.68, "2023-12": 4.53, "2026-06": 4.73}   # published Bloomberg US Agg yield-to-worst, %
W_CORP, W_MBS = 0.25, 0.27                                        # approx. Agg weights of corporates and agency MBS

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
    """monthly series: one value per month; daily/weekly series: last observation of the month."""
    txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}").decode()
    return {row[0][:7]: float(row[1]) for row in list(csv.reader(io.StringIO(txt)))[1:] if row[1] not in ("", ".")}

def prev_month(m):
    y, mo = int(m[:4]), int(m[5:])
    return f"{y-1:04d}-12" if mo == 1 else f"{y:04d}-{mo-1:02d}"

# ---------- weights ----------
def erc(C, iters=1000):
    n = len(C); b = np.ones(n) / n; x = np.ones(n) / np.sqrt(np.diag(C))
    for _ in range(iters):
        old = x.copy()
        for i in range(n):
            bb = C[i] @ x - C[i, i] * x[i]; x[i] = (-bb + math.sqrt(bb * bb + 4 * C[i, i] * b[i])) / (2 * C[i, i])
        if np.max(np.abs(x - old)) < 1e-12: break
    return x / x.sum()

def shrunk_betas(Rw, dyw):
    x = dyw - dyw.mean(); sxx = (x * x).sum(); n = len(x); B = []
    for j in range(Rw.shape[1]):
        y = Rw[:, j] - Rw[:, j].mean(); b = (x @ y) / sxx; res = y - b * x; se = math.sqrt((res @ res) / (n - 2) / sxx); t = b / se if se > 0 else 0
        B.append(b * max(0.0, 1 - 1 / (t * t)) if t != 0 else 0.0)
    return np.array(B), np.var(dyw, ddof=1)

def rate_capped_rb(Rw, dyw, cap=RATE_CAP):
    C = np.cov(Rw.T, ddof=1); beta, vdy = shrunk_betas(Rw, dyw); e = np.minimum(beta, 0)
    share = lambda w: (w @ e) ** 2 * vdy / (w @ C @ w)
    w0 = erc(C); n = len(C)
    if share(w0) <= cap + 1e-9: return w0, share(w0), False
    s = np.mean(np.diag(C)); A = C / s
    con = {"type": "ineq", "fun": lambda y: cap * (y @ A @ y) - (y @ e) ** 2 * vdy / s, "jac": lambda y: 2 * cap * (A @ y) - 2 * (y @ e) * vdy / s * e}
    y0 = w0 / np.sqrt(w0 @ A @ w0)
    r = minimize(lambda y: 0.5 * y @ A @ y - np.log(y).mean(), y0, jac=lambda y: A @ y - 1 / (n * y), constraints=[con],
                 bounds=[(1e-9, None)] * n, method="SLSQP", options={"maxiter": 500, "ftol": 1e-12})
    w = r.x / r.x.sum()
    return w, share(w), True

def main():
    today = dt.date.today()
    last_full = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    rets, names = {}, {}
    for t in RP + BM + AUX:
        rets[t], names[t] = monthly_tr(t)
    F = {s: fred(s) for s in ["FEDFUNDS", "TB3MS", "DGS10", "DGS7", "BAMLC0A0CM", "AAA10Y", "BAA10Y", "MORTGAGE30US", "DFII7", "T7YIEM"]}
    ff, tb, dgs10 = F["FEDFUNDS"], F["TB3MS"], F["DGS10"]
    patches = []
    for m, v in sorted(rets["VGSLX"].items()):
        a = rets["VGSIX"].get(m)
        if m <= "2009-12" and a is not None:
            nv = a + 0.0014 / 12
            patches.append({"ticker": "VGSLX", "month": m, "yahoo": round(v, 6), "used": round(nv, 6), "VGSIX": round(a, 6), "VNQ": rets["VNQ"].get(m) and round(rets["VNQ"][m], 6)})
            rets["VGSLX"][m] = nv
    start = max(min(rets[t]) for t in RP + BM)
    need = ["DGS7", "AAA10Y", "BAA10Y", "MORTGAGE30US", "DFII7", "T7YIEM"]
    months = [m for m in sorted(rets["GLD"]) if start <= m <= last_full and all(m in rets[t] for t in RP + BM) and m in ff and m in tb
              and m in dgs10 and prev_month(m) in dgs10 and all(m in F[s] for s in need)]
    N = len(months)
    # --- bond yield proxies ---
    mid = lambda m: (F["AAA10Y"][m] + F["BAA10Y"][m]) / 2
    ov = [m for m in months if m in F["BAMLC0A0CM"]]
    a_oas = float(np.mean([F["BAMLC0A0CM"][m] for m in ov]) / np.mean([mid(m) for m in ov]))
    oas = lambda m: F["BAMLC0A0CM"][m] if m in F["BAMLC0A0CM"] else a_oas * mid(m)
    mbs_mean = float(np.mean([F["MORTGAGE30US"][m] - dgs10[m] for m in months]))
    raw_agg = lambda m: F["DGS7"][m] + W_CORP * oas(m) + W_MBS * (F["MORTGAGE30US"][m] - dgs10[m] - mbs_mean)
    k_agg = float(np.mean([AGG_YTW[m] - raw_agg(m) for m in AGG_YTW if m in months]))
    yields = {"VBTLX": [round(raw_agg(m) + k_agg, 4) for m in months],
              "VIPIX": [round(F["DFII7"][m] + F["T7YIEM"][m], 4) for m in months]}
    # --- weights: index k -> month MINH+k uses data rows < MINH+k; last row (k = N-MINH) = current weights ---
    R = np.array([[round(rets[t][m], 6) for t in RP] for m in months]); DY = np.array([dgs10[m] - dgs10[prev_month(m)] for m in months])
    W, RS, BIND = [], [], 0
    for t in range(MINH, N + 1):
        lo = max(0, t - LB); w, sh, b = rate_capped_rb(R[lo:t], DY[lo:t]); W.append([round(float(v), 8) for v in w]); RS.append(round(float(sh), 4)); BIND += b
    data = {
        "built": today.isoformat(),
        "start": months[0], "end": months[-1],
        "months": months,
        "assets": RP,
        "names": {t: names[t] for t in RP + BM},
        "returns": {t: [round(rets[t][m], 6) for m in months] for t in RP + BM},
        "fedfunds": [ff[m] for m in months],
        "tbill": [tb[m] for m in months],
        "weights": {"first": MINH, "w": W, "rateShare": RS, "rateCap": RATE_CAP},
        "yields": {**yields, "bonds": BONDS},
        "patches": [p for p in patches if p["month"] >= months[0]],
        "yieldModel": {"corpOasScale": round(a_oas, 4), "corpOasOverlap": [ov[0], ov[-1]] if ov else None, "mbsSpreadMean": round(mbs_mean, 4),
                        "k": round(k_agg, 4), "aggYtwPoints": AGG_YTW, "fitted": {m: round(raw_agg(m) + k_agg, 3) for m in AGG_YTW if m in months}},
        "sources": {
            "prices": "Yahoo Finance adjusted close (total return, distributions reinvested), month-end",
            "fedfunds": "FRED FEDFUNDS, effective federal funds rate, monthly average, %",
            "tbill": "FRED TB3MS, 3-month Treasury bill secondary market rate, monthly average, %",
            "rates": "FRED DGS10, 10-year Treasury constant maturity, month-end (for rate betas)",
            "vbtlxYield": "Bloomberg US Agg yield-to-worst proxy: FRED DGS7 + 0.25 x ICE BofA US Corporate OAS (BAMLC0A0CM; before its FRED history, scaled Moody's AAA10Y/BAA10Y) + 0.27 x (MORTGAGE30US - DGS10, demeaned) + constant fitted to published Agg YTW (Meketa; Hartford Funds), month-end",
            "vipixYield": "FRED DFII7 (7-year TIPS real yield, month-end) + T7YIEM (7-year breakeven inflation, monthly)",
        },
    }
    p = os.path.join(os.path.dirname(__file__), "..", "calculators", "data", "risk-parity.json")
    with open(p, "w") as f: json.dump(data, f, separators=(",", ":"))
    print("wrote", p, months[0], "->", months[-1], N, "months; rate cap binds in", BIND, "of", len(W), "months; Agg proxy k =", round(k_agg, 3), "fit", data["yieldModel"]["fitted"])

if __name__ == "__main__":
    main()
