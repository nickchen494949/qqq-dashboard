import re

with open('tools/build_dashboard.py', 'r') as f:
    text = f.read()

# 1. Replace data fetching logic
data_fetching_old = """tqqq_df = yf.download('TQQQ', period='2y', progress=False, auto_adjust=False)
tqqq_cl = tqqq_df['Close'] if 'Close' in tqqq_df.columns else tqqq_df['Adj Close']
if isinstance(tqqq_cl, pd.DataFrame): tqqq_cl = tqqq_cl.iloc[:, 0]
tqqq_now = float(tqqq_cl.iloc[-1])
tqqq_prev = float(tqqq_cl.iloc[-2]) if len(tqqq_cl) >= 2 else tqqq_now
tqqq_pct = round(((tqqq_now / tqqq_prev) - 1) * 100, 2) if tqqq_prev > 0 else 0

# USD/MYR daily % change
try:
    myr_df = yf.download('MYR=X', period='2y', progress=False, auto_adjust=False)
    myr_close = myr_df['Close'] if 'Close' in myr_df.columns else myr_df['Adj Close']
    if isinstance(myr_close, pd.DataFrame): myr_close = myr_close.iloc[:, 0]
    usd_myr = round(float(myr_close.iloc[-1]), 4)
    myr_prev = float(myr_close.iloc[-2]) if len(myr_close) >= 2 else usd_myr
    myr_pct = round(((usd_myr / myr_prev) - 1) * 100, 2) if myr_prev > 0 else 0
except Exception:
    usd_myr = 4.20; myr_pct = 0; myr_prev = usd_myr

# Multi-period portfolio changes (1D, 1W, 1M, 1Q, 1Y)
import datetime as _dt
_periods = {'1D': 1, '1W': 5, '1M': 21, '1Q': 63, '1Y': 252}
_tqqq_series = tqqq_cl.dropna()
_myr_series = myr_close.dropna() if 'myr_close' in dir() else pd.Series([usd_myr])

nick_usd = HOLDINGS['nick'] * tqqq_now
nick_myr_now = nick_usd * usd_myr
gf_usd = HOLDINGS['gf'] * tqqq_now
gf_myr_now = gf_usd * usd_myr
total_myr_now = nick_myr_now + gf_myr_now

changes = {}
for label, days in _periods.items():
    # TQQQ lookback
    t_prev = float(_tqqq_series.iloc[-1-days]) if len(_tqqq_series) > days else float(_tqqq_series.iloc[0])
    t_pct = round(((tqqq_now / t_prev) - 1) * 100, 2) if t_prev > 0 else 0
    # MYR lookback
    m_prev = float(_myr_series.iloc[-1-days]) if len(_myr_series) > days else float(_myr_series.iloc[0])
    m_pct = round(((usd_myr / m_prev) - 1) * 100, 2) if m_prev > 0 else 0
    # Portfolio lookback
    nick_prev = HOLDINGS['nick'] * t_prev * m_prev
    gf_prev = HOLDINGS['gf'] * t_prev * m_prev
    total_prev = nick_prev + gf_prev
    changes[label] = {
        'tqqq_pct': t_pct,
        'tqqq_prev': round(t_prev, 2),
        'myr_pct': m_pct,
        'nick_pct': round(((nick_myr_now / nick_prev) - 1) * 100, 2) if nick_prev > 0 else 0,
        'nick_chg': round(nick_myr_now - nick_prev, 0),
        'gf_pct': round(((gf_myr_now / gf_prev) - 1) * 100, 2) if gf_prev > 0 else 0,
        'gf_chg': round(gf_myr_now - gf_prev, 0),
        'total_pct': round(((total_myr_now / total_prev) - 1) * 100, 2) if total_prev > 0 else 0,
        'total_chg': round(total_myr_now - total_prev, 0),
    }

portfolio = {
    'nick_units': HOLDINGS['nick'],
    'gf_units': HOLDINGS['gf'],
    'tqqq_close': cur_price,
    'tqqq_est': round(tqqq_now, 2),
    'usd_myr': usd_myr,
    'nick_usd': round(nick_usd, 2),
    'nick_myr': round(nick_myr_now, 2),
    'gf_usd': round(gf_usd, 2),
    'gf_myr': round(gf_myr_now, 2),
    'total_usd': round(nick_usd + gf_usd, 2),
    'total_myr': round(total_myr_now, 2),
    'changes': changes,
}"""

data_fetching_new = """tqqq_df = yf.download('TQQQ', period='2y', progress=False, auto_adjust=False)
tqqq_cl = tqqq_df['Close'] if 'Close' in tqqq_df.columns else tqqq_df['Adj Close']
if isinstance(tqqq_cl, pd.DataFrame): tqqq_cl = tqqq_cl.iloc[:, 0]

# Live prices
tqqq_info = yf.Ticker('TQQQ').fast_info
nq_info = yf.Ticker('NQ=F').fast_info
myr_info = yf.Ticker('MYR=X').fast_info

try: tqqq_mkt = tqqq_info['lastPrice']
except: tqqq_mkt = float(tqqq_cl.iloc[-1])
try: tqqq_prev_day = tqqq_info['previousClose']
except: tqqq_prev_day = float(tqqq_cl.iloc[-2]) if len(tqqq_cl) >= 2 else tqqq_mkt

try:
    nq_last = nq_info['lastPrice']
    nq_prev = nq_info['previousClose']
    nq_pct = (nq_last / nq_prev) - 1
    tqqq_sim = tqqq_prev_day * (1 + 3 * nq_pct)
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
        'tqqq': round(tqqq_price, 2),
        'usd_myr': round(myr_price, 4),
        'nick_myr': round(nick_myr, 2),
        'gf_myr': round(gf_myr, 2),
        'total_myr': round(total_myr, 2),
        'changes': changes,
    }

portfolio_market = calc_portfolio(tqqq_mkt, usd_myr)
portfolio_sim = calc_portfolio(tqqq_sim, usd_myr)
"""
if data_fetching_old in text:
    text = text.replace(data_fetching_old, data_fetching_new)
else:
    print("WARNING: data fetching old not found")

# 2. Inject portfolio_market and portfolio_sim into data_json
text = text.replace("'portfolio': portfolio,", "'portfolio_market': portfolio_market, 'portfolio_sim': portfolio_sim,")

# 3. Update HTML Portfolio Header with Toggle
pf_header_old = """<div class="header-row">
      <div class="label" style="color:#a5b4fc;">💰 Portfolio Value</div>
      <div style="display:flex; gap:8px; align-items:center;">
        ${['1D','1W','1M','1Q','1Y'].map(p => `<span class="pf-tab" data-p="${p}" onclick="renderPF('${p}')" style="cursor:pointer; font-size:11px; font-weight:600; padding:2px 6px; color:${p==='1D'?'#a5b4fc':'#475569'}; border-bottom:${p==='1D'?'2px solid #a5b4fc':'none'};">${p}</span>`).join('')}
      </div>
    </div>"""

pf_header_new = """<div class="header-row">
      <div style="display:flex; gap:12px; align-items:center;">
        <div class="label" style="color:#a5b4fc;">💰 Portfolio Value</div>
        <div style="background:rgba(0,0,0,0.3); padding:2px; border-radius:6px; display:flex; gap:2px;">
          <button id="btn-pf-mkt" onclick="setPFMode('market')" style="padding:2px 8px; border:none; background:#a5b4fc; color:#111827; border-radius:4px; cursor:pointer; font-size:10px; font-weight:700;">Market</button>
          <button id="btn-pf-sim" onclick="setPFMode('sim')" style="padding:2px 8px; border:none; background:transparent; color:#818cf8; border-radius:4px; cursor:pointer; font-size:10px; font-weight:600;">Simulated (NQ=F)</button>
        </div>
      </div>
      <div style="display:flex; gap:8px; align-items:center;">
        ${['1D','1W','1M','1Q','1Y'].map(p => `<span class="pf-tab" data-p="${p}" onclick="renderPF('${p}')" style="cursor:pointer; font-size:11px; font-weight:600; padding:2px 6px; color:${p==='1D'?'#a5b4fc':'#475569'}; border-bottom:${p==='1D'?'2px solid #a5b4fc':'none'};">${p}</span>`).join('')}
      </div>
    </div>"""
text = text.replace(pf_header_old, pf_header_new)

# 4. Update JS logic for rendering PF
js_renderpf_old = """const P = D.portfolio;
const fmtMYR = (v) => 'RM ' + v.toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
const fmtUSD = (v) => '$' + v.toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
const fmtPct = (v) => {
  const sign = v >= 0 ? '+' : '';
  return sign + v.toFixed(2) + '%';
};
const pctStyle = (v) => v >= 0 ? 'color:#22c55e' : 'color:#ef4444';

const C = P.changes;
const _pf = (v) => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
const _ps = (v) => v >= 0 ? 'color:#22c55e' : 'color:#ef4444';
const _vc = (v) => (v >= 0 ? '+RM ' : '-RM ') + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
let curPeriod = '1D';

function renderPF(p) {
  curPeriod = p;
  const c = C[p];
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
}"""

js_renderpf_new = """const fmtMYR = (v) => 'RM ' + v.toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
const _pf = (v) => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
const _ps = (v) => v >= 0 ? 'color:#22c55e' : 'color:#ef4444';
const _vc = (v) => (v >= 0 ? '+RM ' : '-RM ') + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits:0, maximumFractionDigits:0});
let curPeriod = '1D';
let pfMode = 'market';

function setPFMode(mode) {
  pfMode = mode;
  const bm = document.getElementById('btn-pf-mkt');
  const bs = document.getElementById('btn-pf-sim');
  if (mode === 'market') {
    bm.style.background = '#a5b4fc'; bm.style.color = '#111827';
    bs.style.background = 'transparent'; bs.style.color = '#818cf8';
  } else {
    bs.style.background = '#a5b4fc'; bs.style.color = '#111827';
    bm.style.background = 'transparent'; bm.style.color = '#818cf8';
  }
  renderPF(curPeriod);
}

function renderPF(p) {
  curPeriod = p;
  const P = pfMode === 'market' ? D.portfolio_market : D.portfolio_sim;
  const c = P.changes[p];
  
  // Update Big Numbers
  document.getElementById('total-myr').textContent = fmtMYR(P.total_myr);
  document.getElementById('nick-myr').textContent = fmtMYR(P.nick_myr);
  document.getElementById('gf-myr').textContent = fmtMYR(P.gf_myr);
  document.getElementById('pf-tqqq-price').textContent = '$' + P.tqqq;
  document.getElementById('pf-usd-myr').textContent = P.usd_myr;

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
}"""
text = text.replace(js_renderpf_old, js_renderpf_new)

# 5. Make sure the big numbers in HTML have IDs
big_numbers_old = """<div style="font-size:32px; font-weight:800; color:#fff;">${fmtMYR(P.total_myr)}</div>
        <div style="font-size:13px; color:#94a3b8; margin-top:2px;">
          TQQQ: <strong style="color:#e2e8f0;">$${P.tqqq_est}</strong> <span id="pf-tqqq-pct"></span> &nbsp;•&nbsp; 
          USD/MYR: <strong style="color:#e2e8f0;">${P.usd_myr}</strong> <span id="pf-myr-pct"></span>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:20px; font-weight:700; color:#22c55e;" id="pf-total-pct"></div>
        <div style="font-size:14px; color:#22c55e; font-weight:600;" id="pf-total-chg"></div>
      </div>
    </div>
    
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1px; background:#2d2d5e; margin-top:16px; border-top:1px solid #2d2d5e;">
      
      <div style="background:rgba(255,255,255,0.02); padding:12px;">
        <div style="font-size:12px; color:#94a3b8; font-weight:600;">Nick (${P.nick_units} units)</div>
        <div style="font-size:20px; font-weight:700; color:#fff; margin:4px 0;">${fmtMYR(P.nick_myr)}</div>
        <div style="display:flex; justify-content:space-between; font-size:13px;">
          <span id="nick-pct" style="font-weight:600;"></span>
          <span id="nick-chg"></span>
        </div>
      </div>

      <div style="background:rgba(255,255,255,0.02); padding:12px;">
        <div style="font-size:12px; color:#94a3b8; font-weight:600;">GF (${P.gf_units} units)</div>
        <div style="font-size:20px; font-weight:700; color:#fff; margin:4px 0;">${fmtMYR(P.gf_myr)}</div>"""

big_numbers_new = """<div style="font-size:32px; font-weight:800; color:#fff;" id="total-myr">--</div>
        <div style="font-size:13px; color:#94a3b8; margin-top:2px;">
          TQQQ: <strong style="color:#e2e8f0;" id="pf-tqqq-price">--</strong> <span id="pf-tqqq-pct"></span> &nbsp;•&nbsp; 
          USD/MYR: <strong style="color:#e2e8f0;" id="pf-usd-myr">--</strong> <span id="pf-myr-pct"></span>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:20px; font-weight:700; color:#22c55e;" id="pf-total-pct"></div>
        <div style="font-size:14px; color:#22c55e; font-weight:600;" id="pf-total-chg"></div>
      </div>
    </div>
    
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1px; background:#2d2d5e; margin-top:16px; border-top:1px solid #2d2d5e;">
      
      <div style="background:rgba(255,255,255,0.02); padding:12px;">
        <div style="font-size:12px; color:#94a3b8; font-weight:600;">Nick (${D.portfolio_market.nick_units} units)</div>
        <div style="font-size:20px; font-weight:700; color:#fff; margin:4px 0;" id="nick-myr">--</div>
        <div style="display:flex; justify-content:space-between; font-size:13px;">
          <span id="nick-pct" style="font-weight:600;"></span>
          <span id="nick-chg"></span>
        </div>
      </div>

      <div style="background:rgba(255,255,255,0.02); padding:12px;">
        <div style="font-size:12px; color:#94a3b8; font-weight:600;">GF (${D.portfolio_market.gf_units} units)</div>
        <div style="font-size:20px; font-weight:700; color:#fff; margin:4px 0;" id="gf-myr">--</div>"""
text = text.replace(big_numbers_old, big_numbers_new)

# Note: `renderPF('1D');` is called at the bottom of the script natively.

with open('tools/build_dashboard.py', 'w') as f:
    f.write(text)
