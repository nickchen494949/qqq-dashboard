#!/usr/bin/env python3
"""
QQQ 庄家策略 Dashboard Generator (Webull Light Theme)
=====================================
Strategy: SEP (Primary) + -(HYG/IEF) Credit Stress TP (Secondary)
"""
import sys, os, json, re
import pypdf
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred
import warnings
warnings.filterwarnings('ignore')

FRED_API_KEY = os.environ.get('FRED_API_KEY', 'f64f7d1a98a7dd021a155ce2b9703fdb')
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data')
os.makedirs(DATA_DIR, exist_ok=True)

import time as _time

def _fred_is_reachable(timeout=5):
    import urllib.request
    try:
        urllib.request.urlopen('https://api.stlouisfed.org/fred/', timeout=timeout)
        return True
    except Exception:
        return False

_FRED_AVAILABLE = _fred_is_reachable()

def load_or_fetch_fred(series_id, retries=2):
    path = os.path.join(DATA_DIR, f'fred_{series_id}.csv')
    cached = None
    if os.path.exists(path):
        cached = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        cached = cached[~cached.index.duplicated(keep='last')]
    
    if not _FRED_AVAILABLE:
        if cached is not None and len(cached) > 100:
            return cached
        raise ConnectionError(f"FRED is unreachable and no cache for {series_id}")
    
    fred = Fred(api_key=FRED_API_KEY)
    start = cached.index[-1].strftime('%Y-%m-%d') if cached is not None and len(cached) > 0 else '2003-01-01'
    
    new = None
    for attempt in range(retries):
        try:
            result = fred.get_series(series_id, observation_start=start)
            if result is not None and len(result) > 0:
                new = result.dropna()
            break
        except Exception as e:
            if attempt < retries - 1:
                _time.sleep(1)
            else:
                if cached is not None and len(cached) > 100:
                    return cached
                raise
    
    if cached is not None and len(cached) > 0:
        combined = pd.concat([cached, new])
        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
    else:
        combined = new
    
    combined.to_csv(path)
    return combined

def load_or_fetch_yahoo(ticker, name):
    path = os.path.join(DATA_DIR, f'yahoo_{name}.csv')
    cached = None
    if os.path.exists(path):
        cached = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        cached = cached[~cached.index.duplicated(keep='last')]
    
    start = cached.index[-5].strftime('%Y-%m-%d') if cached is not None and len(cached) > 5 else '2005-01-01'
    df = yf.download(ticker, start=start, progress=False, auto_adjust=False)
    adj = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    if isinstance(adj, pd.DataFrame):
        adj = adj.iloc[:, 0]
    
    if cached is not None and len(cached) > 0:
        combined = pd.concat([cached, adj])
        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
    else:
        combined = adj
    
    combined.to_csv(path)
    return combined

effr = load_or_fetch_fred('DFF')
qqq = load_or_fetch_yahoo('QQQ', 'QQQ')
tqqq = load_or_fetch_yahoo('TQQQ', 'TQQQ')
qld = load_or_fetch_yahoo('QLD', 'QLD')
hyg = load_or_fetch_yahoo('HYG', 'HYG')
ief = load_or_fetch_yahoo('IEF', 'IEF')

idx = qqq.index[qqq.index >= pd.Timestamp('2012-01-25')]
qqq_d = qqq.reindex(idx)
dr = qqq_d.pct_change()
tqqq_d = tqqq.reindex(idx).ffill()
qld_d = qld.reindex(idx).ffill()
dr_tqqq = tqqq_d.pct_change()
dr_qld = qld_d.pct_change()
dr_qqq = dr
ef = effr.reindex(idx).ffill() / 100 / 252
hyg_d = hyg.reindex(idx).ffill()
ief_d = ief.reindex(idx).ffill()

source_dates = {
    'qqq': qqq.dropna().index[-1].strftime('%Y-%m-%d'),
    'tqqq': tqqq.dropna().index[-1].strftime('%Y-%m-%d'),
    'hyg': hyg.dropna().index[-1].strftime('%Y-%m-%d'),
    'ief': ief.dropna().index[-1].strftime('%Y-%m-%d'),
}

hyg_ief = hyg_d / ief_d
ma252 = hyg_ief.rolling(252).mean()
sd252 = hyg_ief.rolling(252).std()

# INVERTED Z-SCORE: -(HYG/IEF) so that higher values = higher stress
z_series = -(hyg_ief - ma252) / sd252

# VOLATILITY Z-SCORE
rvol_20 = dr.rolling(20).std() * np.sqrt(252)
vol_mean = rvol_20.rolling(252).mean()
vol_std = rvol_20.rolling(252).std()
vol_z = (rvol_20 - vol_mean) / vol_std

SEP_DIR = os.path.join(PROJECT_DIR, 'fomc_sep')
sep_table_data = []
if os.path.isdir(SEP_DIR):
    sep_pdfs = sorted([f for f in os.listdir(SEP_DIR) if f.endswith('.pdf')])
    sep_raw = []
    for fn in sep_pdfs:
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', fn)
        if not m: continue
        meeting_year = int(m.group(1))
        meeting_month = int(m.group(2))
        try:
            reader = pypdf.PdfReader(os.path.join(SEP_DIR, fn))
            text = ''.join(pg.extract_text()+'\n' for pg in reader.pages[:3])
        except: continue
        cp_all, fr_all = [], []
        lines = text.split('\n')
        for li, line in enumerate(lines):
            if not cp_all and re.search(r'Core\s*PCE\s*in[f\uFB02]', line, re.IGNORECASE) and not re.search(r'projection|september|june|march|december|january|november', line, re.IGNORECASE):
                cp_all = [float(x) for x in re.findall(r'(\d+\.\d+)', line)]
            if not fr_all and re.search(r'Federal\s*funds\s*rate', line, re.IGNORECASE) and not re.search(r'projection|september|june|march|december|january|november', line, re.IGNORECASE):
                fr_all = [float(x) for x in re.findall(r'(\d+\.\d+)', line)]
                if not fr_all:
                    for offset in range(1, 4):
                        if li + offset < len(lines):
                            nxt = lines[li + offset].strip()
                            if re.search(r'projection', nxt, re.IGNORECASE): continue
                            fr_all = [float(x) for x in re.findall(r'(\d+\.\d+)', nxt)]
                            if fr_all: break
        pce_by_year = {meeting_year + j: v for j, v in enumerate(cp_all[:4])}
        rate_by_year = {meeting_year + j: v for j, v in enumerate(fr_all[:4])}
        target_year = meeting_year if meeting_month < 9 else meeting_year + 1
        sep_raw.append({
            'date': f'{m.group(1)}-{m.group(2)}-{m.group(3)}',
            'target_year': target_year,
            'pce': pce_by_year.get(target_year),
            'rate': rate_by_year.get(target_year),
            'pce_by_year': pce_by_year,
            'rate_by_year': rate_by_year,
        })

    _ffr_by_target = {
        ('2012-01-25', 2012): 0.13, ('2012-04-25', 2012): 0.13,
        ('2012-06-20', 2012): 0.13,
        ('2012-09-13', 2013): 0.13, ('2012-12-12', 2013): 0.13,
        ('2013-03-20', 2013): 0.13, ('2013-06-19', 2013): 0.13,
        ('2013-09-18', 2014): 0.13, ('2013-12-18', 2014): 0.13,
        ('2014-03-19', 2014): 0.13, ('2014-06-18', 2014): 0.13,
        ('2014-09-17', 2015): 1.38, ('2014-12-17', 2015): 0.63,
        ('2015-03-18', 2015): 0.63, ('2015-06-17', 2015): 0.63,
        ('2015-09-17', 2016): 0.38, ('2015-12-16', 2016): 1.4,
        ('2018-12-19', 2019): 2.9,
    }
    for row in sep_raw:
        ty = row['target_year']
        key = (row['date'], ty)
        if row['rate'] is None and key in _ffr_by_target:
            row['rate'] = _ffr_by_target[key]
            row['rate_by_year'][ty] = _ffr_by_target[key]

    sep_in = True
    for i in range(1, len(sep_raw)):
        c, p = sep_raw[i], sep_raw[i-1]
        ty = c['target_year']
        c_pce = c['pce_by_year'].get(ty)
        c_rate = c['rate_by_year'].get(ty)
        p_pce = p['pce_by_year'].get(ty)
        p_rate = p['rate_by_year'].get(ty)
        if c_pce is None: continue
        has_both = all(pd.notna(x) for x in [c_pce, c_rate, p_pce, p_rate])
        rate_up = c_rate > p_rate if has_both else False
        pce_above2 = c_pce > 2.0
        pce_up = c_pce > p_pce if has_both else False
        is_exit = rate_up and pce_above2 and pce_up if has_both else False
        reenter = (c_rate <= p_rate) if has_both else False
        
        signal = ''
        if sep_in and is_exit:
            signal = 'EXIT'
            sep_in = False
        elif not sep_in and reenter:
            signal = 'ENTER'
            sep_in = True
            
        sep_table_data.append({
            'date': c['date'], 'target_year': ty,
            'pce': c_pce, 'prev_pce': p_pce,
            'rate': c_rate, 'prev_rate': p_rate,
            'signal': signal,
        })
sep_signal_dates = {pd.Timestamp(r['date']): r['signal'] for r in sep_table_data if r['signal']}

sep_state = pd.Series(1, index=idx)
s = 1
for d in idx:
    if d in sep_signal_dates: s = 1 if sep_signal_dates[d]=='ENTER' else 0
    sep_state[d] = s

def run_strategy(use_overlay=True):
    eq = 1.0; lev = 3.0; prev_lev = 3.0
    pending = None; eql = []; levs = []
    
    in_trade = False
    trade_entry_eq = 1.0
    in_danger = False
    vol_danger = False
    trades = 0
    
    for i in range(len(idx)):
        si = sep_state.iloc[i]
        d = idx[i]
        
        if pending is not None:
            lev = pending; pending = None
            
        is_profitable = (eq > trade_entry_eq) if in_trade else False
        z = z_series.iloc[i]
        
        tgt = 3
        if si == 0:
            tgt = 0
            in_danger = False; vol_danger = False
        else:
            if use_overlay:
                if not np.isnan(z):
                    if not in_danger and z > 1.2:
                        in_danger = True
                    elif in_danger and z < 0.2:
                        in_danger = False
                
                vz = vol_z.iloc[i] if i < len(vol_z) else np.nan
                if not np.isnan(vz):
                    if not vol_danger and vz > 1.0:
                        vol_danger = True
                    elif vol_danger and vz < -0.5:
                        vol_danger = False
                        
                if in_danger:
                    if is_profitable: tgt = 1
                    else: tgt = 3
                elif vol_danger:
                    if is_profitable: tgt = 2
                    else: tgt = lev
                else:
                    tgt = 3
            else:
                tgt = 3
                
        if tgt != lev:
            pending = tgt
            
        if lev > 0 and not in_trade:
            in_trade = True
            trade_entry_eq = eq
        elif lev == 0 and in_trade:
            in_trade = False
            
        if lev != prev_lev:
            trades += 1
            
        if i > 0:
            # Use real ETF returns
            if lev == 3:   r_day = dr_tqqq.iloc[i]
            elif lev == 2: r_day = dr_qld.iloc[i]
            elif lev == 1: r_day = dr_qqq.iloc[i]
            else:          r_day = ef.iloc[i]  # cash
            if np.isnan(r_day): r_day = 0
            tc = abs(lev - prev_lev) * (25/10000)
            eq *= (1 + r_day - tc)
            eq = max(eq, 0.001)
            
        prev_lev = lev
        eql.append(eq)
        levs.append(lev)
        
    es = pd.Series(eql, index=idx)
    ny = len(es)/252
    cagr = es.iloc[-1]**(1/ny) - 1
    mdd = ((es / es.expanding().max()) - 1).min()
    return es, levs, [], cagr, mdd, trades

es_base, lev_base, _, cagr_base, mdd_base, tr_base = run_strategy(use_overlay=False)
es_opt, lev_opt, _, cagr_opt, mdd_opt, tr_opt = run_strategy(use_overlay=True)

# Buy and Hold TQQQ
bh_eq = tqqq_d / tqqq_d.iloc[0]
ny = len(bh_eq)/252
cagr_bh = bh_eq.iloc[-1]**(1/ny) - 1
mdd_bh = ((bh_eq / bh_eq.expanding().max()) - 1).min()

def sw(series):
    d = series.resample('W').last().dropna()
    return list(zip([x.strftime('%Y-%m-%d') for x in d.index], [round(float(v), 4) for v in d.values]))

cur_sep_state = 'IN' if sep_state.iloc[-1] == 1 else 'OUT'
cur_lev = lev_opt[-1]
cur_z = round(float(z_series.iloc[-1]), 2)
cur_vol_z = round(float(vol_z.dropna().iloc[-1]), 2) if len(vol_z.dropna()) > 0 else 0
cur_price = round(float(tqqq.dropna().iloc[-1]), 2)

data_json = json.dumps({
    'dates': [d.strftime('%Y-%m-%d') for d in idx],
    'eq_bh': sw(bh_eq),
    'eq_base': sw(es_base),
    'eq_opt': sw(es_opt),
    'z_score': sw(z_series),
    'vol_z': sw(vol_z.dropna()),
    'lev_opt': list(zip([d.strftime('%Y-%m-%d') for d in idx[::5]], lev_opt[::5])),
    'latest': {
        'date': idx[-1].strftime('%Y-%m-%d'),
        'sep_state': cur_sep_state,
        'leverage': f"{int(cur_lev)}x",
        'z_score': cur_z,
        'vol_z': cur_vol_z,
        'price': cur_price,
        'cagr_bh': round(cagr_bh*100, 1),
        'mdd_bh': round(mdd_bh*100, 1),
        'cagr_base': round(cagr_base*100, 1),
        'mdd_base': round(mdd_base*100, 1),
        'cagr_opt': round(cagr_opt*100, 1),
        'mdd_opt': round(mdd_opt*100, 1),
        'trades_opt': tr_opt,
    },
    'source_dates': source_dates,
    # Filter SEP table to only show 2012 onwards
    'sep_table': [r for r in sep_table_data if pd.Timestamp(r['date']) >= pd.Timestamp('2012-01-25')],
    'generated_at': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
})

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Webull Strategy Overview</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#F4F5F7; color:#111827; font-family:'Roboto',sans-serif; padding-bottom:40px; font-size:13px; }}
  
  /* Webull Header */
  .top-bar {{ display:flex; justify-content:space-between; align-items:center; background:#FFFFFF; padding:16px 24px; box-shadow:0 1px 3px rgba(0,0,0,0.05); margin-bottom:24px; }}
  .top-bar .left-logo {{ display:flex; align-items:center; font-size:22px; font-weight:700; color:#111827; }}
  .top-bar .left-logo .icon {{ width:28px; height:28px; background:#0055FF; border-radius:50%; margin-right:12px; display:flex; justify-content:center; align-items:center; color:white; font-size:16px; font-weight:700; }}
  .top-bar .menu {{ display:flex; gap:24px; font-size:14px; font-weight:500; color:#111827; }}
  .top-bar .menu .active {{ color:#0055FF; border-bottom:2px solid #0055FF; padding-bottom:18px; margin-bottom:-18px; }}
  
  .container {{ max-width: 1400px; margin: 0 auto; padding: 0 24px; }}
  
  /* Cards */
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:24px; }}
  .card {{ background:#FFFFFF; border:1px solid #EBEBEB; border-radius:8px; padding:20px; box-shadow:0 1px 2px rgba(0,0,0,0.02); }}
  .card .header-row {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }}
  .card .label {{ font-size:16px; font-weight:700; color:#111827; }}
  .card .more {{ font-size:12px; color:#A6B0C3; font-weight:500; }}
  .card .value {{ font-size:28px; font-weight:700; color:#111827; margin-bottom:4px; }}
  .card .sub {{ font-size:12px; color:#6B7280; }}
  
  /* Typography Colors */
  .color-green {{ color:#00C805 !important; }}
  .color-red {{ color:#FF333A !important; }}
  .color-neutral {{ color:#111827 !important; }}
  .color-blue {{ color:#0055FF !important; }}
  
  .panels {{ display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-bottom:16px; align-items: stretch; }}
  @media (max-width: 1000px) {{ .panels {{ grid-template-columns:1fr; }} }}
  
  .panel {{ background:#FFFFFF; border:1px solid #EBEBEB; border-radius:8px; box-shadow:0 1px 2px rgba(0,0,0,0.02); display:flex; flex-direction:column; overflow:hidden; }}
  .panel-header {{ padding:16px 20px; border-bottom:1px solid #F0F0F0; font-weight:700; color:#111827; font-size:16px; display:flex; justify-content:space-between; align-items:center; }}
  .panel-header .note {{ font-size:12px; color:#A6B0C3; font-weight:400; }}
  .panel-body {{ padding:20px; flex-grow:1; }}
  
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ padding:12px 8px; text-align:left; color:#6B7280; font-weight:500; border-bottom:1px solid #F0F0F0; position:sticky; top:0; background:#FFFFFF; z-index:10; }}
  td {{ padding:12px 8px; color:#111827; border-bottom:1px solid #F0F0F0; }}
  tr:hover {{ background:#F9FAFB; }}
  .sig-exit {{ color:#FF333A; font-weight:700; }}
  .sig-enter {{ color:#00C805; font-weight:700; }}
  
  .perf-grid {{ display:grid; grid-template-columns:1fr; gap:16px; }}
  .perf-item {{ display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #F0F0F0; padding-bottom:12px; }}
  .perf-item .k {{ color:#6B7280; font-weight:500; }}
  .perf-item .v {{ font-weight:700; color:#111827; font-size:16px; }}
  
  .math-box {{ background:#F9FAFB; border:1px solid #EBEBEB; padding:12px 16px; border-radius:6px; margin-bottom:16px; color:#4B5563; font-size:13px; line-height:1.5; }}
</style>
</head>
<body>

<div class="top-bar">
  <div class="left-logo">
    <div class="icon">W</div>
    TQQQ Strategy
  </div>
  <div class="menu">
    <div class="active">Overview</div>
  </div>
</div>

<div class="container">
  
  <div class="cards" id="cards"></div>

  <div class="panels">
    <div class="panel">
      <div class="panel-header">
        <div>Equity Growth & Target Leverage</div>
        <div class="note">Log Scale • Since 2012</div>
      </div>
      <div class="panel-body" style="padding:0;">
        <div id="chart_equity" style="width:100%;height:400px;"></div>
      </div>
    </div>
    
    <div class="panel">
      <div class="panel-header">Historical Performance</div>
      <div class="panel-body" style="padding:20px 20px 0 20px;">
        <div style="color:#0055FF; font-weight:700; margin-bottom:12px; font-size:14px;">Protected Strategy (Current)</div>
        <div class="perf-grid" id="perf-opt" style="margin-bottom:20px;"></div>
        
        <div style="color:#6B7280; font-weight:700; margin-bottom:12px; font-size:14px;">Base TQQQ+SEP (No TP)</div>
        <div class="perf-grid" id="perf-base" style="margin-bottom:20px;"></div>
        
        <div style="color:#A6B0C3; font-weight:700; margin-bottom:12px; font-size:14px;">TQQQ Buy & Hold</div>
        <div class="perf-grid" id="perf-bh"></div>
      </div>
    </div>
  </div>

  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <div>-(HYG / IEF) Credit Stress Radar</div>
      <div class="note">TP &gt; 1.2 | Re-enter &lt; 0.2</div>
    </div>
    <div class="panel-body">
      <div class="math-box">
        <strong>Z-Score = distance from 252-day SMA, measured in standard deviations.</strong><br>
        Formula: <code>Z = -(HYG/IEF - SMA252) / StdDev252</code><br>
        The negative sign inverts the chart: <strong>UP = stress rising</strong>. When Z &gt; 1.2, HYG/IEF has fallen more than 1.2 standard deviations below its yearly average — a credit stress event.
      </div>
      <div id="chart_z" style="width:100%;height:300px;"></div>
    </div>
  </div>
  
  <div class="panel" style="margin-bottom:16px;">
    <div class="panel-header">
      <div>Realized Volatility Z-Score Radar</div>
      <div class="note">TP (66% TQQQ) &gt; 1.0 | Re-enter (100%) &lt; -0.5</div>
    </div>
    <div class="panel-body">
      <div class="math-box">
        <strong>Vol Z-Score = 20-day annualized realized volatility relative to its 252-day history.</strong><br>
        When Z &gt; 1.0, market turbulence is abnormally high. We reduce to 66% TQQQ (if profitable). Recovery requires Z &lt; -0.5 (wide hysteresis to prevent whipsaws).
      </div>
      <div id="chart_vol" style="width:100%;height:300px;"></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-header">
      <div>Fed SEP Projections (Primary Engine)</div>
      <div class="note">Showing Data from 2012 Onwards</div>
    </div>
    <div class="panel-body" style="padding:0; overflow-x:auto; max-height:400px; overflow-y:auto;">
      <table id="sep-table"></table>
    </div>
  </div>

</div>

<script>
const D = {data_json};
const L = D.latest;

const cardsEl = document.getElementById('cards');

const zColor = L.z_score > 1.2 ? 'color-red' : (L.z_score < 0.2 ? 'color-green' : 'color-neutral');
const zText = L.z_score > 1.2 ? 'RISK OFF (TP 1x)' : (L.z_score < 0.2 ? 'SAFE ZONE' : 'WATCH (HYSTERESIS)');

const volColor = L.vol_z > 1.0 ? 'color-red' : (L.vol_z < -0.5 ? 'color-green' : 'color-neutral');
const volText = L.vol_z > 1.0 ? 'VOL SPIKE → 66% TQQQ' : (L.vol_z < -0.5 ? 'SAFE → 100% TQQQ' : 'WATCH (HYSTERESIS)');

const levColor = L.leverage === '3x' ? 'color-green' : (L.leverage === '1x' ? 'color-red' : 'color-neutral');
const sepColor = L.sep_state === 'IN' ? 'color-green' : 'color-red';

cardsEl.innerHTML = `
  <div class="card">
    <div class="header-row"><div class="label">Fed SEP Position</div><div class="more">Primary</div></div>
    <div class="value ${{sepColor}}">${{L.sep_state}}</div>
    <div class="sub">Macro Economic Engine</div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">-(HYG/IEF) Credit Stress</div></div>
    <div class="value ${{zColor}}">${{L.z_score.toFixed(2)}}</div>
    <div class="sub">${{zText}}</div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">Volatility Z-Score</div></div>
    <div class="value ${{volColor}}">${{L.vol_z.toFixed(2)}}</div>
    <div class="sub">${{volText}}</div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">Target Leverage</div><div class="more">Protected</div></div>
    <div class="value ${{levColor}}">${{L.leverage}}</div>
    <div class="sub">NSL Rules Active</div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">TQQQ Last Price</div><div class="more">Yahoo</div></div>
    <div class="value">$${{L.price.toFixed(2)}}</div>
    <div class="sub">Data: ${{L.date}}</div>
  </div>
`;

document.getElementById('perf-opt').innerHTML = `
  <div class="perf-item"><span class="k">CAGR</span><span class="v color-green">+${{L.cagr_opt}}%</span></div>
  <div class="perf-item"><span class="k">Max Drawdown</span><span class="v color-red">${{L.mdd_opt}}%</span></div>
  <div class="perf-item"><span class="k">Total Trades</span><span class="v">${{L.trades_opt}}</span></div>
`;

document.getElementById('perf-base').innerHTML = `
  <div class="perf-item"><span class="k">CAGR</span><span class="v">+${{L.cagr_base}}%</span></div>
  <div class="perf-item"><span class="k">Max Drawdown</span><span class="v color-red">${{L.mdd_base}}%</span></div>
`;

document.getElementById('perf-bh').innerHTML = `
  <div class="perf-item"><span class="k">CAGR</span><span class="v" style="color:#A6B0C3">+${{L.cagr_bh}}%</span></div>
  <div class="perf-item"><span class="k">Max Drawdown</span><span class="v color-red">${{L.mdd_bh}}%</span></div>
`;

const plotLayout = {{
  paper_bgcolor:'#FFFFFF', plot_bgcolor:'#FFFFFF',
  font:{{ family:'Roboto', color:'#6B7280', size:11 }},
  margin:{{ l:40, r:40, t:20, b:40 }},
  xaxis:{{ gridcolor:'#F0F0F0', linecolor:'#EBEBEB', tickfont:{{color:'#A6B0C3'}} }},
  yaxis:{{ gridcolor:'#F0F0F0', linecolor:'#EBEBEB', tickfont:{{color:'#A6B0C3'}} }},
  hovermode:'x unified', legend:{{ bgcolor:'#FFFFFF', bordercolor:'#EBEBEB', font:{{ size:12, color:'#111827' }} }},
}};
const cfg = {{ responsive:true, displayModeBar:false }};
function unpack(arr) {{ return {{ x: arr.map(d=>d[0]), y: arr.map(d=>d[1]) }}; }}

const eqOpt = unpack(D.eq_opt);
const eqBase = unpack(D.eq_base);
const eqBh = unpack(D.eq_bh);
const levData = unpack(D.lev_opt);

Plotly.newPlot('chart_equity', [
  {{ ...eqBh, name:'TQQQ Buy & Hold', type:'scatter', mode:'lines', line:{{ color:'#EBEBEB', width:1.5 }} }},
  {{ ...eqBase, name:'Base TQQQ+SEP', type:'scatter', mode:'lines', line:{{ color:'#A6B0C3', width:1.5 }} }},
  {{ ...eqOpt, name:'Protected (Current)', type:'scatter', mode:'lines', line:{{ color:'#0055FF', width:2 }} }},
  {{ ...levData, name:'Leverage', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{{ color:'#0055FF', width:1, shape:'hv', dash:'dot' }}, yaxis:'y2' }},
], {{ ...plotLayout, 
  yaxis:{{ ...plotLayout.yaxis, type:'log' }},
  yaxis2:{{ overlaying:'y', side:'right', showgrid:false, range:[0, 3.5], tickvals:[0,1,2,3], tickfont:{{color:'#A6B0C3'}} }},
  legend: {{ orientation: 'h', y: 1.05 }}
}}, cfg);

const zData = unpack(D.z_score);
Plotly.newPlot('chart_z', [
  {{ ...zData, name:'-(HYG/IEF) Z-Score', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(255, 51, 58, 0.05)', line:{{ color:'#FF333A', width:1.5 }} }}
], {{ ...plotLayout, margin:{{ l:40, r:20, t:20, b:40 }},
  shapes:[
    {{ type:'line', xref:'paper', x0:0, x1:1, y0:1.2, y1:1.2, line:{{ color:'#FF333A', width:1.5, dash:'dash' }} }},
    {{ type:'line', xref:'paper', x0:0, x1:1, y0:0.2, y1:0.2, line:{{ color:'#00C805', width:1.5, dash:'dash' }} }}
  ],
  yaxis:{{ ...plotLayout.yaxis, title:'Stress Level' }}
}}, cfg);

const volZData = unpack(D.vol_z);
Plotly.newPlot('chart_vol', [
  {{ ...volZData, name:'Vol Z-Score', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{{ color:'#0055FF', width:1.5 }} }}
], {{ ...plotLayout, margin:{{ l:40, r:20, t:20, b:40 }},
  shapes:[
    {{ type:'line', xref:'paper', x0:0, x1:1, y0:1.0, y1:1.0, line:{{ color:'#FF333A', width:1.5, dash:'dash' }} }},
    {{ type:'line', xref:'paper', x0:0, x1:1, y0:-0.5, y1:-0.5, line:{{ color:'#00C805', width:1.5, dash:'dash' }} }}
  ],
  yaxis:{{ ...plotLayout.yaxis, title:'Vol Z-Score' }}
}}, cfg);

const sepT = D.sep_table || [];
const tbl = document.getElementById('sep-table');
if (sepT.length > 0) {{
  let h = `<thead><tr><th>Date</th><th>Core PCE</th><th>Prev PCE</th><th>Fed Funds</th><th>Prev Rate</th><th>Signal</th></tr></thead><tbody>`;
  sepT.forEach(r => {{
    const isExit = r.signal === 'EXIT';
    const isEnter = r.signal === 'ENTER';
    const sigHtml = isExit ? '<span class="sig-exit">EXIT (0x)</span>' : (isEnter ? '<span class="sig-enter">ENTER (3x)</span>' : '—');
    
    const rate = r.rate !== null ? r.rate.toFixed(1) + '%' : '—';
    const prate = r.prev_rate !== null ? r.prev_rate.toFixed(1) + '%' : '—';
    const pce = r.pce !== null ? r.pce.toFixed(1) + '%' : '—';
    const ppce = r.prev_pce !== null ? r.prev_pce.toFixed(1) + '%' : '—';
    
    h += `<tr>
      <td style="font-weight:700;">${{r.date}}</td>
      <td>${{pce}}</td><td style="color:#A6B0C3;">${{ppce}}</td>
      <td>${{rate}}</td><td style="color:#A6B0C3;">${{prate}}</td>
      <td>${{sigHtml}}</td>
    </tr>`;
  }});
  h += '</tbody>';
  tbl.innerHTML = h;
}}
</script>
</body>
</html>
"""

out = os.path.join(PROJECT_DIR, 'tools', 'robustness_dashboard.html')
with open(out, 'w') as f:
    f.write(html)
print(f"\nDashboard successfully saved to {out}")
