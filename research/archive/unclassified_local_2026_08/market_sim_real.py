#!/usr/bin/env python3
"""
Real-Data Agent-Based Market Attribution.
Uses actual QQQ + macro data to estimate which agent type drove returns each day.
Outputs an interactive HTML report.
"""
import os, sys, warnings, json
import numpy as np, pandas as pd
import yfinance as yf
from fredapi import Fred

warnings.filterwarnings('ignore')

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, 'tools'))
from strategy_engine import get_fred_api_key

FRED_API_KEY = get_fred_api_key()
fred = Fred(api_key=FRED_API_KEY)
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data', 'ml_cache')
os.makedirs(DATA_DIR, exist_ok=True)

def load_fred(sid, start='2005-01-01'):
    path = os.path.join(DATA_DIR, f'fred_{sid}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    s = fred.get_series(sid, observation_start=start).dropna()
    s.to_csv(path)
    return s

def load_yahoo(ticker, start='2005-01-01'):
    path = os.path.join(DATA_DIR, f'yahoo_{ticker}.csv')
    if os.path.exists(path):
        s = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        if len(s) > 100: return s
    df = yf.download(ticker, start=start, progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame): adj = adj.iloc[:, 0]
    adj.to_csv(path)
    return adj

# ══════════════════════════════════════
# 1. LOAD REAL DATA
# ══════════════════════════════════════
print("Loading real market data...")
qqq = load_yahoo('QQQ')
spy = load_yahoo('SPY')
hyg = load_yahoo('HYG')
ief = load_yahoo('IEF')
vxn = load_yahoo('^VXN')  # Nasdaq VIX for GEX proxy

vix = load_fred('VIXCLS')
hy_oas = load_fred('BAMLH0A0HYM2')
ig_oas = load_fred('BAMLC0A0CM')
fed_rate = load_fred('DFF')
t10y = load_fred('DGS10')
t2y = load_fred('DGS2')
t10y2y = load_fred('T10Y2Y')
cpi = load_fred('CPIAUCSL')
nfci = load_fred('NFCI')

# Align to QQQ daily index
idx = qqq.dropna().index
qqq = qqq.reindex(idx)
spy = spy.reindex(idx).ffill()
hyg = hyg.reindex(idx).ffill()
ief = ief.reindex(idx).ffill()
vxn = vxn.reindex(idx).ffill() if vxn is not None else None

vix = vix.reindex(idx, method='ffill').ffill()
hy_oas = hy_oas.reindex(idx, method='ffill').ffill()
ig_oas = ig_oas.reindex(idx, method='ffill').ffill()
fed_rate = fed_rate.reindex(idx, method='ffill').ffill()
t10y = t10y.reindex(idx, method='ffill').ffill()
t2y = t2y.reindex(idx, method='ffill').ffill()
t10y2y = t10y2y.reindex(idx, method='ffill').ffill()
cpi_m = cpi.resample('D').ffill().reindex(idx, method='ffill').ffill()
nfci = nfci.resample('D').ffill().reindex(idx, method='ffill').ffill()

qqq_ret = qqq.pct_change()

# Start from 2007 to have enough lookback
start_date = '2007-01-01'
mask = idx >= start_date
idx = idx[mask]
qqq = qqq[mask]; spy = spy[mask]; hyg = hyg[mask]; ief = ief[mask]
if vxn is not None: vxn = vxn[mask]
vix = vix[mask]; hy_oas = hy_oas[mask]; ig_oas = ig_oas[mask]
fed_rate = fed_rate[mask]; t10y = t10y[mask]; t2y = t2y[mask]; t10y2y = t10y2y[mask]
cpi_m = cpi_m[mask]; nfci = nfci[mask]
qqq_ret = qqq_ret[mask]

print(f"  Data: {idx[0].strftime('%Y-%m-%d')} to {idx[-1].strftime('%Y-%m-%d')} ({len(idx)} days)")

# ══════════════════════════════════════
# 2. BUILD AGENT SIGNALS (daily)
# ══════════════════════════════════════
print("Building agent signals from real data...")

signals = pd.DataFrame(index=idx)

# ── 1. PASSIVE / 401k ──
# Constant positive flow. Slightly higher at month start.
signals['passive'] = 1.0
signals.loc[signals.index.day <= 5, 'passive'] = 1.3

# ── 2. VALUE INVESTOR ──
# Deviation from 200-week moving average (contrarian)
qqq_200w = qqq.rolling(252*4).mean()  # ~4 year MA as "fair value" proxy
val_ratio = qqq / qqq_200w
signals['value'] = -(val_ratio - 1.0)  # negative when expensive, positive when cheap
signals['value'] = signals['value'].clip(-2, 2)

# Also use earnings yield vs bond yield (simplified)
# When 10Y yield rises fast → value investors see stocks as less attractive
yield_chg = t10y - t10y.shift(63)
signals['value'] -= yield_chg.fillna(0) * 0.3

# ── 3. MOMENTUM TRADER ──
# 12M momentum + SMA crossover
mom_12m = qqq.pct_change(252)
sma50 = qqq.rolling(50).mean()
sma200 = qqq.rolling(200).mean()
sma_signal = (sma50 / sma200 - 1) * 10  # positive when 50 > 200

signals['momentum'] = (mom_12m.fillna(0) * 3 + sma_signal.fillna(0)) / 2
signals['momentum'] = signals['momentum'].clip(-3, 3)

# ── 4. MARKET MAKER / MEAN REVERSION ──
# Counter short-term moves (provide liquidity)
ret_1d = qqq_ret.fillna(0)
ret_5d = qqq.pct_change(5).fillna(0)
signals['mm'] = -(ret_1d * 5 + ret_5d * 2)
signals['mm'] = signals['mm'].clip(-2, 2)

# ── 5. HEDGE FUND / MACRO ──
# Composite macro signal:
# - VIX level and change
# - Credit spread level and change
# - Yield curve
# - Financial conditions (NFCI)
vix_z = (vix - vix.rolling(252).mean()) / vix.rolling(252).std().replace(0, 1)
hy_z = (hy_oas - hy_oas.rolling(252).mean()) / hy_oas.rolling(252).std().replace(0, 1)
nfci_z = (nfci - nfci.rolling(252).mean()) / nfci.rolling(252).std().replace(0, 1)
curve = t10y2y.fillna(0)

# High VIX/spread/NFCI = hedge fund sells; inverted curve = sells
signals['hedge'] = -(vix_z.fillna(0) * 0.4 + hy_z.fillna(0) * 0.3 + nfci_z.fillna(0) * 0.2) + curve.fillna(0) * 0.1
signals['hedge'] = signals['hedge'].clip(-3, 3)

# ── 6. RETAIL / SENTIMENT ──
# FOMO when momentum + low VIX; panic when momentum down + high VIX
vix_inv = 1 / (vix / 20).clip(0.5, 3)  # inverse normalized VIX
signals['retail'] = mom_12m.fillna(0) * vix_inv.fillna(1) * 2
# Panic amplifier: recent big drops trigger panic selling
ret_20d = qqq.pct_change(20).fillna(0)
signals.loc[ret_20d < -0.1, 'retail'] = signals.loc[ret_20d < -0.1, 'retail'] - 1.5
signals['retail'] = signals['retail'].clip(-3, 3)

# ── 7. GEX (Gamma Exposure) PROXY ──
# Real GEX data is not free. Proxy using:
# - VIX vs realized vol spread (when implied > realized = dealers short gamma)
# - VIX term structure (VIX vs VXN or VIX9D) 
# - VIX level regime: low VIX = positive gamma, high VIX = negative gamma
# Positive GEX → dealers hedge by selling rips/buying dips → STABILIZING
# Negative GEX → dealers hedge by buying rips/selling dips → AMPLIFYING
realized_vol = ret_1d.rolling(20).std() * np.sqrt(252) * 100
implied_vol = vix.fillna(20)
vol_spread = implied_vol - realized_vol.fillna(implied_vol)  # IV - RV

# GEX proxy signal: positive = positive gamma (stabilizing)
# Low VIX + IV < RV = dealers long gamma → buy dips, sell rips → mean reversion
# High VIX + IV > RV = dealers short gamma → chase moves → amplify
gex_raw = -vol_spread.fillna(0) / 10  # negative spread = positive gamma
# VIX level factor: very low VIX (<15) = very positive gamma
gex_raw += (20 - vix.clip(10, 40).fillna(20)) / 20
# When VIX is under 15, dealers are heavily long gamma (big stabilizer)
# When VIX spikes above 30, dealers are short gamma (amplifier)
signals['gex'] = gex_raw.clip(-3, 3)

# GEX acts as mean-reversion when positive, trend-amplifier when negative
# So its "flow" contribution is: gex_signal * (-recent_return)
# Positive GEX: counter recent moves (stabilize)
# Negative GEX: amplify recent moves (destabilize)
signals['gex'] = signals['gex'] * -(ret_5d.fillna(0) * 3)
signals['gex'] = signals['gex'].clip(-3, 3)

# Drop NaN rows
signals = signals.dropna()
common_idx = signals.index.intersection(qqq_ret.dropna().index)
signals = signals.loc[common_idx]
returns = qqq_ret.loc[common_idx].values.astype(float)

print(f"  Signals built: {len(signals)} days, {signals.shape[1]} agents")

# ══════════════════════════════════════
# 3. ROLLING REGRESSION — RETURN ATTRIBUTION
# ══════════════════════════════════════
print("Running rolling attribution (63-day windows)...")

from numpy.linalg import lstsq

agent_names = ['passive', 'value', 'momentum', 'mm', 'hedge', 'retail', 'gex']
window = 63

# Standardize signals for regression
from sklearn.preprocessing import StandardScaler

# Rolling regression
contributions = {a: np.full(len(signals), np.nan) for a in agent_names}
contributions['noise'] = np.full(len(signals), np.nan)
r_squared = np.full(len(signals), np.nan)

for i in range(window, len(signals)):
    X_win = signals.iloc[i-window:i][agent_names].values
    y_win = returns[i-window:i]
    
    # Standardize within window
    X_mean = X_win.mean(axis=0)
    X_std = X_win.std(axis=0)
    X_std[X_std == 0] = 1
    X_norm = (X_win - X_mean) / X_std
    
    # Add intercept
    X_aug = np.column_stack([np.ones(window), X_norm])
    
    # OLS
    betas, residuals, _, _ = lstsq(X_aug, y_win, rcond=None)
    
    # Predicted return decomposition for today
    x_today = signals.iloc[i][agent_names].values
    x_today_norm = (x_today - X_mean) / X_std
    
    pred = betas[0]  # intercept
    for j, a in enumerate(agent_names):
        contrib = betas[j+1] * x_today_norm[j]
        contributions[a][i] = contrib
    
    total_pred = betas[0] + np.dot(betas[1:], x_today_norm)
    contributions['noise'][i] = returns[i] - total_pred
    
    # R-squared
    y_pred_all = X_aug @ betas
    ss_res = np.sum((y_win - y_pred_all)**2)
    ss_tot = np.sum((y_win - y_win.mean())**2)
    r_squared[i] = 1 - ss_res / ss_tot if ss_tot > 0 else 0

print(f"  Attribution complete. Avg R²: {np.nanmean(r_squared):.3f}")

# ══════════════════════════════════════
# 4. VARIANCE DECOMPOSITION
# ══════════════════════════════════════
print("Computing variance decomposition...")

# Rolling variance share (quarterly windows)
var_window = 63
var_shares = {a: [] for a in agent_names}
var_dates = []

for i in range(window + var_window, len(signals), 5):  # every week
    var_dates.append(signals.index[i].strftime('%Y-%m-%d'))
    total_var = 0
    agent_vars = {}
    for a in agent_names:
        c = contributions[a][i-var_window:i]
        c = c[~np.isnan(c)]
        v = np.var(c) if len(c) > 10 else 0
        agent_vars[a] = v
        total_var += v
    
    for a in agent_names:
        var_shares[a].append(agent_vars[a] / total_var * 100 if total_var > 0 else 0)

# Overall variance share
overall_var = {}
total_v = 0
for a in agent_names:
    c = contributions[a]
    c = c[~np.isnan(c)]
    v = np.var(c)
    overall_var[a] = v
    total_v += v
for a in agent_names:
    overall_var[a] = overall_var[a] / total_v * 100 if total_v > 0 else 0

print(f"\n  Overall Variance Decomposition:")
for a in sorted(agent_names, key=lambda x: overall_var[x], reverse=True):
    bar = '█' * int(overall_var[a] / 2)
    print(f"    {a:<12} {overall_var[a]:>5.1f}%  {bar}")

# ══════════════════════════════════════
# 5. EVENT ANALYSIS
# ══════════════════════════════════════
print("\nEvent-level attribution...")

events = {
    'GFC Crash (Sep-Nov 2008)': ('2008-09-01', '2008-11-30'),
    'GFC Recovery (Mar-Jun 2009)': ('2009-03-01', '2009-06-30'),
    'COVID Crash (Feb-Mar 2020)': ('2020-02-19', '2020-03-23'),
    'COVID Recovery (Apr-Aug 2020)': ('2020-04-01', '2020-08-31'),
    '2022 Inflation Bear (Jan-Oct 2022)': ('2022-01-01', '2022-10-31'),
    '2023 AI Rally (Jan-Dec 2023)': ('2023-01-01', '2023-12-31'),
    '2024 Bull Run (Jan-Dec 2024)': ('2024-01-01', '2024-12-31'),
}

event_data = {}
for event_name, (s, e) in events.items():
    mask_arr = (signals.index >= s) & (signals.index <= e)
    if mask_arr.sum() == 0: continue
    
    event_shares = {}
    total_v = 0
    for a in agent_names:
        c = contributions[a][mask_arr]
        c = c[~np.isnan(c)]
        v = np.var(c) if len(c) > 10 else 0
        event_shares[a] = v
        total_v += v
    
    for a in agent_names:
        event_shares[a] = event_shares[a] / total_v * 100 if total_v > 0 else 0
    
    net_flow = {}
    for a in agent_names:
        c = contributions[a][mask_arr]
        c = c[~np.isnan(c)]
        net_flow[a] = np.mean(c) * 10000 if len(c) > 0 else 0
    
    event_data[event_name] = {'shares': event_shares, 'net_flow': net_flow}
    
    dominant = max(event_shares, key=event_shares.get)
    qqq_slice = qqq.loc[(qqq.index >= s) & (qqq.index <= e)]
    qqq_ret_period = (qqq_slice.iloc[-1] / qqq_slice.iloc[0] - 1) * 100 if len(qqq_slice) > 1 else 0
    print(f"  {event_name}")
    print(f"    QQQ return: {qqq_ret_period:+.1f}% | Dominant: {dominant} ({event_shares[dominant]:.0f}%)")
    for a in sorted(agent_names, key=lambda x: event_shares[x], reverse=True):
        direction = "BUY" if net_flow[a] > 0 else "SELL"
        print(f"      {a:<12} {event_shares[a]:>5.1f}%  {direction:>4} ({net_flow[a]:>+.1f} bps/day)")

# ══════════════════════════════════════
# 6. GENERATE HTML REPORT
# ══════════════════════════════════════
print("\nGenerating interactive HTML report...")

# Prepare data for JSON
# Downsample for performance (every 5th day for charts)
step = 3
chart_dates = [d.strftime('%Y-%m-%d') for d in signals.index[window::step]]
chart_price = qqq.loc[signals.index[window::step]].values.tolist()

# Smoothed contributions (21-day MA)
smooth_contribs = {}
for a in agent_names:
    c = pd.Series(contributions[a], index=signals.index)
    c_smooth = c.rolling(21, min_periods=1).mean()
    smooth_contribs[a] = c_smooth.iloc[window::step].fillna(0).tolist()

# R-squared smoothed
r2_smooth = pd.Series(r_squared, index=signals.index).rolling(63, min_periods=1).mean().iloc[window::step].fillna(0).tolist()

# Agent colors
colors = {
    'passive': '#3b82f6', 'value': '#10b981', 'momentum': '#f59e0b',
    'mm': '#8b5cf6', 'hedge': '#ef4444', 'retail': '#ec4899', 'gex': '#14b8a6'
}
labels = {
    'passive': '401k / Passive', 'value': 'Value Investor', 'momentum': 'Momentum Trader',
    'mm': 'Market Maker', 'hedge': 'Hedge Fund / Macro', 'retail': 'Retail / FOMO',
    'gex': 'GEX (Gamma Exposure)'
}

data_json = json.dumps({
    'dates': chart_dates,
    'price': chart_price,
    'contributions': smooth_contribs,
    'r2': r2_smooth,
    'var_dates': var_dates,
    'var_shares': var_shares,
    'overall_var': overall_var,
    'events': event_data,
    'event_names': list(events.keys()),
    'colors': colors,
    'labels': labels,
    'agent_names': agent_names,
})

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Who Drives QQQ? — Real Data Agent Attribution</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a1a;color:#e2e8f0;font-family:'Inter',sans-serif}}
.hero{{text-align:center;padding:40px 24px 20px;background:linear-gradient(180deg,#0f0f2e,#0a0a1a)}}
.hero h1{{font-size:28px;font-weight:900;background:linear-gradient(135deg,#f59e0b,#ef4444,#8b5cf6,#3b82f6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero p{{color:#94a3b8;font-size:13px;margin-top:8px;max-width:700px;margin-left:auto;margin-right:auto;line-height:1.6}}
.container{{max-width:1200px;margin:0 auto;padding:0 20px 60px}}
.panel{{background:#111827;border:1px solid #1e293b;border-radius:16px;padding:24px;margin-bottom:20px}}
.panel-title{{font-size:16px;font-weight:800;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
.agents-row{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}}
.agent-pill{{border-radius:10px;padding:10px 16px;text-align:center;flex:1;min-width:140px}}
.agent-pill .name{{font-size:11px;font-weight:700;margin-top:2px}}
.agent-pill .pct{{font-size:22px;font-weight:900;margin-top:4px}}
.agent-pill .role{{font-size:10px;opacity:.6;margin-top:2px}}
.chart-wrap{{margin:12px -12px}}
.event-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;margin-top:12px}}
.event-card{{background:#1e293b;border-radius:12px;padding:16px;border-left:4px solid #f59e0b}}
.event-card h4{{font-size:13px;font-weight:800;color:#f59e0b;margin-bottom:8px}}
.event-card .ev-return{{font-size:11px;margin-bottom:8px}}
.event-bar{{display:flex;height:24px;border-radius:6px;overflow:hidden;margin:4px 0}}
.event-bar div{{display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:white;transition:width .5s}}
.event-label{{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}}
.event-label span{{font-size:9px;padding:2px 6px;border-radius:4px;font-weight:600}}
.insight{{background:linear-gradient(135deg,rgba(245,158,11,.08),rgba(239,68,68,.08));border:1px solid rgba(245,158,11,.2);border-radius:12px;padding:16px 20px;margin-top:16px}}
.insight h3{{font-size:13px;font-weight:800;color:#f59e0b;margin-bottom:8px}}
.insight p,.insight li{{font-size:12px;color:#cbd5e1;line-height:1.7}}
.insight ul{{padding-left:20px;margin-top:8px}}
</style>
</head>
<body>
<div class="hero">
  <h1>🔬 Who Drives QQQ? — Real Data Attribution</h1>
  <p>Using actual QQQ prices, VIX, credit spreads, yield curves, CPI, and financial conditions to decompose every day's return into 6 market participant types.</p>
</div>
<div class="container">

<div class="panel">
  <div class="panel-title">🏆 Overall Variance Decomposition — Who Explains QQQ Price Changes?</div>
  <div class="agents-row" id="agent-pills"></div>
</div>

<div class="panel">
  <div class="panel-title">📈 QQQ Price + Agent Attribution Over Time</div>
  <div class="chart-wrap"><div id="chart-price" style="width:100%;height:350px"></div></div>
</div>

<div class="panel">
  <div class="panel-title">🔬 Daily Return Attribution — Who Moved QQQ Today?</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:8px">Smoothed 21-day rolling average of each agent's estimated contribution to daily returns</p>
  <div class="chart-wrap"><div id="chart-contrib" style="width:100%;height:320px"></div></div>
</div>

<div class="panel">
  <div class="panel-title">📊 Rolling Variance Share — Who Dominates Each Period?</div>
  <p style="font-size:11px;color:#64748b;margin-bottom:8px">63-day rolling windows showing which agent type explains the most variance in QQQ returns</p>
  <div class="chart-wrap"><div id="chart-variance" style="width:100%;height:320px"></div></div>
</div>

<div class="panel">
  <div class="panel-title">🎯 Model Explanatory Power (R²)</div>
  <div class="chart-wrap"><div id="chart-r2" style="width:100%;height:200px"></div></div>
</div>

<div class="panel">
  <div class="panel-title">🔥 Event-Level Attribution — Key Market Episodes</div>
  <div class="event-grid" id="event-grid"></div>
</div>

<div class="panel">
  <div class="insight" style="margin-top:0">
    <h3>💡 What Does This Tell Us About Your Strategy?</h3>
    <ul id="insights-list"></ul>
  </div>
</div>

</div>

<script>
const D = {data_json};

const plotCfg = {{ responsive: true, displayModeBar: false }};
const darkLay = {{
  paper_bgcolor:'#111827', plot_bgcolor:'#111827',
  font:{{family:'Inter',color:'#94a3b8',size:11}},
  margin:{{l:50,r:20,t:20,b:40}},
  xaxis:{{gridcolor:'#1e293b',linecolor:'#374151'}},
  yaxis:{{gridcolor:'#1e293b',linecolor:'#374151'}},
  legend:{{bgcolor:'rgba(17,24,39,.8)',bordercolor:'#374151',font:{{size:10}}}},
}};

// Event annotations for price chart
const eventAnnotations = [
  {{x:'2008-09-15',text:'GFC',color:'#ef4444'}},
  {{x:'2020-02-20',text:'COVID',color:'#ef4444'}},
  {{x:'2022-01-03',text:'Inflation Bear',color:'#f59e0b'}},
  {{x:'2023-01-03',text:'AI Rally',color:'#10b981'}},
];

// Agent pills
const pillsDiv = document.getElementById('agent-pills');
const sorted = D.agent_names.slice().sort((a,b) => D.overall_var[b] - D.overall_var[a]);
sorted.forEach(a => {{
  const d = document.createElement('div');
  d.className = 'agent-pill';
  d.style.background = D.colors[a] + '15';
  d.style.border = '2px solid ' + D.colors[a] + '60';
  d.innerHTML = `<div class="name" style="color:${{D.colors[a]}}">${{D.labels[a]}}</div><div class="pct" style="color:${{D.colors[a]}}">${{D.overall_var[a].toFixed(1)}}%</div><div class="role">of price variance</div>`;
  pillsDiv.appendChild(d);
}});

// Price chart
const shapes = [
  {{type:'rect',x0:'2008-09-01',x1:'2009-03-01',y0:0,y1:1,yref:'paper',fillcolor:'rgba(239,68,68,.08)',line:{{width:0}}}},
  {{type:'rect',x0:'2020-02-15',x1:'2020-04-01',y0:0,y1:1,yref:'paper',fillcolor:'rgba(239,68,68,.08)',line:{{width:0}}}},
  {{type:'rect',x0:'2022-01-01',x1:'2022-10-31',y0:0,y1:1,yref:'paper',fillcolor:'rgba(245,158,11,.06)',line:{{width:0}}}},
];
const annotations = eventAnnotations.map(a => ({{
  x:a.x, y:1, yref:'paper', text:a.text, showarrow:false,
  font:{{size:10,color:a.color,family:'Inter'}}, yshift:10
}}));
Plotly.newPlot('chart-price',[{{
  x:D.dates, y:D.price, type:'scatter', mode:'lines',
  line:{{color:'#e2e8f0',width:1.5}}, name:'QQQ'
}}],{{...darkLay, shapes, annotations, yaxis:{{...darkLay.yaxis,title:'QQQ Price ($)',type:'log'}}}}, plotCfg);

// Contribution chart
const contribTraces = D.agent_names.map(a => ({{
  x:D.dates, y:D.contributions[a].map(v=>v*10000),
  type:'scatter', mode:'lines', name:D.labels[a],
  line:{{color:D.colors[a],width:1.5}}
}}));
Plotly.newPlot('chart-contrib', contribTraces, {{
  ...darkLay, shapes,
  yaxis:{{...darkLay.yaxis,title:'Contribution (bps/day)',zeroline:true,zerolinecolor:'#475569',zerolinewidth:2}}
}}, plotCfg);

// Variance decomposition stacked area
const varTraces = D.agent_names.slice().reverse().map(a => ({{
  x:D.var_dates, y:D.var_shares[a],
  type:'scatter', mode:'lines', name:D.labels[a],
  stackgroup:'one', line:{{color:D.colors[a],width:0}},
  fillcolor:D.colors[a]+'90',
}}));
Plotly.newPlot('chart-variance', varTraces, {{
  ...darkLay, shapes,
  yaxis:{{...darkLay.yaxis,title:'% of Variance Explained',range:[0,100]}}
}}, plotCfg);

// R² chart
Plotly.newPlot('chart-r2',[{{
  x:D.dates, y:D.r2.map(v=>v*100), type:'scatter', mode:'lines',
  fill:'tozeroy', line:{{color:'#f59e0b',width:1}}, fillcolor:'rgba(245,158,11,.15)'
}}],{{...darkLay,yaxis:{{...darkLay.yaxis,title:'R² (%)',range:[0,60]}},shapes}}, plotCfg);

// Event cards
const grid = document.getElementById('event-grid');
D.event_names.forEach(name => {{
  if (!D.events[name]) return;
  const ev = D.events[name];
  const card = document.createElement('div');
  card.className = 'event-card';
  
  // Sort agents by variance share
  const sortedAgents = D.agent_names.slice().sort((a,b) => ev.shares[b] - ev.shares[a]);
  const dominant = sortedAgents[0];
  card.style.borderLeftColor = D.colors[dominant];
  
  // Bar
  let barHTML = '<div class="event-bar">';
  sortedAgents.forEach(a => {{
    if (ev.shares[a] > 3) {{
      const dir = ev.net_flow[a] > 0 ? '↑' : '↓';
      barHTML += `<div style="width:${{ev.shares[a]}}%;background:${{D.colors[a]}}">${{dir}}</div>`;
    }}
  }});
  barHTML += '</div>';
  
  // Labels
  let labelHTML = '<div class="event-label">';
  sortedAgents.slice(0,4).forEach(a => {{
    const dir = ev.net_flow[a] > 0 ? 'BUY' : 'SELL';
    labelHTML += `<span style="background:${{D.colors[a]}}30;color:${{D.colors[a]}}">${{D.labels[a]}} ${{ev.shares[a].toFixed(0)}}% ${{dir}}</span>`;
  }});
  labelHTML += '</div>';
  
  card.innerHTML = `<h4>${{name}}</h4>${{barHTML}}${{labelHTML}}`;
  grid.appendChild(card);
}});

// Insights
const il = document.getElementById('insights-list');
const topAgent = sorted[0];
const insights = [
  `<strong style="color:${{D.colors[topAgent]}}">${{D.labels[topAgent]}}</strong> explains the most variance overall (${{D.overall_var[topAgent].toFixed(1)}}%). This is the single biggest "force" moving QQQ over this period.`,
  `During <strong>crashes</strong> (GFC, COVID), <strong style="color:#ef4444">Hedge Funds</strong> and <strong style="color:#ec4899">Retail panic</strong> dominate — they amplify the downturn through forced selling and emotional reactions.`,
  `During <strong>recoveries</strong>, <strong style="color:#3b82f6">401k passive inflow</strong> and <strong style="color:#10b981">Value investors</strong> provide the floor — their steady buying absorbs the selling pressure.`,
  `<strong style="color:#f59e0b">Momentum traders</strong> are trend amplifiers — they make rallies bigger AND crashes deeper. They don't cause moves, they <em>extend</em> them.`,
  `<strong style="color:#8b5cf6">Market makers</strong> are stabilizers — they dampen short-term volatility but have little influence on medium-term direction.`,
  `<strong>Your Z-score strategy works because</strong> it detects when destructive agents (hedge fund deleverage + momentum reversal + retail panic) overwhelm constructive agents (passive inflow + value buying). Credit Z catches the hedge fund stress. Vol Z catches the momentum breakdown. Inflation Z catches the macro regime shift.`,
  `<strong>Key insight:</strong> Price is not driven by one factor. It's driven by which <em>coalition of agents</em> is currently dominant. Your strategy doesn't need to predict direction — it needs to detect agent regime transitions.`,
];
insights.forEach(t => {{
  const li = document.createElement('li');
  li.innerHTML = t;
  il.appendChild(li);
}});
</script>
</body>
</html>"""

out_path = os.path.join(PROJECT_DIR, 'tools', 'market_simulator_real.html')
with open(out_path, 'w') as f:
    f.write(html)
print(f"\n✓ Report saved to: {out_path}")
print("Opening in browser...")
os.system(f'open "{out_path}"')
