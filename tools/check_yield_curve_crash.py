"""
Yield Curve vs QQQ Crash Analysis
==================================
Tests whether yield curve inversion (10Y-2Y and 10Y-3M) can predict QQQ drawdowns.

Checks:
1. Every major QQQ drawdown (>15%) — was the curve inverted before?
2. Every yield curve inversion — did a crash follow? How long was the lead time?
3. Forward returns after inversion vs normal periods
4. Could this be a usable strategy signal?
"""
import os
import numpy as np
import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Load data ---
qqq = pd.read_csv(os.path.join(project_root, 'market_data/yahoo_QQQ.csv'), parse_dates=['Date'])
qqq = qqq.rename(columns={'Date': 'date'}).set_index('date').sort_index()

t10y2y = pd.read_csv(os.path.join(project_root, 'market_data/fred_T10Y2Y.csv'), parse_dates=['date'])
t10y2y = t10y2y.set_index('date').sort_index()

t10y3m = pd.read_csv(os.path.join(project_root, 'market_data/fred_T10Y3M.csv'), parse_dates=['date'])
t10y3m = t10y3m.set_index('date').sort_index()

# Merge
df = qqq[['QQQ']].join(t10y2y, how='inner').join(t10y3m, how='inner').dropna()
df['QQQ_ret'] = df['QQQ'].pct_change()

print(f"Data range: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")
print()

# ============================================================================
# PART 1: Identify all major QQQ drawdowns (peak-to-trough > 15%)
# ============================================================================
print("=" * 80)
print("PART 1: Major QQQ Drawdowns (>15%) — Was yield curve inverted before?")
print("=" * 80)

# Rolling peak and drawdown
df['peak'] = df['QQQ'].cummax()
df['dd'] = df['QQQ'] / df['peak'] - 1

# Find drawdown episodes
threshold = -0.15
in_dd = False
episodes = []
for i, (date, row) in enumerate(df.iterrows()):
    if not in_dd and row['dd'] < threshold:
        # Find peak date (start of drawdown)
        peak_date = df.loc[:date, 'QQQ'].idxmax()
        in_dd = True
        current_trough = row['dd']
        trough_date = date
    elif in_dd:
        if row['dd'] < current_trough:
            current_trough = row['dd']
            trough_date = date
        if row['dd'] > threshold * 0.3:  # recovered significantly
            peak_date_val = df.loc[peak_date, 'QQQ']
            trough_val = df.loc[trough_date, 'QQQ']
            episodes.append({
                'peak_date': peak_date,
                'trough_date': trough_date,
                'peak_price': peak_date_val,
                'trough_price': trough_val,
                'drawdown': current_trough,
            })
            in_dd = False

# Check if still in drawdown at end
if in_dd:
    episodes.append({
        'peak_date': peak_date,
        'trough_date': trough_date,
        'peak_price': df.loc[peak_date, 'QQQ'],
        'trough_price': df.loc[trough_date, 'QQQ'],
        'drawdown': current_trough,
    })

print(f"\nFound {len(episodes)} major drawdown episodes (>15%):\n")

for ep in episodes:
    pd_date = ep['peak_date']
    # Check if curve was inverted in 24 months before peak
    lookback_start = pd_date - pd.DateOffset(months=24)
    window = df.loc[lookback_start:pd_date]
    
    t2y_inverted_days = (window['T10Y2Y'] < 0).sum()
    t3m_inverted_days = (window['T10Y3M'] < 0).sum()
    t2y_min = window['T10Y2Y'].min()
    t3m_min = window['T10Y3M'].min()
    
    # First inversion date in the 24mo window
    t2y_inv_dates = window[window['T10Y2Y'] < 0].index
    t3m_inv_dates = window[window['T10Y3M'] < 0].index
    t2y_first = t2y_inv_dates[0] if len(t2y_inv_dates) > 0 else None
    t3m_first = t3m_inv_dates[0] if len(t3m_inv_dates) > 0 else None
    
    lead_2y = (pd_date - t2y_first).days if t2y_first else None
    lead_3m = (pd_date - t3m_first).days if t3m_first else None
    
    print(f"  📉 Peak: {pd_date.date()} → Trough: {ep['trough_date'].date()}  "
          f"Drawdown: {ep['drawdown']*100:.1f}%")
    print(f"     10Y-2Y: inverted {t2y_inverted_days}d in prior 24mo, min={t2y_min:.2f}  "
          f"{'✅ YES' if t2y_inverted_days > 0 else '❌ NO'}  "
          f"{'(lead: '+str(lead_2y)+'d)' if lead_2y else ''}")
    print(f"     10Y-3M: inverted {t3m_inverted_days}d in prior 24mo, min={t3m_min:.2f}  "
          f"{'✅ YES' if t3m_inverted_days > 0 else '❌ NO'}  "
          f"{'(lead: '+str(lead_3m)+'d)' if lead_3m else ''}")
    print()

# ============================================================================
# PART 2: Every inversion period — did a crash follow?
# ============================================================================
print("=" * 80)
print("PART 2: Yield Curve Inversion Periods — What happened after?")
print("=" * 80)

for label, col in [('10Y-2Y', 'T10Y2Y'), ('10Y-3M', 'T10Y3M')]:
    print(f"\n--- {label} ---")
    inverted = df[col] < 0
    
    # Find inversion episodes (contiguous blocks)
    inv_starts = []
    inv_ends = []
    was_inv = False
    for date, is_inv in inverted.items():
        if is_inv and not was_inv:
            inv_starts.append(date)
        elif not is_inv and was_inv:
            inv_ends.append(date)
        was_inv = is_inv
    if was_inv:
        inv_ends.append(df.index[-1])
    
    for start, end in zip(inv_starts, inv_ends):
        duration = (end - start).days
        if duration < 5:  # Skip very brief blips
            continue
        
        # Forward returns from END of inversion
        for horizon_label, horizon_days in [('3mo', 63), ('6mo', 126), ('12mo', 252), ('18mo', 378)]:
            future_date = end + pd.DateOffset(days=horizon_days)
            future = df.loc[end:future_date]
            if len(future) < 2:
                continue
            fwd_ret = future['QQQ'].iloc[-1] / future['QQQ'].iloc[0] - 1
            max_dd = (future['QQQ'] / future['QQQ'].cummax() - 1).min()
            
            if horizon_label == '3mo':
                ret_3m = fwd_ret
                dd_3m = max_dd
            elif horizon_label == '12mo':
                ret_12m = fwd_ret
                dd_12m = max_dd
        
        # Forward returns from START of inversion
        future_from_start_12m = df.loc[start:start + pd.DateOffset(days=378)]
        if len(future_from_start_12m) > 1:
            max_dd_from_start = (future_from_start_12m['QQQ'] / future_from_start_12m['QQQ'].cummax() - 1).min()
        else:
            max_dd_from_start = 0
        
        print(f"\n  Inversion: {start.date()} → {end.date()} ({duration}d)")
        print(f"    After un-inversion → 12mo fwd return: {ret_12m*100:+.1f}%, max DD: {dd_12m*100:.1f}%")
        print(f"    Max DD within 18mo of inversion START: {max_dd_from_start*100:.1f}%")

# ============================================================================
# PART 3: Forward return distributions — inverted vs normal
# ============================================================================
print("\n")
print("=" * 80)
print("PART 3: Forward Return Comparison — Inverted vs Normal Days")
print("=" * 80)

for label, col in [('10Y-2Y', 'T10Y2Y'), ('10Y-3M', 'T10Y3M')]:
    print(f"\n--- {label} ---")
    
    for horizon_name, horizon in [('63d (3mo)', 63), ('126d (6mo)', 126), ('252d (12mo)', 252)]:
        fwd = df['QQQ'].pct_change(horizon).shift(-horizon)
        
        inv_mask = df[col] < 0
        normal_mask = df[col] >= 0
        
        inv_fwd = fwd[inv_mask].dropna()
        norm_fwd = fwd[normal_mask].dropna()
        
        if len(inv_fwd) == 0:
            continue
        
        print(f"  {horizon_name}:")
        print(f"    Normal  (n={len(norm_fwd):4d}): mean={norm_fwd.mean()*100:+.1f}%, "
              f"median={norm_fwd.median()*100:+.1f}%, <-15%: {(norm_fwd < -0.15).mean()*100:.1f}%")
        print(f"    Inverted(n={len(inv_fwd):4d}): mean={inv_fwd.mean()*100:+.1f}%, "
              f"median={inv_fwd.median()*100:+.1f}%, <-15%: {(inv_fwd < -0.15).mean()*100:.1f}%")

# ============================================================================
# PART 4: Practical signal test — could you USE this?
# ============================================================================
print("\n")
print("=" * 80)
print("PART 4: Signal Timing Problem — Lead Time Analysis")
print("=" * 80)

print("""
Key issue: Yield curve inverts MONTHS to YEARS before the crash.
If you sell at inversion, you miss massive rallies.
If you wait for un-inversion, the crash may already be happening.
""")

# Calculate: if you went to cash at first inversion, and back in at un-inversion
# vs buy-and-hold
for label, col in [('10Y-2Y', 'T10Y2Y'), ('10Y-3M', 'T10Y3M')]:
    inverted = df[col] < 0
    # Strategy: hold QQQ when NOT inverted, hold cash when inverted
    strat_ret = df['QQQ_ret'].copy()
    strat_ret[inverted] = 0  # cash during inversion
    
    bh_cum = (1 + df['QQQ_ret']).cumprod()
    strat_cum = (1 + strat_ret).cumprod()
    
    bh_final = bh_cum.iloc[-1]
    strat_final = strat_cum.iloc[-1]
    
    years = (df.index[-1] - df.index[0]).days / 365.25
    bh_cagr = bh_final ** (1/years) - 1
    strat_cagr = strat_final ** (1/years) - 1
    
    # Max drawdown
    bh_dd = (bh_cum / bh_cum.cummax() - 1).min()
    strat_dd = (strat_cum / strat_cum.cummax() - 1).min()
    
    inv_days = inverted.sum()
    total_days = len(inverted)
    
    print(f"\n--- Naive strategy: sell QQQ when {label} < 0, hold cash ---")
    print(f"  Days inverted: {inv_days}/{total_days} ({inv_days/total_days*100:.1f}%)")
    print(f"  Buy & Hold:   CAGR={bh_cagr*100:+.1f}%, MDD={bh_dd*100:.1f}%")
    print(f"  YC Strategy:  CAGR={strat_cagr*100:+.1f}%, MDD={strat_dd*100:.1f}%")
    print(f"  CAGR diff:    {(strat_cagr - bh_cagr)*100:+.1f}pp")

# ============================================================================
# PART 5: Un-inversion (steepening) as crash signal
# ============================================================================
print("\n")
print("=" * 80)
print("PART 5: Un-Inversion (Re-steepening) as Crash Signal")
print("=" * 80)
print("The classic signal: crash comes when the curve UN-inverts (steepens)")
print("because it means the Fed is cutting → recession is HERE.\n")

for label, col in [('10Y-2Y', 'T10Y2Y'), ('10Y-3M', 'T10Y3M')]:
    inverted = df[col] < 0
    # Find un-inversion dates (inverted → not inverted)
    uninv_dates = []
    was_inv = False
    inv_start = None
    for date, is_inv in inverted.items():
        if is_inv and not was_inv:
            inv_start = date
        elif not is_inv and was_inv and inv_start is not None:
            duration = (date - inv_start).days
            if duration > 20:  # meaningful inversion
                uninv_dates.append((date, duration))
        was_inv = is_inv
    
    print(f"\n--- {label} un-inversion events ---")
    for uninv_date, dur in uninv_dates:
        # Forward returns
        for h_name, h_days in [('3mo', 63), ('6mo', 126), ('12mo', 252)]:
            future = df.loc[uninv_date:uninv_date + pd.DateOffset(days=h_days)]
            if len(future) < 2:
                continue
            fwd_ret = future['QQQ'].iloc[-1] / future['QQQ'].iloc[0] - 1
            max_dd = (future['QQQ'] / future['QQQ'].cummax() - 1).min()
            if h_name == '6mo':
                r6 = fwd_ret
                d6 = max_dd
            elif h_name == '12mo':
                r12 = fwd_ret
                d12 = max_dd
        
        crash_flag = "⚠️ CRASH" if d6 < -0.15 else "  ok"
        print(f"  Un-inverted: {uninv_date.date()} (was inverted {dur}d)")
        try:
            print(f"    6mo fwd: {r6*100:+.1f}%, MDD: {d6*100:.1f}%  "
                  f"| 12mo fwd: {r12*100:+.1f}%, MDD: {d12*100:.1f}%  {crash_flag}")
        except:
            print(f"    (insufficient forward data)")

print("\n")
print("=" * 80)
print("CONCLUSION")
print("=" * 80)
