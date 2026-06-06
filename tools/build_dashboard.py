#!/usr/bin/env python3
"""
QQQ 庄家策略 Dashboard Generator (Webull Light Theme)
=====================================
Strategy: SEP (Primary) + -(HYG/IEF) Credit Stress TP (Secondary)
"""
import sys, os, json, re
import pypdf
from strategy_engine import (
    compute_credit_z, compute_vol_z,
    parse_sep_pdfs, build_sep_signals, build_sep_state,
    run_backtest, get_fred_api_key,
)
import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred
import warnings
warnings.filterwarnings('ignore')

FRED_API_KEY = get_fred_api_key()
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, 'market_data')
os.makedirs(DATA_DIR, exist_ok=True)

import time as _time

def load_or_fetch_fred(series_id, retries=2):
    path = os.path.join(DATA_DIR, f'fred_{series_id}.csv')
    cached = None
    if os.path.exists(path):
        cached = pd.read_csv(path, index_col=0, parse_dates=True).squeeze()
        cached = cached[~cached.index.duplicated(keep='last')]
    
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
                    print(f"  ⚠️  FRED fetch failed, using cache ({len(cached)} rows)")
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

z_series = compute_credit_z(hyg_d, ief_d)
vol_z = compute_vol_z(dr)

SEP_DIR = os.path.join(PROJECT_DIR, 'fomc_sep')
sep_table_data = []
if os.path.isdir(SEP_DIR):
    sep_raw = parse_sep_pdfs(SEP_DIR)
    sep_table_data = build_sep_signals(sep_raw)
sep_state, _ = build_sep_state(sep_table_data, idx)

# Compute gap/intra returns for next-open execution (matches audit_backtest.py)
qqq_open_raw = yf.download('QQQ', start='2005-01-01', progress=False, auto_adjust=False)
_open_raw = qqq_open_raw['Open']
_close_raw = qqq_open_raw['Close']
_adj_close = qqq_open_raw['Adj Close'] if 'Adj Close' in qqq_open_raw.columns else _close_raw
if isinstance(_close_raw, pd.DataFrame): _close_raw = _close_raw.iloc[:, 0]
if isinstance(_adj_close, pd.DataFrame): _adj_close = _adj_close.iloc[:, 0]
if isinstance(_open_raw, pd.DataFrame): _open_raw = _open_raw.iloc[:, 0]
_adj_factor = _adj_close / _close_raw
qqq_adj_open = (_open_raw * _adj_factor).reindex(idx).ffill()
dr_qqq_gap = (qqq_adj_open / qqq_d.shift(1) - 1).fillna(0)
dr_qqq_intra = (qqq_d / qqq_adj_open - 1).fillna(0)

res_base = run_backtest(idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, ef,
                        z_series, vol_z, sep_state, use_overlay=False)
es_base = res_base['equity']; lev_base = res_base['leverage']
cagr_base = res_base['cagr']; mdd_base = res_base['mdd']; tr_base = res_base['trades']

res_opt = run_backtest(idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, ef,
                       z_series, vol_z, sep_state, use_overlay=True)
es_opt = res_opt['equity']; lev_opt = res_opt['leverage']
cagr_opt = res_opt['cagr']; mdd_opt = res_opt['mdd']; tr_opt = res_opt['trades']

# Buy and Hold TQQQ
bh_eq = tqqq_d / tqqq_d.iloc[0]
ny = len(bh_eq)/252
cagr_bh = bh_eq.iloc[-1]**(1/ny) - 1
mdd_bh = ((bh_eq / bh_eq.expanding().max()) - 1).min()

def sw_weekly(series):
    d = series.resample('W').last().dropna()
    return list(zip([x.strftime('%Y-%m-%d') for x in d.index], [round(float(v), 4) for v in d.values]))

def sw_daily(series):
    d = series.dropna()
    return list(zip([x.strftime('%Y-%m-%d') for x in d.index], [round(float(v), 4) for v in d.values]))

cur_sep_state = 'IN' if sep_state.iloc[-1] == 1 else 'OUT'
cur_lev = lev_opt[-1]
cur_z = round(float(z_series.iloc[-1]), 2)
cur_vol_z = round(float(vol_z.dropna().iloc[-1]), 2) if len(vol_z.dropna()) > 0 else 0
cur_price = round(float(tqqq.dropna().iloc[-1]), 2)

# Portfolio: TQQQ + USD/MYR with daily % change
HOLDINGS = {'nick': 6326, 'gf': 395}

# TQQQ daily % change (last trading day vs previous)
tqqq_df = yf.download('TQQQ', period='2y', progress=False, auto_adjust=False)
tqqq_cl = tqqq_df['Close'] if 'Close' in tqqq_df.columns else tqqq_df['Adj Close']
if isinstance(tqqq_cl, pd.DataFrame): tqqq_cl = tqqq_cl.iloc[:, 0]

# Live prices
tqqq_info = yf.Ticker('TQQQ').fast_info
nq_info = yf.Ticker('NQ=F').fast_info
myr_info = yf.Ticker('MYR=X').fast_info

try: tqqq_mkt = tqqq_info['lastPrice']
except: tqqq_mkt = float(tqqq_cl.iloc[-1])

# Use the LAST regular-session close from historical data, NOT fast_info previousClose
# (previousClose includes post-market and is unreliable as a base)
tqqq_regular_close = float(tqqq_cl.iloc[-1])

try:
    nq_hist = yf.download('NQ=F', period='5d', progress=False, auto_adjust=False)
    nq_cl = nq_hist['Close']
    if isinstance(nq_cl, pd.DataFrame): nq_cl = nq_cl.iloc[:, 0]
    # Real-time NQ price from fast_info
    nq_now = float(nq_info['lastPrice'])
    # Baseline = same-day NQ close (matches TQQQ close day)
    # This avoids double-counting: TQQQ close already reflects intraday NQ move
    nq_baseline = float(nq_cl.iloc[-1])
    nq_pct = (nq_now / nq_baseline) - 1
    tqqq_sim = tqqq_regular_close * (1 + 3 * nq_pct)
except:
    tqqq_sim = tqqq_mkt

try:
    usd_myr = myr_info['lastPrice']
except:
    usd_myr = 4.20

# MYR historical
try:
    myr_df = yf.download('MYR=X', period='2y', progress=False, auto_adjust=False)
    myr_close = myr_df['Close'] if 'Close' in myr_df.columns else myr_df['Adj Close']
    if isinstance(myr_close, pd.DataFrame): myr_close = myr_close.iloc[:, 0]
except:
    myr_close = pd.Series([usd_myr])

# Multi-period portfolio changes
_periods = {'1D': 1, '1W': 5, '1M': 21, '1Q': 63, '1Y': 252}
_tqqq_series = tqqq_cl.dropna()
_myr_series = myr_close.dropna()

def calc_portfolio(tqqq_price, myr_price):
    nick_usd = HOLDINGS['nick'] * tqqq_price
    nick_myr = nick_usd * myr_price
    gf_usd = HOLDINGS['gf'] * tqqq_price
    gf_myr = gf_usd * myr_price
    total_myr = nick_myr + gf_myr

    changes = {}
    for label, days in _periods.items():
        t_prev = float(_tqqq_series.iloc[-1-days]) if len(_tqqq_series) > days else float(_tqqq_series.iloc[0])
        t_pct = round(((tqqq_price / t_prev) - 1) * 100, 2) if t_prev > 0 else 0
        m_prev = float(_myr_series.iloc[-1-days]) if len(_myr_series) > days else float(_myr_series.iloc[0])
        m_pct = round(((myr_price / m_prev) - 1) * 100, 2) if m_prev > 0 else 0
        nick_prev = HOLDINGS['nick'] * t_prev * m_prev
        gf_prev = HOLDINGS['gf'] * t_prev * m_prev
        total_prev = nick_prev + gf_prev
        changes[label] = {
            'tqqq_pct': t_pct,
            'myr_pct': m_pct,
            'nick_pct': round(((nick_myr / nick_prev) - 1) * 100, 2) if nick_prev > 0 else 0,
            'nick_chg': round(nick_myr - nick_prev, 0),
            'gf_pct': round(((gf_myr / gf_prev) - 1) * 100, 2) if gf_prev > 0 else 0,
            'gf_chg': round(gf_myr - gf_prev, 0),
            'total_pct': round(((total_myr / total_prev) - 1) * 100, 2) if total_prev > 0 else 0,
            'total_chg': round(total_myr - total_prev, 0),
        }
    return {
        'nick_units': HOLDINGS['nick'],
        'gf_units': HOLDINGS['gf'],
        'tqqq': round(tqqq_price, 2),
        'usd_myr': round(myr_price, 4),
        'nick_usd': round(nick_usd, 2),
        'nick_myr': round(nick_myr, 2),
        'gf_usd': round(gf_usd, 2),
        'gf_myr': round(gf_myr, 2),
        'total_usd': round(nick_usd + gf_usd, 2),
        'total_myr': round(total_myr, 2),
        'changes': changes,
    }

portfolio_market = calc_portfolio(tqqq_mkt, usd_myr)
portfolio_sim = calc_portfolio(tqqq_sim, usd_myr)


data_json = json.dumps({
    'dates': [d.strftime('%Y-%m-%d') for d in idx],
    'eq_bh_w': sw_weekly(bh_eq), 'eq_bh_d': sw_daily(bh_eq),
    'eq_base_w': sw_weekly(es_base), 'eq_base_d': sw_daily(es_base),
    'eq_opt_w': sw_weekly(es_opt), 'eq_opt_d': sw_daily(es_opt),
    'z_score_w': sw_weekly(z_series), 'z_score_d': sw_daily(z_series),
    'vol_z_w': sw_weekly(vol_z.dropna()), 'vol_z_d': sw_daily(vol_z.dropna()),
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
    'portfolio_market': portfolio_market, 'portfolio_sim': portfolio_sim,
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
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
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
  <div class="menu"><div class="active">Overview</div></div>
</div>

<div class="container">
  
  <div class="cards" id="cards"></div>

  <div class="panels">
    <div class="panel">
      <div class="panel-header" style="display:flex; justify-content:space-between; align-items:center;">
        <div>Equity Growth & Target Leverage</div>
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="background:#F0F0F0; padding:2px; border-radius:6px; display:flex; gap:2px;">
      <button id="btn-eq-d" onclick="setMode('eq', 'daily')" style="padding:4px 12px; border:none; background:#FFFFFF; color:#111827; border-radius:4px; cursor:pointer; font-size:11px; font-weight:600; box-shadow:0 1px 2px rgba(0,0,0,0.05);">Daily</button>
      <button id="btn-eq-w" onclick="setMode('eq', 'weekly')" style="padding:4px 12px; border:none; background:transparent; color:#6B7280; border-radius:4px; cursor:pointer; font-size:11px; font-weight:500;">Weekly</button>
    </div>
          <div class="note" style="font-weight:400; font-size:12px;">Log Scale • Since 2012</div>
        </div>
      </div>
      <div class="panel-body" style="padding:0;">
        <div id="chart_equity" style="width:100%;height:400px;"></div>
      </div>
    </div>
    
    <div class="panel">
      <div class="panel-header" style="display:flex; justify-content:space-between; align-items:center;">
      <div>Historical Performance</div>
      <div class="note" style="font-size:12px; font-weight:400; color:#A6B0C3;">Data: {source_dates['tqqq']}</div>
    </div>
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
      <div class="note">TP &gt; 1.2 | Re-enter &lt; 0.2 &nbsp;|&nbsp; Data: {source_dates['hyg']}</div>
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
      <div class="note">TP (66% TQQQ) &gt; 1.0 | Re-enter (100%) &lt; -0.5 &nbsp;|&nbsp; Data: {source_dates['qqq']}</div>
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

// SEP countdown
const SEP_DATES = ['2026-06-17','2026-09-16','2026-12-09','2027-03-17','2027-06-16','2027-09-15','2027-12-08'];
const today = new Date();
let nextSep = null;
let sepDays = 0;
for (const d of SEP_DATES) {{
  const dt = new Date(d + 'T18:00:00Z');
  const diff = Math.ceil((dt - today) / 86400000);
  if (diff >= 0) {{ nextSep = d; sepDays = diff; break; }}
}}
const sepLabel = nextSep ? `${{sepDays}}d → ${{nextSep}}` : 'TBD';
const sepUrgency = sepDays <= 7 ? '#ef4444' : (sepDays <= 30 ? '#f59e0b' : '#22c55e');

const cardsEl = document.getElementById('cards');

const zColor = L.z_score > 1.2 ? 'color-red' : (L.z_score < 0.2 ? 'color-green' : 'color-neutral');
const zText = L.z_score > 1.2 ? 'RISK OFF (TP 1x)' : (L.z_score < 0.2 ? 'SAFE ZONE' : 'WATCH (HYSTERESIS)');

const volColor = L.vol_z > 1.0 ? 'color-red' : (L.vol_z < -0.5 ? 'color-green' : 'color-neutral');
const volText = L.vol_z > 1.0 ? 'VOL SPIKE → 66% TQQQ' : (L.vol_z < -0.5 ? 'SAFE → 100% TQQQ' : 'WATCH (HYSTERESIS)');

const levColor = L.leverage === '3x' ? 'color-green' : (L.leverage === '1x' ? 'color-red' : 'color-neutral');
const sepColor = L.sep_state === 'IN' ? 'color-green' : 'color-red';
const P_init = D.portfolio_market;
const fmtMYR = (v) => 'RM ' + v.toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
const fmtUSD = (v) => '$' + v.toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
const fmtPct = (v) => {{
  const sign = v >= 0 ? '+' : '';
  return sign + v.toFixed(2) + '%';
}};
const pctStyle = (v) => v >= 0 ? 'color:#22c55e' : 'color:#ef4444';

const _pf = (v) => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
const _ps = (v) => v >= 0 ? 'color:#22c55e' : 'color:#ef4444';
const _vc = (v) => (v >= 0 ? '+RM ' : '-RM ') + Math.abs(v).toLocaleString('en-US', {{minimumFractionDigits:0, maximumFractionDigits:0}});
let curPeriod = '1D';
let pfMode = 'market';

function setPFMode(mode) {{
  pfMode = mode;
  const bm = document.getElementById('btn-pf-mkt');
  const bs = document.getElementById('btn-pf-sim');
  if (mode === 'market') {{
    bm.style.background = '#a5b4fc'; bm.style.color = '#111827';
    bs.style.background = 'transparent'; bs.style.color = '#818cf8';
  }} else {{
    bs.style.background = '#a5b4fc'; bs.style.color = '#111827';
    bm.style.background = 'transparent'; bm.style.color = '#818cf8';
  }}
  renderPF(curPeriod);
}}

function renderPF(p) {{
  curPeriod = p;
  const P = pfMode === 'market' ? D.portfolio_market : D.portfolio_sim;
  const c = P.changes[p];
  
  // Update Big Numbers
  document.getElementById('pf-total').textContent = fmtMYR(P.total_myr);
  document.getElementById('nick-myr').textContent = fmtMYR(P.nick_myr);
  document.getElementById('nick-usd').textContent = fmtUSD(P.nick_usd);
  document.getElementById('gf-myr').textContent = fmtMYR(P.gf_myr);
  document.getElementById('gf-usd').textContent = fmtUSD(P.gf_usd);
  document.getElementById('pf-tqqq-price').textContent = P.tqqq.toFixed(2);
  
  document.querySelectorAll('.pf-tab').forEach(t => t.style.color = t.dataset.p === p ? '#a5b4fc' : '#475569');
  document.querySelectorAll('.pf-tab').forEach(t => t.style.borderBottom = t.dataset.p === p ? '2px solid #a5b4fc' : 'none');
  
  document.getElementById('nick-pct').textContent = _pf(c.nick_pct);
  document.getElementById('nick-pct').style.color = _ps(c.nick_pct) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  document.getElementById('nick-chg').textContent = _vc(c.nick_chg);
  document.getElementById('nick-chg').style.color = _ps(c.nick_chg) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  
  document.getElementById('gf-pct').textContent = _pf(c.gf_pct);
  document.getElementById('gf-pct').style.color = _ps(c.gf_pct) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  document.getElementById('gf-chg').textContent = _vc(c.gf_chg);
  document.getElementById('gf-chg').style.color = _ps(c.gf_chg) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  
  document.getElementById('pf-tqqq-pct').textContent = _pf(c.tqqq_pct);
  document.getElementById('pf-tqqq-pct').style.color = _ps(c.tqqq_pct) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  
  document.getElementById('pf-myr-pct').textContent = _pf(c.myr_pct);
  document.getElementById('pf-myr-pct').style.color = _ps(c.myr_pct) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  
  document.getElementById('pf-total-pct').textContent = _pf(c.total_pct);
  document.getElementById('pf-total-pct').style.color = _ps(c.total_pct) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
  document.getElementById('pf-total-chg').textContent = _vc(c.total_chg);
  document.getElementById('pf-total-chg').style.color = _ps(c.total_chg) === 'color:#22c55e' ? '#22c55e' : '#ef4444';
}}

cardsEl.innerHTML = `
  <div class="card" id="portfolio-card" style="grid-column: span 2; background:linear-gradient(135deg,#0a0a23 0%,#1a1a3e 100%); border:1px solid #2d2d5e;">
    <div class="header-row">
      <div style="display:flex; gap:12px; align-items:center;">
        <div class="label" style="color:#a5b4fc;">💰 Portfolio Value</div>
        <div style="background:rgba(0,0,0,0.3); padding:2px; border-radius:6px; display:flex; gap:2px;">
          <button id="btn-pf-mkt" onclick="setPFMode('market')" style="padding:2px 8px; border:none; background:#a5b4fc; color:#111827; border-radius:4px; cursor:pointer; font-size:10px; font-weight:700;">Market</button>
          <button id="btn-pf-sim" onclick="setPFMode('sim')" style="padding:2px 8px; border:none; background:transparent; color:#818cf8; border-radius:4px; cursor:pointer; font-size:10px; font-weight:600;">Simulated (NQ=F)</button>
        </div>
      </div>
      <div style="display:flex; gap:8px; align-items:center;">
        ${{['1D','1W','1M','1Q','1Y'].map(p => `<span class="pf-tab" data-p="${{p}}" onclick="renderPF('${{p}}')" style="cursor:pointer; font-size:11px; font-weight:600; padding:2px 6px; color:${{p==='1D'?'#a5b4fc':'#475569'}}; border-bottom:${{p==='1D'?'2px solid #a5b4fc':'none'}};">${{p}}</span>`).join('')}}
      </div>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:8px;">
      <div>
        <div style="color:#94a3b8; font-size:11px; margin-bottom:2px;">Nick (${{P_init.nick_units}} units)</div>
        <div style="display:flex; align-items:baseline; gap:8px;">
          <div id="nick-myr" style="color:#f1f5f9; font-weight:700; font-size:22px;">${{fmtMYR(P_init.nick_myr)}}</div>
          <div id="nick-pct" style="font-size:12px; font-weight:600;"></div>
        </div>
        <div style="display:flex; align-items:baseline; gap:8px;">
          <div id="nick-usd" style="color:#64748b; font-size:11px;">${{fmtUSD(P_init.nick_usd)}}</div>
          <div id="nick-chg" style="font-size:11px; font-weight:500;"></div>
        </div>
      </div>
      <div>
        <div style="color:#94a3b8; font-size:11px; margin-bottom:2px;">SY (${{P_init.gf_units}} units)</div>
        <div style="display:flex; align-items:baseline; gap:8px;">
          <div id="gf-myr" style="color:#f1f5f9; font-weight:700; font-size:22px;">${{fmtMYR(P_init.gf_myr)}}</div>
          <div id="gf-pct" style="font-size:12px; font-weight:600;"></div>
        </div>
        <div style="display:flex; align-items:baseline; gap:8px;">
          <div id="gf-usd" style="color:#64748b; font-size:11px;">${{fmtUSD(P_init.gf_usd)}}</div>
          <div id="gf-chg" style="font-size:11px; font-weight:500;"></div>
        </div>
      </div>
    </div>
    <div style="border-top:1px solid #2d2d5e; margin-top:10px; padding-top:8px; display:flex; justify-content:space-between; align-items:center;">
      <div style="color:#94a3b8; font-size:11px;">TQQQ $<span id="pf-tqqq-price">${{P_init.tqqq.toFixed(2)}}</span> <span id="pf-tqqq-pct" style="font-size:10px;"></span> · USD/MYR ${{P_init.usd_myr}} <span id="pf-myr-pct" style="font-size:10px;"></span></div>
      <div style="display:flex; align-items:baseline; gap:6px;">
        <div id="pf-total" style="color:#a5b4fc; font-weight:700; font-size:16px;">${{fmtMYR(P_init.total_myr)}}</div>
        <div id="pf-total-pct" style="font-size:11px; font-weight:600;"></div>
        <div id="pf-total-chg" style="font-size:10px; font-weight:500;"></div>
      </div>
    </div>
    <div id="pf-status" style="color:#475569; font-size:10px; margin-top:4px; text-align:right;">📊 Data: ${{D.generated_at}}</div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">Fed SEP Position</div><div class="more">Primary</div></div>
    <div class="value ${{sepColor}}">${{L.sep_state}}</div>
    <div class="sub">Macro Economic Engine<br><span style="font-size:10px; opacity:0.8">As of ${{L.date}}</span></div>
    <div style="margin-top:8px; padding-top:6px; border-top:1px solid rgba(0,0,0,0.08); display:flex; align-items:center; gap:6px;">
      <span style="font-size:14px;">🔔</span>
      <span style="font-size:11px; font-weight:600; color:#111827;">Next SEP: ${{sepLabel}}</span>
    </div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">-(HYG/IEF) Credit Stress</div></div>
    <div class="value ${{zColor}}">${{L.z_score.toFixed(2)}}</div>
    <div class="sub">${{zText}}<br><span style="font-size:10px; opacity:0.8">Data: ${{D.source_dates.hyg}}</span></div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">Volatility Z-Score</div></div>
    <div class="value ${{volColor}}">${{L.vol_z.toFixed(2)}}</div>
    <div class="sub">${{volText}}<br><span style="font-size:10px; opacity:0.8">Data: ${{D.source_dates.qqq}}</span></div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">Target Leverage</div><div class="more">Protected</div></div>
    <div class="value ${{levColor}}">${{L.leverage}}</div>
    <div class="sub">NSL Rules Active<br><span style="font-size:10px; opacity:0.8">Target for next open</span></div>
  </div>
  <div class="card">
    <div class="header-row"><div class="label">TQQQ Last Price</div><div class="more">Yahoo</div></div>
    <div class="value">$${{L.price.toFixed(2)}}</div>
    <div class="sub">Data: ${{D.source_dates.tqqq}}</div>
  </div>
`;

renderPF('1D');

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
  xaxis:{{ 
    gridcolor:'#F0F0F0', linecolor:'#EBEBEB', tickfont:{{color:'#A6B0C3'}}, hoverformat:'%Y-%m-%d',
    rangeselector: {{
      buttons: [
        {{count: 1, label: '1y', step: 'year', stepmode: 'backward'}},
        {{count: 2, label: '2y', step: 'year', stepmode: 'backward'}},
        {{count: 5, label: '5y', step: 'year', stepmode: 'backward'}},
        {{step: 'all', label: 'All'}}
      ],
      font: {{size: 11, color: '#6B7280'}},
      bgcolor: '#F9FAFB',
      activecolor: '#EBEBEB',
      bordercolor: '#EBEBEB',
      borderwidth: 1
    }}
  }},
  yaxis:{{ gridcolor:'#F0F0F0', linecolor:'#EBEBEB', tickfont:{{color:'#A6B0C3'}} }},
  hovermode:'x unified', legend:{{ bgcolor:'#FFFFFF', bordercolor:'#EBEBEB', font:{{ size:12, color:'#111827' }} }},
}};
const cfg = {{ responsive:true, displayModeBar:false }};
function unpack(arr) {{ return {{ x: arr.map(d=>d[0]), y: arr.map(d=>d[1]) }}; }}

function barColors(yArr) {{
  return yArr.map((v, i) => i === 0 ? '#A6B0C3' : (v > yArr[i-1] ? '#FF333A' : '#00C805'));
}}

const levData = unpack(D.lev_opt);
const modes = {{ eq: 'daily', z: 'daily', vol: 'daily' }};

function renderEq() {{
  const s = modes.eq === 'daily' ? '_d' : '_w';
  const eqOpt = unpack(D['eq_opt' + s]);
  const eqBase = unpack(D['eq_base' + s]);
  const eqBh = unpack(D['eq_bh' + s]);
  Plotly.react('chart_equity', [
    {{ ...eqBh, name:'TQQQ Buy & Hold', type:'scatter', mode:'lines', line:{{ color:'#EBEBEB', width:1.5 }} }},
    {{ ...eqBase, name:'Base TQQQ+SEP', type:'scatter', mode:'lines', line:{{ color:'#A6B0C3', width:1.5 }} }},
    {{ ...eqOpt, name:'Protected (Current)', type:'scatter', mode:'lines', line:{{ color:'#0055FF', width:2 }} }},
    {{ ...levData, name:'Leverage', type:'scatter', mode:'lines', fill:'tozeroy', fillcolor:'rgba(0, 85, 255, 0.05)', line:{{ color:'#0055FF', width:1, shape:'hv', dash:'dot' }}, yaxis:'y2' }},
  ], {{ ...plotLayout,
    yaxis:{{ ...plotLayout.yaxis, type:'log' }},
    yaxis2:{{ overlaying:'y', side:'right', showgrid:false, range:[0, 3.5], tickvals:[0,1,2,3], tickfont:{{color:'#A6B0C3'}} }},
    legend: {{ orientation: 'h', y: 1.05 }}
  }}, cfg);
}}

function renderZ() {{
  const s = modes.z === 'daily' ? '_d' : '_w';
  const zData = unpack(D['z_score' + s]);
  Plotly.react('chart_z', [
    {{ x: zData.x, y: zData.y, name:'-(HYG/IEF) Z-Score', type:'bar', marker:{{ color: barColors(zData.y) }} }}
  ], {{ ...plotLayout, margin:{{ l:40, r:20, t:20, b:40 }},
    shapes:[
      {{ type:'line', xref:'paper', x0:0, x1:1, y0:1.2, y1:1.2, line:{{ color:'#FF333A', width:1.5, dash:'dash' }} }},
      {{ type:'line', xref:'paper', x0:0, x1:1, y0:0.2, y1:0.2, line:{{ color:'#00C805', width:1.5, dash:'dash' }} }}
    ],
    yaxis:{{ ...plotLayout.yaxis, title:'Stress Level' }},
    bargap: 0
  }}, cfg);
}}

function renderVol() {{
  const s = modes.vol === 'daily' ? '_d' : '_w';
  const volZData = unpack(D['vol_z' + s]);
  Plotly.react('chart_vol', [
    {{ x: volZData.x, y: volZData.y, name:'Vol Z-Score', type:'bar', marker:{{ color: barColors(volZData.y) }} }}
  ], {{ ...plotLayout, margin:{{ l:40, r:20, t:20, b:40 }},
    shapes:[
      {{ type:'line', xref:'paper', x0:0, x1:1, y0:1.0, y1:1.0, line:{{ color:'#FF333A', width:1.5, dash:'dash' }} }},
      {{ type:'line', xref:'paper', x0:0, x1:1, y0:-0.5, y1:-0.5, line:{{ color:'#00C805', width:1.5, dash:'dash' }} }}
    ],
    yaxis:{{ ...plotLayout.yaxis, title:'Vol Z-Score' }},
    bargap: 0
  }}, cfg);
}}

function setMode(chart, mode) {{
  modes[chart] = mode;
  const bd = document.getElementById('btn-' + chart + '-d');
  const bw = document.getElementById('btn-' + chart + '-w');
  if (mode === 'daily') {{
    bd.style.background = '#FFFFFF'; bd.style.color = '#111827'; bd.style.fontWeight = '600'; bd.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
    bw.style.background = 'transparent'; bw.style.color = '#6B7280'; bw.style.fontWeight = '500'; bw.style.boxShadow = 'none';
  }} else {{
    bw.style.background = '#FFFFFF'; bw.style.color = '#111827'; bw.style.fontWeight = '600'; bw.style.boxShadow = '0 1px 2px rgba(0,0,0,0.05)';
    bd.style.background = 'transparent'; bd.style.color = '#6B7280'; bd.style.fontWeight = '500'; bd.style.boxShadow = 'none';
  }}
  if (chart === 'eq') renderEq();
  if (chart === 'z') renderZ();
  if (chart === 'vol') renderVol();
}}

renderEq();
renderZ();
renderVol();

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
