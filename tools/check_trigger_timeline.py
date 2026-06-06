import yfinance as yf
import pandas as pd
import numpy as np

# Download data
tqqq = yf.download('TQQQ', start='2012-01-01', end='2024-01-01', progress=False)['Close']
if isinstance(tqqq, pd.DataFrame): tqqq = tqqq.iloc[:, 0]
hyg = yf.download('HYG', start='2012-01-01', end='2024-01-01', progress=False)['Close']
if isinstance(hyg, pd.DataFrame): hyg = hyg.iloc[:, 0]
ief = yf.download('IEF', start='2012-01-01', end='2024-01-01', progress=False)['Close']
if isinstance(ief, pd.DataFrame): ief = ief.iloc[:, 0]

# Calculate Credit Z-score
credit_ratio = hyg / ief
credit_ma = credit_ratio.rolling(252).mean()
credit_std = credit_ratio.rolling(252).std()
credit_z = -(credit_ratio - credit_ma) / credit_std

# Calculate Vol Z-score
daily_ret = tqqq.pct_change()
vol_20 = daily_ret.rolling(20).std() * np.sqrt(252)
vol_ma = vol_20.rolling(252).mean()
vol_std = vol_20.rolling(252).std()
vol_z = (vol_20 - vol_ma) / vol_std

# Combine into a dataframe
df = pd.DataFrame({'TQQQ': tqqq, 'Credit_Z': credit_z, 'Vol_Z': vol_z}).dropna()

# Analyze specific crises
crises = {
    '2018 Q4': ('2018-09-01', '2019-01-31'),
    '2020 COVID': ('2020-01-01', '2020-04-30'),
    '2022 Bear Market': ('2022-01-01', '2022-12-31')
}

for name, (start, end) in crises.items():
    print(f"--- {name} ---")
    sub_df = df.loc[start:end]
    
    vol_trigger = sub_df[sub_df['Vol_Z'] > 1.0].index.min()
    credit_trigger = sub_df[sub_df['Credit_Z'] > 1.2].index.min()
    
    print(f"Vol Trigger (> 1.0):    {vol_trigger.date() if pd.notna(vol_trigger) else 'Did not trigger'}")
    print(f"Credit Trigger (> 1.2): {credit_trigger.date() if pd.notna(credit_trigger) else 'Did not trigger'}")
    
    if pd.notna(vol_trigger) and pd.notna(credit_trigger):
        diff = (credit_trigger - vol_trigger).days
        print(f"Vol was faster by: {diff} days")
    print("\n")
