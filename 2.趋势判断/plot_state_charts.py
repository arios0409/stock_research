#!/usr/bin/env python3
"""两张图：1.上证指数+KDJ 2.状态机概率+迁移标记"""

import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import os

# 字体
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf','/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif',[])
plt.rcParams['axes.unicode_minus'] = False

# ===== 数据 =====
TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)
df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260520")
df = df.sort_values("trade_date").reset_index(drop=True)
close = df["close"].values; high = df["high"].values; low = df["low"].values
dates = pd.to_datetime(df["trade_date"]).values

N, M1, M2 = 14, 5, 3
k = np.full(len(close), np.nan, dtype=float)
d = np.full(len(close), np.nan, dtype=float)
for i in range(N - 1, len(close)):
    hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
    rsv = 50.0 if hh == ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i]=rsv; d[i]=rsv
    else:
        k[i]=(rsv*1+k[i-1]*(M1-1))/M1
        d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

# ===== 概率系统 =====
p_up = np.full(len(close), 50.0); p_down = np.full(len(close), 50.0); p_risk = np.full(len(close), 50.0)
up_days = down_days = risk_days = 0

# 记录所有状态切换
transitions = []  # (idx, from_state, to_state, trigger, prob_val)

for i in range(N, len(close)):
    prev_up = p_up[i-1]; prev_down = p_down[i-1]; prev_risk = p_risk[i-1]
    
    # 信号
    is_golden = k[i-1] <= d[i-1] and k[i] > d[i]
    is_death = k[i-1] >= d[i-1] and k[i] < d[i]
    high_death = is_death and k[i] >= 85
    in_down_zone = k[i] < 35 and d[i] < 40
    
    up_days = up_days+1 if k[i] > d[i] else 0
    down_days = down_days+1 if in_down_zone else 0
    risk_days = risk_days+1 if (k[i] < d[i] and k[i] >= 85) else 0
    
    # P_up
    if k[i] > d[i]:
        p_up_val = 80 if (is_golden and k[i] < 30 and d[i] < 30) else (60 if is_golden else min(60+up_days*5,92))
    else:
        p_up_val = 30 if is_death else max(prev_up-(down_days*8 if down_days>0 else 3), 10)
    
    # P_down
    if in_down_zone: p_down_val = min(55+down_days*5, 88)
    elif k[i] < d[i] and k[i] < 50: p_down_val = min(45+(50-k[i])*1.5, 80)
    elif high_death: p_down_val = 50
    elif risk_days >= 1: p_down_val = min(50+risk_days*3, 70)
    elif is_golden: p_down_val = max(prev_down-15, 10)
    else: p_down_val = max(prev_down-2, 20)
    
    # P_risk
    if high_death: p_risk_val = 65
    elif risk_days >= 1 and k[i] < d[i]: p_risk_val = min(65+risk_days*5, 88)
    elif k[i] < d[i] and k[i] >= 75: p_risk_val = min(45+(k[i]-75)*2, 65)
    elif in_down_zone: p_risk_val = max(prev_risk-10, 10)
    elif is_golden: p_risk_val = max(prev_risk-20, 5)
    else: p_risk_val = max(prev_risk-2, 15)
    
    p_up[i]=p_up_val; p_down[i]=p_down_val; p_risk[i]=p_risk_val

# 状态判定 + 记录切换
state = np.full(len(close), 0, dtype=int)
prev_s = 0
triggers = {1:"金叉", 2:"高位死叉", 3:"K<35&D<40"}

for i in range(N, len(close)):
    # 判断当前状态
    s = 1 if (p_up[i] > p_risk[i] and p_up[i] > p_down[i]) else \
        2 if (p_risk[i] > p_up[i] and p_risk[i] > p_down[i]) else \
        3 if (p_down[i] > p_up[i] and p_down[i] > p_risk[i]) else 0
    
    if s != prev_s and prev_s > 0 and s > 0:
        # 确定触发原因
        is_g = k[i-1] <= d[i-1] and k[i] > d[i] if not np.isnan(k[i]) and not np.isnan(k[i-1]) and not np.isnan(d[i]) and not np.isnan(d[i-1]) else False
        is_hd = (k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85) if not np.isnan(k[i]) and not np.isnan(k[i-1]) and not np.isnan(d[i]) and not np.isnan(d[i-1]) else False
        is_dz = k[i] < 35 and d[i] < 40
        
        trig = "金叉" if is_g else ("高位死叉" if is_hd else ("K<35&D<40" if is_dz else "概率切换"))
        prob_key = p_up[i] if s == 1 else (p_risk[i] if s == 2 else p_down[i])
        transitions.append((i, prev_s, s, trig, prob_key))
    
    state[i] = s
    prev_s = s

# 状态名
sn = {0:"—", 1:"↑上升", 2:"⚠风险", 3:"↓下降"}
sc = {0:"#8b949e", 1:"#3fb950", 2:"#d29922", 3:"#f85149"}

# ========================================================
# 图1：上证指数 + KDJ(14,5,3) 状态区间   y=[2500,4300]
# ========================================================
fig1, ax1 = plt.subplots(1, 1, figsize=(18, 8), facecolor='#0d1117')
ax1.set_facecolor('#161b22')

# 价格线
ax1.plot(dates, close, color='#e6edf3', linewidth=1.2, alpha=0.8, label='收盘价')

# KDJ线（用右侧轴）
ax1b = ax1.twinx()
ax1b.plot(dates, k, color='#f0883e', linewidth=1.0, alpha=0.7, label=f'K({M1})')
ax1b.plot(dates, d, color='#58a6ff', linewidth=1.0, alpha=0.7, label=f'D({M2})')
ax1b.plot(dates, 3*k-2*d, color='#d2a8ff', linewidth=0.6, alpha=0.4, label='J')
ax1b.axhline(y=80, color='#f85149', linestyle='--', alpha=0.2, linewidth=0.6)
ax1b.axhline(y=20, color='#3fb950', linestyle='--', alpha=0.2, linewidth=0.6)
ax1b.axhline(y=35, color='#d29922', linestyle=':', alpha=0.15, linewidth=0.5)
ax1b.set_ylabel('KDJ', color='#8b949e', fontsize=10)
ax1b.tick_params(colors='#8b949e', labelsize=8)
ax1b.set_ylim(-10, 115)

# 状态区间背景
for i in range(N, len(close)):
    if state[i] > 0 and state[i] != state[i-1]:
        # 找到这段状态的结束
        j = i
        while j < len(close) and state[j] == state[i]:
            j += 1
        ax1.axvspan(dates[i], dates[j-1], alpha=0.08, color=sc[state[i]], zorder=0)
        # 状态标签
        mid = i + (j-i)//2
        if mid < len(close):
            ax1.text(dates[mid], 4350, sn[state[i]], color=sc[state[i]], fontsize=9,
                    fontweight='bold', ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.15', facecolor='#0d1117', edgecolor=sc[state[i]], alpha=0.7))

# KDJ参考线标注
ax1b.text(dates[-1], 82, "超买80", color='#f85149', fontsize=7, alpha=0.5, ha='left')
ax1b.text(dates[-1], 18, "超卖20", color='#3fb950', fontsize=7, alpha=0.5, ha='left')
ax1b.text(dates[-1], 33, "K<35", color='#d29922', fontsize=7, alpha=0.5, ha='left')

ax1.set_ylim(2500, 4400)
ax1.set_title('上证指数 + KDJ(14,5,3) 三状态区间', fontsize=15, color='#e6edf3', fontweight='bold')
ax1.set_ylabel('指数', color='#8b949e', fontsize=10)
ax1.tick_params(colors='#8b949e', labelsize=9)
ax1.grid(True, alpha=0.1, color='#30363d')
ax1.set_xlim(dates[0], dates[-1])

# 合并图例
l1, l2 = ax1.get_legend_handles_labels(), ax1b.get_legend_handles_labels()
ax1.legend(l1[0]+l2[0], l1[1]+l2[1], loc='upper left', fontsize=8,
           facecolor='#0d1117', edgecolor='#30363d', labelcolor='#e6edf3')

ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

plt.tight_layout()
fig1.savefig('/mnt/e/Hermes_workspace/stock_research/2.趋势判断/图1_上证指数_KDJ_状态区间.png', dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close(fig1)
print("✅ 图1 已保存")

# ========================================================
# 图2：概率曲线 + 状态迁移标记
# ========================================================
fig2, ax2 = plt.subplots(1, 1, figsize=(18, 8), facecolor='#0d1117')
ax2.set_facecolor('#161b22')

ax2.plot(dates, p_up, color='#3fb950', linewidth=2.0, alpha=0.9, label='P_up 上涨概率')
ax2.plot(dates, p_down, color='#f85149', linewidth=2.0, alpha=0.9, label='P_down 下降概率')
ax2.plot(dates, p_risk, color='#d29922', linewidth=2.0, alpha=0.9, label='P_risk 风险概率')

ax2.axhline(y=60, color='#3fb950', linestyle='--', alpha=0.3, linewidth=0.8)
ax2.axhline(y=50, color='#8b949e', linestyle=':', alpha=0.2, linewidth=0.6)
ax2.fill_between(dates[N:], 60, p_up[N:], alpha=0.08, color='#3fb950', where=(p_up[N:]>=60))

# 状态区间背景
for i in range(N, len(close)):
    if state[i] > 0 and state[i] != state[i-1]:
        j = i
        while j < len(close) and state[j] == state[i]:
            j += 1
        ax2.axvspan(dates[i], dates[j-1], alpha=0.06, color=sc[state[i]], zorder=0)

# 标注状态迁移点（只保留有明确信号的切换，交替上下偏移避免重叠）
sv = {1:"↑", 2:"⚠", 3:"↓"}
signal_triggers = {"金叉", "高位死叉", "K<35&D<40"}
annot_idx = 0
for idx, fs, ts, trig, pv in transitions:
    if trig not in signal_triggers:
        continue
    y_val = p_up[idx] if ts == 1 else (p_risk[idx] if ts == 2 else p_down[idx])
    
    # 交替偏移：奇数次向上，偶数次向下
    offset_y = 22 if annot_idx % 2 == 0 else -18
    va = 'bottom' if annot_idx % 2 == 0 else 'top'
    annot_idx += 1
    
    ax2.annotate(f'{sv[fs]}→{sv[ts]}\n{trig}',
                xy=(dates[idx], y_val),
                xytext=(dates[idx], y_val + offset_y),
                fontsize=7.5, color=sc[ts], fontweight='bold', ha='center', va=va,
                arrowprops=dict(arrowstyle='->', color=sc[ts], lw=1.2),
                bbox=dict(boxstyle='round,pad=0.15', facecolor='#0d1117', edgecolor=sc[ts], alpha=0.8))

ax2.set_title('KDJ概率趋势系统 — 状态迁移标注', fontsize=15, color='#e6edf3', fontweight='bold')
ax2.legend(loc='upper left', fontsize=9, facecolor='#0d1117', edgecolor='#30363d', labelcolor='#e6edf3')
ax2.set_ylabel('概率 %', color='#8b949e', fontsize=10)
ax2.set_ylim(0, 105)
ax2.tick_params(colors='#8b949e', labelsize=9)
ax2.grid(True, alpha=0.1, color='#30363d')
ax2.set_xlim(dates[0], dates[-1])

ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

plt.tight_layout()
fig2.savefig('/mnt/e/Hermes_workspace/stock_research/2.趋势判断/图2_概率趋势_状态迁移.png', dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close(fig2)
print("✅ 图2 已保存")

# 迁移汇总
print(f"\n=== 状态迁移汇总 ({len(transitions)}次) ===")
for idx, fs, ts, trig, pv in transitions:
    print(f"  {pd.Timestamp(dates[idx]).strftime('%Y-%m-%d'):<14} {sn[fs]:>8} → {sn[ts]:>8}  {trig:<12} 概率={pv:.0f}%")
