#!/usr/bin/env python3
"""参数网格搜索：分层仓位买入/卖出 三年最优组合"""
import tushare as ts
import pandas as pd
import numpy as np

TOKEN="0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro=ts.pro_api(TOKEN)

df=pro.index_daily(ts_code="000001.SH",start_date="20220701",end_date="20251231")
df=df.sort_values("trade_date").reset_index(drop=True)
close=df["close"].values;high=df["high"].values;low=df["low"].values
dates=pd.to_datetime(df["trade_date"]).values;ds=df["trade_date"].values

N,M1,M2=14,5,3
k=np.full(len(close),np.nan);d=np.full(len(close),np.nan)
for i in range(N-1,len(close)):
    hh=np.max(high[i-N+1:i+1]);ll=np.min(low[i-N+1:i+1])
    rsv=50 if hh==ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]):k[i]=rsv;d[i]=rsv
    else:k[i]=(rsv*1+k[i-1]*(M1-1))/M1;d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

pu=np.full(len(close),50.0);pd_=np.full(len(close),50.0);pr=np.full(len(close),50.0)
ud=dd=rd=0
for i in range(N,len(close)):
    pu_=pu[i-1];pdw_=pd_[i-1];pr_=pr[i-1];ig=k[i-1]<=d[i-1] and k[i]>d[i];id_=k[i-1]>=d[i-1] and k[i]<d[i]
    hd=id_ and k[i]>=85;dz=k[i]<35 and d[i]<40;lg=ig and k[i]<30 and d[i]<30
    ud=ud+1 if k[i]>d[i] else 0;dd=dd+1 if dz else 0;rd=rd+1 if(k[i]<d[i] and k[i]>=85) else 0
    if k[i]>d[i]:puv=80 if lg else(60 if ig else min(60+ud*5,92))
    else:puv=30 if id_ else max(pu_-(dd*8 if dd>0 else 3),10)
    if dz:pdv=min(55+dd*5,88)
    elif k[i]<d[i] and k[i]<50:pdv=min(45+(50-k[i])*1.5,80)
    elif hd:pdv=50
    elif rd>=1:pdv=min(50+rd*3,70)
    elif ig:pdv=max(pdw_-15,10)
    else:pdv=max(pdw_-2,20)
    if hd:prv=65
    elif rd>=1 and k[i]<d[i]:prv=min(65+rd*5,88)
    elif k[i]<d[i] and k[i]>=75:prv=min(45+(k[i]-75)*2,65)
    elif dz:prv=max(pr_-10,10)
    elif ig:prv=max(pr_-20,5)
    else:prv=max(pr_-2,15)
    pu[i]=puv;pd_[i]=pdv;pr[i]=prv

state=np.full(len(close),0,dtype=int)
for i in range(N,len(close)):
    pu2=pu[i];pdw2=pd_[i];pr2=pr[i]
    if pu2>pr2 and pu2>pdw2:state[i]=1
    elif pr2>pu2 and pr2>pdw2:state[i]=2
    elif pdw2>pu2 and pdw2>pr2:state[i]=3

YEARS=[('2023','20230101','20231231'),('2024','20240101','20241231'),('2025','20250101','20251231')]

def backtest(buy_low, buy_high, sell_yellow_days, sell_red_pdown):
    """
    buy_low: P_up ≥ buy_low 买入半仓
    buy_high: P_up ≥ buy_high 买入满仓
    sell_yellow_days: 黄色N天后清仓 (999=永不)
    sell_red_pdown: 红色P_down>X时清仓 (0=红色就清)
    """
    total_compound=1.0
    details=[]
    for yr,sd,ed in YEARS:
        mask=(df['trade_date']>=sd)&(df['trade_date']<=ed)
        idxs=np.where(mask)[0];valid=[i for i in idxs if i>=N]
        if not valid:continue
        cash=1.0;units=0.0;yellow_days=0;trades=0
        for idx in valid:
            price=close[idx];s=state[idx];puv=pu[idx];pdv=pd_[idx]
            nav=cash+units*price
            
            if s==2:yellow_days+=1
            else:yellow_days=0
            
            # 买入
            if s==1:
                target=None
                if buy_low <= puv < buy_high:target=0.5
                elif puv >= buy_high:target=1.0
                if target is not None:
                    cur_pct=units*price/nav if nav>0 else 0
                    if cur_pct<target-0.01:
                        need=target*nav-units*price
                        spend=min(need,cash)
                        if spend>0:units+=spend/price;cash-=spend;trades+=1
            
            # 卖出
            sell=False
            if s==2 and yellow_days>=sell_yellow_days and units>0:sell=True
            if s==3 and units>0:
                if pdv>sell_red_pdown:sell=True
            
            if sell:
                cash+=units*price;units=0.0;yellow_days=0;trades+=1
        
        if units>0:
            cash+=units*close[valid[-1]];units=0
            trades+=1
        ret=(cash-1)*100
        total_compound*=cash
        details.append(ret)
    total=(total_compound-1)*100
    return total,details

# ── 网格搜索 ──
results=[]
buy_lows=[50,55,60,65]
buy_highs=[65,70,75,80,85]
sell_days=[1,2,3,4,5,999]  # 999=永不卖黄
sell_pdowns=[0,30,40,50,60]  # 0=红色就卖

total_combos=len(buy_lows)*len(buy_highs)*len(sell_days)*len(sell_pdowns)
print(f"搜索{total_combos}个组合...\n")

i=0
for bl in buy_lows:
    for bh in buy_highs:
        if bh<=bl:continue  # 保证半仓<满仓
        for sd in sell_days:
            for sp in sell_pdowns:
                total,ann=backtest(bl,bh,sd,sp)
                results.append((total,bl,bh,sd,sp,ann))
                i+=1

results.sort(key=lambda x:-x[0])

# Top 15
print(f"{'排名':>4} {'买入半仓':>8} {'买入满仓':>8} {'黄区卖出':>8} {'红区条件':>8} {'2023':>8} {'2024':>8} {'2025':>8} {'三年':>8}")
print("-"*80)
for rank,(tot,bl,bh,sd,sp,ann) in enumerate(results[:15],1):
    sd_str=f"{sd}天" if sd!=999 else "永不"
    sp_str=f"P↓>{sp}" if sp>0 else "红即卖"
    print(f"{rank:>4}    P≥{bl:<4}     P≥{bh:<4}     {sd_str:<6}     {sp_str:<6}   {ann[0]:>+6.2f}% {ann[1]:>+6.2f}% {ann[2]:>+6.2f}% {tot:>+7.2f}%")

# 最佳组合详细
print(f"\n{'='*80}")
bl,bh,sd,sp=results[0][1],results[0][2],results[0][3],results[0][4]
print(f"🏆 最优: 半仓≥{bl} / 满仓≥{bh} / {'黄区'+str(sd)+'天清仓' if sd!=999 else '黄区不清仓'} / {'红区P↓>'+str(sp)+'清仓' if sp>0 else '红区即清'}")

# 再看几个有意思的特殊组合
print(f"\n{'='*80}")
print("特殊组合对比:")
special_labels=[
    (50,70,999,0,"原始:半50满70,黄不清红即卖"),
    (60,80,999,0,"半60满80,黄不清红即卖"),
    (65,80,999,0,"半65满80,黄不清红即卖"),
    (55,75,3,0,"半55满75,黄3天清红即卖"),
    (60,80,5,40,"半60满80,黄5天清红P↓>40"),
    (55,75,999,50,"半55满75,黄不清红P↓>50清"),
    (60,75,999,40,"半60满75,黄不清红P↓>40"),
    (65,80,999,50,"半65满80,黄不清红P↓>50"),
]
for bl,bh,sd,sp,label in special_labels:
    total,ann=backtest(bl,bh,sd,sp)
    print(f"  {label}:  {ann[0]:>+6.2f}% {ann[1]:>+6.2f}% {ann[2]:>+6.2f}%  三年{total:>+7.2f}%")
