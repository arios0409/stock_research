#!/usr/bin/env python3
"""2023年大盘趋势全扫描：状态变化 + 概率走势"""
import tushare as ts
import pandas as pd
import numpy as np

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20220701", end_date="20231231")
df = df.sort_values("trade_date").reset_index(drop=True)
close = df["close"].values; high = df["high"].values; low = df["low"].values
dates = pd.to_datetime(df["trade_date"]).values
date_str = df["trade_date"].values

N, M1, M2 = 14, 5, 3
k = np.full(len(close), np.nan, dtype=float); d = np.full(len(close), np.nan, dtype=float)
for i in range(N-1, len(close)):
    hh=np.max(high[i-N+1:i+1]); ll=np.min(low[i-N+1:i+1])
    rsv=50.0 if hh==ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i]=rsv; d[i]=rsv
    else: k[i]=(rsv*1+k[i-1]*(M1-1))/M1; d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

p_up=np.full(len(close),50.0); p_down=np.full(len(close),50.0); p_risk=np.full(len(close),50.0)
ud=dd=rd=0
for i in range(N, len(close)):
    pu=p_up[i-1]; pdw=p_down[i-1]; pr=p_risk[i-1]
    ig=k[i-1]<=d[i-1] and k[i]>d[i]; id_=k[i-1]>=d[i-1] and k[i]<d[i]
    hd=id_ and k[i]>=85; dz=k[i]<35 and d[i]<40; lg=ig and k[i]<30 and d[i]<30
    ud=ud+1 if k[i]>d[i] else 0; dd=dd+1 if dz else 0; rd=rd+1 if(k[i]<d[i] and k[i]>=85) else 0
    if k[i]>d[i]: p_up_val=80 if lg else(60 if ig else min(60+ud*5,92))
    else: p_up_val=30 if id_ else max(pu-(dd*8 if dd>0 else 3),10)
    if dz: p_down_val=min(55+dd*5,88)
    elif k[i]<d[i] and k[i]<50: p_down_val=min(45+(50-k[i])*1.5,80)
    elif hd: p_down_val=50
    elif rd>=1: p_down_val=min(50+rd*3,70)
    elif ig: p_down_val=max(pdw-15,10)
    else: p_down_val=max(pdw-2,20)
    if hd: p_risk_val=65
    elif rd>=1 and k[i]<d[i]: p_risk_val=min(65+rd*5,88)
    elif k[i]<d[i] and k[i]>=75: p_risk_val=min(45+(k[i]-75)*2,65)
    elif dz: p_risk_val=max(pr-10,10)
    elif ig: p_risk_val=max(pr-20,5)
    else: p_risk_val=max(pr-2,15)
    p_up[i]=p_up_val; p_down[i]=p_down_val; p_risk[i]=p_risk_val

state=np.full(len(close),0,dtype=int)
sn={0:"—震荡",1:"↑上升",2:"⚠风险",3:"↓下降"}
for i in range(N, len(close)):
    pu=p_up[i]; pdw=p_down[i]; pr=p_risk[i]
    if pu>pr and pu>pdw: state[i]=1
    elif pr>pu and pr>pdw: state[i]=2
    elif pdw>pu and pdw>pr: state[i]=3

# 按月分块输出
print(f"{'='*140}")
print("2023年 上证指数 KDJ概率趋势系统 — 全量扫描")
print(f"{'='*140}")
print(f"{'日期':<12} {'收盘':>8} {'K':>6} {'D':>6} {'P_up':>6} {'P_down':>6} {'P_risk':>6} {'状态':>8} {'信号':>12}")
print("-"*80)

prev_s = 0
for i in range(N, len(close)):
    if date_str[i][:4] != '2023': continue
    
    # 信号检测
    sig = ""
    if not np.isnan(k[i]) and not np.isnan(k[i-1]):
        if k[i-1]<=d[i-1] and k[i]>d[i]: sig="金叉↑"
        elif k[i-1]>=d[i-1] and k[i]<d[i] and k[i]>=85: sig="高位死叉↓"
    
    # 状态变化标记
    if state[i] != prev_s and prev_s > 0:
        arrow = f" {sn[prev_s]}→{sn[state[i]]}"
    else:
        arrow = ""
    prev_s = state[i]
    
    print(f"{date_str[i]:<12} {close[i]:>8.1f} {k[i]:>6.1f} {d[i]:>6.1f} {p_up[i]:>5.0f}% {p_down[i]:>5.0f}% {p_risk[i]:>5.0f}% {sn[state[i]]:>8} {sig:>12}{arrow}")

# 按状态区间汇总
print(f"\n{'='*80}")
print("状态区间汇总")
print(f"{'='*80}")

# 找出2023年有效索引
valid_idx = [i for i in range(N, len(close)) if date_str[i][:4] == '2023']
if valid_idx:
    start_i = valid_idx[0]
    segments = []
    current_state = state[start_i]
    seg_start = start_i
    for i in valid_idx[1:]:
        if state[i] != current_state:
            segments.append((seg_start, i, current_state))
            current_state = state[i]
            seg_start = i
    segments.append((seg_start, valid_idx[-1], current_state))
    
    for s, e, st in segments:
        s_date = date_str[s]
        e_date = date_str[e-1] if e < len(date_str) else date_str[s]
        days = (pd.Timestamp(e_date) - pd.Timestamp(s_date)).days
        chg = (close[e-1] - close[s]) / close[s] * 100 if e < len(close) else 0
        print(f"  {sn[st]:>8}  {s_date}~{e_date}  ({days}天)  涨跌{chg:+.2f}%")

# 每月统计
print(f"\n{'='*80}")
print("月度统计")
print(f"{'='*80}")
print(f"{'月份':>6} {'状态分布':>30} {'月涨跌':>8} {'P_up均值':>8}")
for m in range(1, 13):
    m_idx = [i for i in valid_idx if date_str[i][4:6] == f"{m:02d}"]
    if not m_idx: continue
    sts = [state[i] for i in m_idx]
    s1=sts.count(1); s2=sts.count(2); s3=sts.count(3); s0=sts.count(0)
    st_str=f"↑{s1} ⚠{s2} ↓{s3} —{s0}"
    chg = (close[m_idx[-1]] - close[m_idx[0]]) / close[m_idx[0]] * 100
    avg_pu = np.mean([p_up[i] for i in m_idx])
    print(f"  {m:>4}月  {st_str:>30}  {chg:>+7.2f}%  {avg_pu:>6.1f}%")
