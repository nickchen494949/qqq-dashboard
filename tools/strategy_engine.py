"""
strategy_engine.py — Single source of truth for TQQQ strategy logic.
====================================================================
Both audit_backtest.py and build_dashboard.py import from here.
No strategy/signal/backtest logic should exist outside this file.

Contains:
  1. Sealed parameters (constants)
  2. Signal computation (Credit Z, Vol Z)
  3. SEP parsing + state machine
  4. Production backtest engine (NSL + Next-Open + Costs)
"""
import os, re
import numpy as np
import pandas as pd
import pypdf


def get_fred_api_key():
    """Load FRED API key from env var or .env file. Never hardcoded in source."""
    key = os.environ.get('FRED_API_KEY')
    if key:
        return key
    # Fallback: read from .env in project root
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('FRED_API_KEY='):
                    return line.split('=', 1)[1].strip()
    raise RuntimeError("FRED_API_KEY not found. Set env var or create .env file.")

# ============================================================================
# SEALED PARAMETERS (do not modify without full 29-test audit)
# ============================================================================
Z_TRIGGER     = 1.2
Z_RECOVER     = 0.2
VZ_TRIGGER    = 1.0
VZ_RECOVER    = -0.5
VZ_LEV        = 2.0    # Vol danger → 2x leverage (66% TQQQ)
Z_WINDOW      = 252
EXPENSE_RATIO = 0.0086
TC_BPS        = 25

HARDCODED_FFR = {
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


# ============================================================================
# SIGNAL COMPUTATION
# ============================================================================
def compute_credit_z(hyg, ief, window=Z_WINDOW):
    """Inverted Z-score of HYG/IEF ratio. Higher = more stress."""
    ratio = hyg / ief
    return -(ratio - ratio.rolling(window).mean()) / ratio.rolling(window).std()


def compute_vol_z(daily_returns, window=Z_WINDOW):
    """Z-score of 20-day realized volatility (annualized)."""
    rvol_20 = daily_returns.rolling(20).std() * np.sqrt(252)
    vol_mean = rvol_20.rolling(window).mean()
    vol_std = rvol_20.rolling(window).std()
    return (rvol_20 - vol_mean) / vol_std


# ============================================================================
# SEP PARSING
# ============================================================================
def parse_sep_pdfs(sep_dir):
    """Parse all FOMC SEP PDFs. Returns list of dicts with date, pce, rate, etc.
    Raises RuntimeError on parse failure (no silent skips)."""
    sep_pdfs = sorted([f for f in os.listdir(sep_dir) if f.endswith('.pdf')])
    sep_raw = []
    for fn in sep_pdfs:
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', fn)
        if not m:
            continue
        meeting_year = int(m.group(1))
        meeting_month = int(m.group(2))
        try:
            reader = pypdf.PdfReader(os.path.join(sep_dir, fn))
            text = ''.join(pg.extract_text() + '\n' for pg in reader.pages[:3])
        except Exception as e:
            raise RuntimeError(f"Failed to parse SEP PDF {fn}: {e}")

        cp_all, fr_all = [], []
        lines = text.split('\n')
        for li, line in enumerate(lines):
            if not cp_all and re.search(r'Core\s*PCE\s*in[f\uFB02]', line, re.IGNORECASE) and \
               not re.search(r'projection|september|june|march|december|january|november', line, re.IGNORECASE):
                cp_all = [float(x) for x in re.findall(r'(\d+\.\d+)', line)]
            if not fr_all and re.search(r'Federal\s*funds\s*rate', line, re.IGNORECASE) and \
               not re.search(r'projection|september|june|march|december|january|november', line, re.IGNORECASE):
                fr_all = [float(x) for x in re.findall(r'(\d+\.\d+)', line)]
                if not fr_all:
                    for offset in range(1, 4):
                        if li + offset < len(lines):
                            nxt = lines[li + offset].strip()
                            if re.search(r'projection', nxt, re.IGNORECASE):
                                continue
                            fr_all = [float(x) for x in re.findall(r'(\d+\.\d+)', nxt)]
                            if fr_all:
                                break

        pce_by_year = {meeting_year + j: v for j, v in enumerate(cp_all[:4])}
        rate_by_year = {meeting_year + j: v for j, v in enumerate(fr_all[:4])}
        target_year = meeting_year if meeting_month < 9 else meeting_year + 1

        sep_raw.append({
            'date': f'{m.group(1)}-{m.group(2)}-{m.group(3)}',
            'meeting_year': meeting_year,
            'meeting_month': meeting_month,
            'target_year': target_year,
            'pce': pce_by_year.get(target_year),
            'rate': rate_by_year.get(target_year),
            'pce_by_year': pce_by_year,
            'rate_by_year': rate_by_year,
            'source': 'parsed',
        })

    # Apply hardcoded rates for early/broken PDFs
    for row in sep_raw:
        ty = row['target_year']
        key = (row['date'], ty)
        if row['rate'] is None and key in HARDCODED_FFR:
            row['rate'] = HARDCODED_FFR[key]
            row['rate_by_year'][ty] = HARDCODED_FFR[key]
            row['source'] = 'hardcoded'

    return sep_raw


def build_sep_signals(sep_raw):
    """Generate ENTER/EXIT signals from parsed SEP data.
    Uses same-target-year comparison logic."""
    sep_signals = []
    sep_in = True
    for i in range(1, len(sep_raw)):
        c, p = sep_raw[i], sep_raw[i - 1]
        ty = c['target_year']
        c_pce = c['pce_by_year'].get(ty)
        c_rate = c['rate_by_year'].get(ty)
        p_pce = p['pce_by_year'].get(ty)
        p_rate = p['rate_by_year'].get(ty)
        if c_pce is None:
            continue
        has_both = all(pd.notna(x) for x in [c_pce, c_rate, p_pce, p_rate])
        rate_up = c_rate > p_rate if has_both else False
        pce_above2 = c_pce > 2.0
        pce_up = c_pce > p_pce if has_both else False
        is_exit = rate_up and pce_above2 and pce_up if has_both else False
        reenter = (c_rate <= p_rate) if has_both else False
        same_ty = (ty == p['target_year'])

        signal = ''
        if sep_in and is_exit:
            signal = 'EXIT'
            sep_in = False
        elif not sep_in and reenter:
            signal = 'ENTER'
            sep_in = True

        sep_signals.append({
            'date': c['date'], 'target_year': ty, 'same_ty': same_ty,
            'pce': c_pce, 'prev_pce': p_pce,
            'rate': c_rate, 'prev_rate': p_rate,
            'signal': signal,
        })
    return sep_signals


def build_sep_state(sep_signals, idx):
    """Build daily SEP state series (1=IN, 0=OUT) from signal list.
    Maps signal dates to next trading day."""
    sep_signal_dates = {}
    for r in sep_signals:
        if not r['signal']:
            continue
        raw_date = pd.Timestamp(r['date'])
        candidates = idx[idx >= raw_date]
        if len(candidates) == 0:
            continue
        mapped = candidates[0]
        sep_signal_dates[mapped] = r['signal']

    sep_state = pd.Series(1, index=idx)
    s = 1
    for d in idx:
        if d in sep_signal_dates:
            s = 1 if sep_signal_dates[d] == 'ENTER' else 0
        sep_state[d] = s
    return sep_state, sep_signal_dates


# ============================================================================
# BACKTEST ENGINE (production-grade)
# ============================================================================
def run_backtest(idx, dr_qqq, dr_qqq_gap, dr_qqq_intra, effr,
                 z_series, vol_z, sep_state,
                 use_sep=True, use_overlay=True,
                 z_trigger=Z_TRIGGER, z_recover=Z_RECOVER,
                 vz_trigger=VZ_TRIGGER, vz_recover=VZ_RECOVER,
                 vz_lev=VZ_LEV, tc_bps=TC_BPS):
    """
    Full production backtest with:
    - T+1 pending execution (next-open)
    - Gap/intra split on switch days
    - NSL (Never Sell in Loss)
    - Borrowing costs, expense ratios, transaction costs

    Returns dict with: equity, leverage, cagr, mdd, sharpe, trades, trade_log, etc.
    """
    eq = 1.0; lev = 3.0; prev_lev = 3.0
    pending = None; eql = []; levs = []
    in_trade = False; trade_entry_eq = 1.0
    in_danger = False; vol_danger = False; trades = 0
    trade_log = []; danger_log = []; vol_danger_log = []
    switch_today = False

    for i in range(len(idx)):
        d = idx[i]
        si = sep_state.loc[d] if use_sep else 1

        # Apply pending (1-day delay)
        switch_today = False
        prev_lev_for_gap = lev
        if pending is not None:
            if pending != lev:
                trade_log.append({
                    'signal_date': idx[i - 1].strftime('%Y-%m-%d') if i > 0 else 'N/A',
                    'exec_date': d.strftime('%Y-%m-%d'),
                    'from_lev': lev, 'to_lev': pending,
                    'equity': round(eq, 4),
                    'reason': 'SEP' if pending == 0 or (lev == 0 and pending > 0) else 'TP/Vol',
                    'z': round(float(z_series.loc[d]), 2) if d in z_series.index else None,
                })
                switch_today = True
            lev = pending; pending = None

        is_profitable = (eq > trade_entry_eq) if in_trade else False
        z = z_series.loc[d] if d in z_series.index else np.nan

        tgt = 3
        if si == 0:
            tgt = 0; in_danger = False; vol_danger = False
        else:
            if use_overlay:
                if not np.isnan(z):
                    if not in_danger and z > z_trigger:
                        in_danger = True
                    elif in_danger and z < z_recover:
                        in_danger = False

                vz = vol_z.iloc[i] if i < len(vol_z) else np.nan
                if not np.isnan(vz):
                    if not vol_danger and vz > vz_trigger:
                        vol_danger = True
                    elif vol_danger and vz < vz_recover:
                        vol_danger = False

                if in_danger:
                    tgt = 1 if is_profitable else 3  # NSL for Credit: keep full if in loss
                elif vol_danger:
                    if is_profitable:
                        tgt = vz_lev
                    else:
                        tgt = lev  # NSL for Vol
                else:
                    tgt = 3
            else:
                tgt = 3

        if tgt != lev:
            pending = tgt
        if lev > 0 and not in_trade:
            in_trade = True; trade_entry_eq = eq
        elif lev == 0 and in_trade:
            in_trade = False
        if lev != prev_lev:
            trades += 1

        if i > 0:
            r_total = dr_qqq.iloc[i]
            if np.isnan(r_total):
                r_total = 0.0

            # On switch day: split into gap (old lev) + intra (new lev)
            if switch_today and dr_qqq_gap is not None and dr_qqq_intra is not None:
                rg = dr_qqq_gap.iloc[i]
                ri = dr_qqq_intra.iloc[i]
                if np.isnan(rg):
                    rg = 0.0
                if np.isnan(ri):
                    ri = 0.0
                r_applied = (1 + prev_lev_for_gap * rg) * (1 + lev * ri) - 1
            else:
                r_applied = lev * r_total

            borrow = max(0, lev - 1) * effr.iloc[i] if lev > 1 else 0
            fee = EXPENSE_RATIO / 252 * min(lev / 3, 1) if lev > 1 else 0
            cy = effr.iloc[i] if lev == 0 else 0
            tc = abs(lev - prev_lev) * (tc_bps / 10000)
            eq *= (1 + r_applied - borrow - fee + cy - tc)
            eq = max(eq, 0.001)

        prev_lev = lev
        eql.append(eq)
        levs.append(lev)
        danger_log.append(in_danger)
        vol_danger_log.append(vol_danger)

    es = pd.Series(eql, index=idx)
    ny = len(es) / 252
    cagr = es.iloc[-1] ** (1 / ny) - 1
    mdd = ((es / es.expanding().max()) - 1).min()
    daily_ret = es.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0

    return {
        'equity': es, 'leverage': levs,
        'danger': danger_log, 'vol_danger': vol_danger_log,
        'cagr': cagr, 'mdd': mdd, 'sharpe': sharpe, 'trades': trades,
        'trade_log': trade_log,
    }
