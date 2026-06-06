#!/usr/bin/env python3
"""2023年四子图：上证+KDJ+成交量+近4月放大"""
import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
import os

for fp in ['/mnt/c/Windows/Fonts/simhei.ttf','/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif',[])
plt.rcParams['axes.unicode_minus'] = False

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20220701", end_date="20231231")
df = df.sort_values("trade_date").reset_index(drop=True)
close=df["close"].values; high=df["high"].values; low=df["low"].values
opens=df["open"].values; vol=df["vol"].values
dates=pd.to_datetime(df["trade_date"]).values

N, M1, M2 = 14,5,3
k=np.full(len(close),np.nan); d=np.full(len(close),np.nan)
for i in range(N-1,len(close)):
    hh=np.max(high[i-N+1:i+1]); ll=np.min(low[i-N+1:i+1])
    rsv=50 if hh==ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i]=rsv; d[i]=rsv
    else: k[i]=(rsv*1+k[i-1]*(M1-1))/M1; d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

p_up=np.full(len(close),50.0); p_down=np.full(len(close),50.0); p_risk=np.full(len(close),50.0)
ud=dd=rd=0; transitions=[]
for i in range(N,len(close)):
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

state=np.full(len(close),0,dtype=int); ps=0
sg={"金叉","高位死叉","K<35&D<40"}
for i in range(N,len(close)):
    pu_=p_up[i]; pdw_=p_down[i]; pr_=p_risk[i]
    s=1 if pu_>pr_ and pu_>pdw_ else 2 if pr_>pu_ and pr_>pdw_ else 3 if pdw_>pu_ and pdw_>pr_ else 0
    if s!=ps and ps>0 and s>0:
        ig2=k[i-1]<=d[i-1] and k[i]>d[i] if not np.isnan(k[i]) and not np.isnan(d[i-1]) else False
        hd2=(k[i-1]>=d[i-1] and k[i]<d[i] and k[i]>=85) if not np.isnan(k[i]) else False
        dz2=k[i]<35 and d[i]<40; t="金叉" if ig2 else("高位死叉" if hd2 else("K<35&D<40" if dz2 else "概率切换"))
        if t in sg: transitions.append((i,ps,s,t))
    state[i]=s; ps=s

# ── 只保留2023年数据 ──
# 找到2023年的索引范围
year2023_mask = (df['trade_date'] >= '20230101') & (df['trade_date'] <= '20231231')
y2023_idx = np.where(year2023_mask)[0]
s2023 = y2023_idx[0]  # start index in full array
e2023 = y2023_idx[-1] + 1  # end index (exclusive)

# 切片到2023范围
c_s = close[s2023:e2023]; k_s = k[s2023:e2023]; d_s = d[s2023:e2023]
p_up_s = p_up[s2023:e2023]; p_down_s = p_down[s2023:e2023]; p_risk_s = p_risk[s2023:e2023]
state_s = state[s2023:e2023]; dates_s = dates[s2023:e2023]; opens_s = opens[s2023:e2023]; vol_s = vol[s2023:e2023]
# 过滤子图范围内的信号
t_s = [(idx-s2023,fs,ts,trig) for idx,fs,ts,trig in transitions if idx>=s2023 and idx<e2023]
len_s = len(c_s)

# ── 图表配色 ──
c_bg='#0d1117'; c_ax='#161b22'; c_up='#00ff00'; c_risk='#ffff00'; c_down='#ff0000'
c_price='#ffffff'; c_k='#ff9900'; c_d='#33ddff'; c_j='#dd88ff'; c_grid='#333333'; c_label='#dddddd'
sn={0:"—",1:"↑上升",2:"⚠风险",3:"↓下降"}; sc={0:c_label,1:c_up,2:c_risk,3:c_down}

# 子图4：近4个月切片（2023年有12个月，取近4个月=80交易日）
M4=80; m4=max(0,len_s-M4)
d4=dates_s[m4:]; c4=c_s[m4:]; st4=state_s[m4:]; pu4=p_up_s[m4:]; pd4=p_down_s[m4:]; pr4=p_risk_s[m4:]
t4=[(idx,fs,ts,trig) for idx,fs,ts,trig in t_s if idx>=m4]

fig=plt.figure(figsize=(20,14),facecolor=c_bg)
ax1=fig.add_axes([0.07,0.58,0.90,0.42],facecolor=c_ax)
ax2=fig.add_axes([0.07,0.40,0.90,0.16],facecolor=c_ax)
ax3=fig.add_axes([0.07,0.22,0.90,0.16],facecolor=c_ax)
ax4=fig.add_axes([0.07,0.02,0.90,0.18],facecolor=c_ax)
DATE_FMT=lambda:mdates.DateFormatter('Y%yM%m')

def draw_state_spans(ax,da,ca,sa,pua,pda,pra,sl=True,ylt=0):
    ax.plot(da,ca,color=c_price,lw=1.6,alpha=0.95);i=0
    while i<len(ca):
        if sa[i]==0: i+=1;continue
        s=sa[i];j=i
        while j<len(ca) and sa[j]==s: j+=1
        for idx in range(i,j):
            if s==1: pv=pua[idx];a=0.10+(pv-55)/37*0.38 if pv>55 else 0.06
            elif s==2: pv=pra[idx];a=0.10+(pv-50)/38*0.38 if pv>50 else 0.06
            elif s==3: pv=pda[idx];a=0.10+(pv-50)/38*0.38 if pv>50 else 0.06
            a=max(0.06,min(0.55,a))
            if idx<len(ca)-1: ax.axvspan(da[idx],da[idx+1],alpha=a,color=sc[s],lw=0,zorder=0)
        if sl and ylt:
            ap=np.mean(pua[i:j] if s==1 else(pra[i:j] if s==2 else pda[i:j]))
            mid=i+(j-i)//2
            if mid<len(ca): ax.text(da[mid],ylt,f"{sn[s]} {ap:.0f}%",color=sc[s],fontsize=9,fontweight='bold',ha='center',va='top',bbox=dict(boxstyle='round,pad=0.2',facecolor=c_bg,edgecolor=sc[s],alpha=0.85))
        i=j

ym1,ymx=np.min(c_s),np.max(c_s);yr=ymx-ym1
draw_state_spans(ax1,dates_s,c_s,state_s,p_up_s,p_down_s,p_risk_s,True,ymx+yr*0.065)
ax1.set_ylim(ym1-yr*0.10,ymx+yr*0.15)
ax1.set_ylabel('上证指数 2023',color=c_label,fontsize=20)
ax1.tick_params(colors=c_label,labelsize=14);ax1.yaxis.set_minor_locator(MultipleLocator(100))
ax1.tick_params(which='minor',colors=c_label,length=3);ax1.grid(True,alpha=0.08,color=c_grid)
ax1.set_xlim(dates_s[0],dates_s[-1]);ax1.set_xticklabels([])

ax2.plot(dates_s,k_s,color=c_k,lw=1.5,alpha=0.9,label=f'K({M1})')
ax2.plot(dates_s,d_s,color=c_d,lw=1.5,alpha=0.9,label=f'D({M2})')
ax2.plot(dates_s,3*k_s-2*d_s,color=c_j,lw=0.8,alpha=0.5,label='J')
ax2.axhline(85,color=c_risk,ls='--',alpha=0.4,lw=1);ax2.axhline(35,color=c_down,ls='--',alpha=0.4,lw=1)
ax2.axhline(20,color=c_up,ls=':',alpha=0.3,lw=0.8);ax2.axhline(80,color=c_risk,ls=':',alpha=0.3,lw=0.8)
ax2.text(dates_s[-1],86,'超买85',color='#ffee00',fontsize=8,alpha=0.6)
ax2.text(dates_s[-1],33,'危险35',color=c_down,fontsize=8,alpha=0.6)

for idx,fs,ts,trig in t_s:
    yk=k_s[idx]
    if trig=="金叉":
        ax2.scatter(dates_s[idx],yk,color=c_up,s=60,marker='^',zorder=6,edgecolors='white',lw=0.8)
        ax2.annotate('金叉',xy=(dates_s[idx],yk),xytext=(dates_s[idx],yk+20),fontsize=8,color=c_up,fontweight='bold',ha='center',arrowprops=dict(arrowstyle='->',color=c_up,lw=1.5),bbox=dict(boxstyle='round,pad=0.15',facecolor=c_bg,edgecolor=c_up,alpha=0.9))
    elif trig=="高位死叉":
        ax2.scatter(dates_s[idx],yk,color=c_risk,s=60,marker='v',zorder=6,edgecolors='white',lw=0.8)
        ax2.annotate('高位死叉',xy=(dates_s[idx],yk),xytext=(dates_s[idx],yk-22),fontsize=8,color=c_risk,fontweight='bold',ha='center',va='top',arrowprops=dict(arrowstyle='->',color=c_risk,lw=1.5),bbox=dict(boxstyle='round,pad=0.15',facecolor=c_bg,edgecolor=c_risk,alpha=0.9))
    elif trig=="K<35&D<40":
        ax2.scatter(dates_s[idx],yk,color=c_down,s=60,marker='s',zorder=6,edgecolors='white',lw=0.8)
        ax2.annotate('K<35&D<40',xy=(dates_s[idx],yk),xytext=(dates_s[idx],yk-22),fontsize=8,color=c_down,fontweight='bold',ha='center',va='top',arrowprops=dict(arrowstyle='->',color=c_down,lw=1.5),bbox=dict(boxstyle='round,pad=0.15',facecolor=c_bg,edgecolor=c_down,alpha=0.9))
ax2.set_ylabel('KDJ',color=c_label,fontsize=16);ax2.tick_params(colors=c_label,labelsize=12)
ax2.grid(True,alpha=0.12,color=c_grid);ax2.set_ylim(-10,115)
ax2.set_xlim(dates_s[0],dates_s[-1]);ax2.set_xticklabels([])
ax2.legend(loc='upper left',fontsize=9,facecolor=c_bg,edgecolor=c_grid,labelcolor=c_label)

vc=[c_down if c_s[i]>=opens_s[i] else c_up for i in range(len_s)]
ax3.bar(dates_s,np.array(vol_s)/1e8,color=vc,alpha=0.6,width=0.7)
ax3.set_ylabel('成交量(亿手)',color=c_label,fontsize=16);ax3.tick_params(colors=c_label,labelsize=12)
ax3.grid(True,alpha=0.1,color=c_grid);ax3.set_xlim(dates_s[0],dates_s[-1])
ax3.xaxis.set_major_formatter(DATE_FMT());ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
ax3.xaxis.set_minor_locator(mdates.DayLocator(interval=5));ax3.tick_params(which='minor',colors=c_label,length=3)
plt.setp(ax3.xaxis.get_majorticklabels(),rotation=0,ha='center',fontsize=12,color=c_label)

for ax in [ax1,ax2]:
    ax.set_xlim(dates_s[0],dates_s[-1]);ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(DATE_FMT());ax.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
    ax.tick_params(which='minor',colors=c_label,length=3)
    plt.setp(ax.xaxis.get_majorticklabels(),rotation=0,ha='center',fontsize=12,color=c_label)

y4m1,y4mx=np.min(c4),np.max(c4);y4r=y4mx-y4m1
draw_state_spans(ax4,d4,c4,st4,pu4,pd4,pr4,True,y4mx+y4r*0.06)
ax4.set_ylim(y4m1-y4r*0.10,y4mx+y4r*0.10);ax4.set_ylabel('上证指数(近4月)',color=c_label,fontsize=15)
ax4.tick_params(colors=c_label,labelsize=12);ax4.grid(True,alpha=0.08,color=c_grid)
ax4.set_xlim(d4[0],d4[-1]);ax4.xaxis.set_major_formatter(DATE_FMT())
ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=1));ax4.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
ax4.tick_params(which='minor',colors=c_label,length=3)
plt.setp(ax4.xaxis.get_majorticklabels(),rotation=0,ha='center',fontsize=12,color=c_label)

out=f"/mnt/e/Hermes_workspace/stock_research/1.Shanghai_composite_trend_detect/20231231_2023四子图.png"
fig.savefig(out,dpi=150,facecolor=c_bg);plt.close(fig)
print(f"✅ {out}")
