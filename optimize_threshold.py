#!/usr/bin/env python3
"""阈值优化：扫描P_up买入阈值，找三年累计收益最大化"""
import tushare as ts
import pandas as pd
import numpy as np

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20220701", end_date="20251231")
df = df.sort_values("trade_date").reset_index(drop=True)
close = df["close"].values; high = df["high"].values; low = df["low"].values
opens = df["open"].values; dates = pd.to_datetime(df["trade_date"]).values
date_strs = df["trade_date"].values

N, M1, M2 = 14, 5, 3
k = np.full(len(close), np.nan, dtype=float); d = np.full(len(close), np.nan, dtype=float)
for i in range(N - 1, len(close)):
    hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
    rsv = 50.0 if hh == ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i]=rsv; d[i]=rsv
    else: k[i]=(rsv*1+k[i-1]*(M1-1))/M1; d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

p_up = np.full(len(close), 50.0); p_down = np.full(len(close), 50.0); p_risk = np.full(len(close), 50.0)
up_days = down_days = risk_days = 0
for i in range(N, len(close)):
    pu=p_up[i-1]; pdw=p_down[i-1]; pr=p_risk[i-1]
    ig=k[i-1]<=d[i-1] and k[i]>d[i]; id_=k[i-1]>=d[i-1] and k[i]<d[i]
    hd=id_ and k[i]>=85; dz=k[i]<35 and d[i]<40; lg=ig and k[i]<30 and d[i]<30
    up_days=up_days+1 if k[i]>d[i] else 0; down_days=down_days+1 if dz else 0; risk_days=risk_days+1 if(k[i]<d[i] and k[i]>=85) else 0
    if k[i]>d[i]: p_up_val=80 if lg else(60 if ig else min(60+up_days*5,92))
    else: p_up_val=30 if id_ else max(pu-(down_days*8 if down_days>0 else 3), 10)
    if dz: p_down_val=min(55+down_days*5,88)
    elif k[i]<d[i] and k[i]<50: p_down_val=min(45+(50-k[i])*1.5,80)
    elif hd: p_down_val=50
    elif risk_days>=1: p_down_val=min(50+risk_days*3,70)
    elif ig: p_down_val=max(pdw-15,10)
    else: p_down_val=max(pdw-2,20)
    if hd: p_risk_val=65
    elif risk_days>=1 and k[i]<d[i]: p_risk_val=min(65+risk_days*5,88)
    elif k[i]<d[i] and k[i]>=75: p_risk_val=min(45+(k[i]-75)*2,65)
    elif dz: p_risk_val=max(pr-10,10)
    elif ig: p_risk_val=max(pr-20,5)
    else: p_risk_val=max(pr-2,15)
    p_up[i]=p_up_val; p_down[i]=p_down_val; p_risk[i]=p_risk_val

state = np.full(len(close), 0, dtype=int)
for i in range(N, len(close)):
    pu=p_up[i]; pdw=p_down[i]; pr=p_risk[i]
    if pu>pr and pu>pdw: state[i]=1
    elif pr>pu and pr>pdw: state[i]=2
    elif pdw>pu and pdw>pr: state[i]=3

YEARS = [('2023','20230101','20231231'),('2024','20240101','20241231'),('2025','20250101','20251231')]

def backtest(thresh):
    """给定阈值返回 三年累计收益率、每年明细"""
    annual_rets = []
    total_compound = 1.0
    for yr_name, start, end in YEARS:
        mask = (df['trade_date']>=start)&(df['trade_date']<=end)
        idxs = np.where(mask)[0]
        valid = [i for i in idxs if i>=N]
        if not valid: continue
        compound=1.0; in_pos=False; buy_price=None
        for i in valid:
            if not in_pos and state[i]==1 and p_up[i]>thresh:
                buy_price=close[i]; in_pos=True
            elif in_pos and state[i]==3:
                compound*=(1+(close[i]-buy_price)/buy_price)
                in_pos=False; buy_price=None
        if in_pos:
            last=close[valid[-1]]
            compound*=(1+(last-buy_price)/buy_price)
        ret=(compound-1)*100
        annual_rets.append(ret)
        total_compound*=compound
    total_ret=(total_compound-1)*100
    return total_ret, annual_rets

print(f"{'阈值':>6} {'2023':>10} {'2024':>10} {'2025':>10} {'三年累计':>10}")
print("-"*50)
best_thresh=None; best_ret=-999

for t in range(50, 96, 2):
    total, ann = backtest(t)
    print(f"{'P_up>'+str(t):>6} {ann[0]:>+9.2f}% {ann[1]:>+9.2f}% {ann[2]:>+9.2f}% {total:>+9.2f}%")
    if total > best_ret:
        best_ret = total
        best_thresh = t

print("\n" + "="*50)
print(f"🏆 最优阈值: P_up > {best_thresh}%  三年累计收益: {best_ret:+.2f}%")
print("="*50)

# 最优阈值详细展示
print(f"\n{'='*60}")
print(f"P_up > {best_thresh}% 详细交易记录")
for yr_name, start, end in YEARS:
    mask=(df['trade_date']>=start)&(df['trade_date']<=end)
    idxs=np.where(mask)[0]; valid=[i for i in idxs if i>=N]
    if not valid: continue
    trades=[]
    in_pos=False; buy_idx=None; buy_price=None
    for i in valid:
        if not in_pos and state[i]==1 and p_up[i]>best_thresh:
            buy_idx=i; buy_price=close[i]; in_pos=True
        elif in_pos and state[i]==3:
            trades.append((date_strs[buy_idx],buy_price,date_strs[i],close[i],(close[i]-buy_price)/buy_price*100))
            in_pos=False; buy_idx=None; buy_price=None
    if in_pos:
        last=close[valid[-1]]
        trades.append((date_strs[buy_idx],buy_price,date_strs[valid[-1]]+"(年末)",last,(last-buy_price)/buy_price*100))
    if trades:
        print(f"\n  {yr_name}年 ({len(trades)}笔):")
        for bd,bp,sd,sp,r in trades:
            print(f"    {bd}买({bp:.0f})→{sd}卖({sp:.0f}) {r:+.2f}%")
        compound=1; w=0
        for _,_,_,_,r in trades:
            compound*=(1+r/100)
            if r>0: w+=1
        print(f"    胜率{w}/{len(trades)}={w/len(trades)*100:.0f}% 累计{(compound-1)*100:+.2f}%")
