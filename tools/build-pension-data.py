"""Build calculators/data/pension.json for the #pension page.

Reads the research series from /workspace/pension-bt/series.pkl (built by data.py there) and
exports, for calendar years 1927-2025, each asset's annual return NET of expense ratio
(monthly compounding, ER deducted monthly, exactly as pension-bt/sim.py build_windows) plus
the December CPI level for 1926-2025. A January-start window for year y uses calendar years
y..y+29, and its CPI index for year k is CPI[Dec y+k-1] / CPI[Dec y-1], so the browser can
rerun sim.py exactly. Also embeds the reference default results (summary_main.csv,
windows_by_start_year.csv for $1M) so the page and the test can verify they match.
"""
import json, numpy as np, pandas as pd, hashlib, os
BT = '/workspace/pension-bt/'
OUT = os.path.join(os.path.dirname(__file__), '..', 'calculators', 'data', 'pension.json')
S = pd.read_pickle(BT + 'series.pkl')
P = lambda s: pd.Period(s, 'M')
ER = dict(stock=.0003, agg=.0003, tips=.0005, natres=.0040)
S['natres_hair'] = S['natres'] - np.where(S.index < P('2010-10'), 0.02 / 12, 0)   # same as run.py
cols = {'stock': ('stock_crsp', 'stock'), 'agg': ('agg', 'agg'),
        **{f'tips_R{i}': (f'tips_R{i}', 'tips') for i in range(1, 6)},
        'natres': ('natres', 'natres'), 'natres_hair': ('natres_hair', 'natres')}
years = list(range(1927, 2026))
ret = {}
for key, (col, erk) in cols.items():
    m = 1 + (S[col] - ER[erk] / 12)
    out = []
    for y in years:
        seg = m.loc[P(f'{y}-01'):P(f'{y}-12')].values
        assert len(seg) == 12 and not np.isnan(seg).any(), (key, y)
        out.append(float(seg.prod() - 1))
    ret[key] = out
cpi = [float(S['cpi'].loc[P(f'{y}-12')]) for y in range(1926, 2026)]
summ = pd.read_csv(BT + 'summary_main.csv')
win = pd.read_csv(BT + 'windows_by_start_year.csv')
ref_cols = ['start_year', 'first_withdrawal_year', 'total_real_gross_withdrawals_2026usd'] + \
           [c for c in win.columns if '_1000k_' in c]
D = dict(
    note='Annual net-of-ER returns (decimal) by calendar year, and Dec CPI levels 1926-2025. Source: /workspace/pension-bt (research backtest).',
    years=years, cpi_dec_from=1926, cpi_dec=cpi,
    ret={k: [round(v, 12) for v in vs] for k, vs in ret.items()},
    ref=dict(summary=json.loads(summ.to_json(orient='records')),
             windows_1M=json.loads(win[ref_cols].to_json(orient='records'))),
)
s = json.dumps(D, separators=(',', ':'))
open(OUT, 'w').write(s)
print('wrote', OUT, len(s), 'bytes sha256', hashlib.sha256(s.encode()).hexdigest()[:12])
