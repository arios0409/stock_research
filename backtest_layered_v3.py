#!/usr/bin/env python3
"""分层仓位回测 v3: 绿区分层买入,黄区持续3天卖出,红区立刻卖出"""
import tushare as ts
import pandas as pd
import numpy as np

TOKEN="0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro=ts.pro_api(TOKEN)

df=pro.index_daily(ts_code="000001.SH",start_date="20220701",end_date="20251231")
df=df.sort_values("trade_date").reset_index(drop=True)
close=df["close"].values;high=df["high"].values;low=df["low"].values;opens=df["open"].values
vol=df["vol"].values;dates=pd.to_datetime(df["trade_date"]).values;ds=df["trade_date"].values

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

def backtest():
    results={}
    for yr,sd,ed in YEARS:
        mask=(df['trade_date']>=sd)&(df['trade_date']<=ed)
        idxs=np.where(mask)[0];valid=[i for i in idxs if i>=N]
        if not valid:continue
        
        cash=1.0;units=0.0;trades=[];yellow_days=0
        
        for idx in valid:
            price=close[idx];s=state[idx];puv=pu[idx];pdv=pd_[idx]
            nav=cash+units*price
            
            # 连续黄色计数
            if s==2: yellow_days+=1
            else: yellow_days=0
            
            # ── 买入（仅绿色） ──
            if s==1:
                target=0.5 if (50<puv<=70) else (1.0 if puv>70 else None)
                if target is not None:
                    cur_pct=units*price/nav if nav>0 else 0
                    if cur_pct<target-0.01:
                        need_val=target*nav-units*price
                        spend=min(need_val,cash)
                        if spend>0:
                            trades.append((ds[idx],f"买入至{target*100:.0f}%",price,cur_pct,target,cash,units*price))
                            units+=spend/price;cash-=spend
            
            # ── 卖出：黄色3天以上 或 红色一律 ──
            sell_all=False
            reason=""
            if s==2 and yellow_days>=3 and units>0:
                sell_all=True;reason="黄区≥3天清仓"
            if s==3 and units>0:
                sell_all=True;reason="红区清仓"
            
            if sell_all:
                cur_val=units*price;cur_pct=cur_val/nav if nav>0 else 0
                cash+=cur_val
                trades.append((ds[idx],reason,price,cur_pct,0.0,cash-cur_val,0))
                units=0.0;yellow_days=0
        
        # 年末平仓
        if units>0:
            cash+=units*close[valid[-1]]
            trades.append((ds[valid[-1]],"年末平仓",close[valid[-1]],0,0,cash,0))
            units=0
        
        start_p=close[valid[0]];end_p=close[valid[-1]]
        bh=(end_p/start_p-1)*100;strat=(cash-1)*100
        results[yr]={'trades':trades,'ret':strat,'bh':bh,'start':start_p,'end':end_p}
    return results

res=backtest()
total_s=1.0;total_b=1.0

for yr in ['2023','2024','2025']:
    r=res[yr];t=r['trades']
    buys=len([x for x in t if '买入' in x[1]])
    sells=len([x for x in t if '清仓' in x[1] or '平仓' in x[1]])
    
    print(f"\n{'='*70}")
    print(f"  {yr}年  开盘点:{r['start']:.0f}→{r['end']:.0f}  上证:{r['bh']:+.2f}%")
    print(f"{'='*70}")
    for d,act,pr,pa,pb,c,v in t:
        print(f"  {d} {act} @{pr:.0f}  仓位{pb*100:.0f}%→{pa*100:.0f}%")
    
    print(f"\n  操作:{buys}次买入 {sells}次卖出")
    print(f"  🏆 策略:{r['ret']:+.2f}%  上证:{r['bh']:+.2f}%  超额:{r['ret']-r['bh']:+.2f}%")
    total_s*=(1+r['ret']/100);total_b*=(1+r['bh']/100)

print(f"\n{'='*70}")
print(f"  三年累计  策略:{(total_s-1)*100:+.2f}%  上证:{(total_b-1)*100:+.2f}%  超额:{(total_s-total_b)*100:+.2f}%")
print(f"{'='*70}")
