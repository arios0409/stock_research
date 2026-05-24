#!/usr/bin/env python3
"""KDJ(14,5,3) 概率趋势系统 — 图表绘制"""

import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import os

# ========== 字体 ==========
font_paths = ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']
for fp in font_paths:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False

# ========== 数据 ==========
TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260520")
df = df.sort_values("trade_date").reset_index(drop=True)
df["date"] = pd.to_datetime(df["trade_date"])

close = df["close"].values
high = df["high"].values
low = df["low"].values
dates = df["date"].values

N, M1, M2 = 14, 5, 3

# KDJ
k = np.full(len(close), np.nan, dtype=float)
d = np.full(len(close), np.nan, dtype=float)
j = np.full(len(close), np.nan, dtype=float)
for i in range(N - 1, len(close)):
    hh = np.max(high[i - N + 1:i + 1])
    ll = np.min(low[i - N + 1:i + 1])
    rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
    if np.isnan(k[i - 1]):
        k[i] = rsv
        d[i] = rsv
    else:
        k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
        d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2
    j[i] = 3 * k[i] - 2 * d[i]

# ========== 概率系统 ==========
p_up = np.full(len(close), np.nan, dtype=float)
p_down = np.full(len(close), np.nan, dtype=float)
p_risk = np.full(len(close), np.nan, dtype=float)
up_days = 0
down_days = 0
risk_days = 0

for i in range(N, len(close)):
    if np.isnan(k[i]) or np.isnan(d[i]):
        p_up[i] = 50; p_down[i] = 50; p_risk[i] = 50
        continue
    
    prev_up = p_up[i-1] if not np.isnan(p_up[i-1]) else 50
    prev_down = p_down[i-1] if not np.isnan(p_down[i-1]) else 50
    prev_risk = p_risk[i-1] if not np.isnan(p_risk[i-1]) else 50
    
    # 信号
    is_golden = False
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] <= d[i-1] and k[i] > d[i]:
            is_golden = True
    
    low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30
    
    is_death = False
    if not np.isnan(k[i-1]) and not np.isnan(d[i-1]):
        if k[i-1] >= d[i-1] and k[i] < d[i]:
            is_death = True
    
    high_death = is_death and k[i] >= 85
    in_down_zone = k[i] < 35 and d[i] < 40
    
    if k[i] > d[i]:
        up_days += 1
    else:
        up_days = 0
    if in_down_zone:
        down_days += 1
    else:
        down_days = 0
    if k[i] < d[i] and k[i] >= 85:
        risk_days += 1
    else:
        risk_days = 0
    
    # P_up
    if k[i] > d[i]:
        if is_golden and low_golden_bonus:
            p_up_val = 80
        elif is_golden:
            p_up_val = 60
        elif up_days >= 1:
            p_up_val = min(60 + up_days * 5, 92)
        else:
            p_up_val = min(prev_up + 3, 70)
    else:
        if is_death:
            p_up_val = 30
        elif k[i] < d[i]:
            decay = down_days * 8 if down_days > 0 else 3
            p_up_val = max(prev_up - decay, 10)
        else:
            p_up_val = max(prev_up - 5, 10)
    
    # P_down
    if in_down_zone:
        p_down_val = min(55 + down_days * 5, 88)
    elif k[i] < d[i] and k[i] < 50:
        p_down_val = min(45 + (50 - k[i]) * 1.5, 80)
    elif high_death:
        p_down_val = 50
    elif risk_days >= 1:
        p_down_val = min(50 + risk_days * 3, 70)
    elif is_golden:
        p_down_val = max(prev_down - 15, 10)
    else:
        p_down_val = max(prev_down - 2, 20)
    
    # P_risk
    if high_death:
        p_risk_val = 65
    elif risk_days >= 1 and k[i] < d[i]:
        p_risk_val = min(65 + risk_days * 5, 88)
    elif k[i] < d[i] and k[i] >= 75:
        p_risk_val = min(45 + (k[i] - 75) * 2, 65)
    elif in_down_zone:
        p_risk_val = max(prev_risk - 10, 10)
    elif is_golden:
        p_risk_val = max(prev_risk - 20, 5)
    else:
        p_risk_val = max(prev_risk - 2, 15)
    
    p_up[i] = round(p_up_val, 1)
    p_down[i] = round(p_down_val, 1)
    p_risk[i] = round(p_risk_val, 1)

# ========== 最终状态 ==========
final_state = np.full(len(close), "", dtype=object)
state_color = np.full(len(close), "", dtype=object)
for i in range(N, len(close)):
    if p_up[i] > p_risk[i] and p_up[i] > p_down[i]:
        final_state[i] = "↑上升"
        state_color[i] = "#3fb950"
    elif p_risk[i] > p_up[i] and p_risk[i] > p_down[i]:
        final_state[i] = "⚠风险"
        state_color[i] = "#d29922"
    elif p_down[i] > p_up[i] and p_down[i] > p_risk[i]:
        final_state[i] = "↓下降"
        state_color[i] = "#f85149"
    else:
        final_state[i] = "—"
        state_color[i] = "#8b949e"

# ========== 绘图 ==========
fig = plt.figure(figsize=(20, 16), facecolor='#0d1117')

# 日期索引（用于绘图）
date_idx = df["date"].values

# ===== 子图1：价格 + KDJ =====
ax1 = fig.add_subplot(3, 1, 1, facecolor='#161b22')
ax1.plot(date_idx, close, color='#e6edf3', linewidth=1.0, alpha=0.7, label='收盘价')
ax1.plot(date_idx, k, color='#f0883e', linewidth=1.0, alpha=0.8, label=f'K({M1})')
ax1.plot(date_idx, d, color='#58a6ff', linewidth=1.0, alpha=0.8, label=f'D({M2})')
ax1.plot(date_idx, j, color='#d2a8ff', linewidth=0.7, alpha=0.5, label='J')

# KDJ参考线
ax1.axhline(y=80, color='#f85149', linestyle='--', alpha=0.25, linewidth=0.7)
ax1.axhline(y=20, color='#3fb950', linestyle='--', alpha=0.25, linewidth=0.7)
ax1.axhline(y=35, color='#f0883e', linestyle=':', alpha=0.2, linewidth=0.5)
ax1.axhline(y=85, color='#d29922', linestyle=':', alpha=0.2, linewidth=0.5)

# 标注状态区间（用背景色）
state_regions = []
current_state = ""
start_idx = N
for i in range(N, len(close)):
    s = final_state[i]
    if s != current_state or i == len(close)-1:
        if current_state and current_state != "—":
            end_idx = i
            state_regions.append((start_idx, end_idx, current_state))
        current_state = s
        start_idx = i

for si, ei, st in state_regions:
    if st == "↑上升":
        ax1.axvspan(date_idx[si], date_idx[ei], alpha=0.06, color='#3fb950', zorder=0)
    elif st == "⚠风险":
        ax1.axvspan(date_idx[si], date_idx[ei], alpha=0.08, color='#d29922', zorder=0)
    elif st == "↓下降":
        ax1.axvspan(date_idx[si], date_idx[ei], alpha=0.08, color='#f85149', zorder=0)

ax1.set_title(f'上证指数 + KDJ({N},{M1},{M2}) 状态区间', fontsize=14, color='#e6edf3', fontweight='bold')
ax1.legend(loc='upper left', fontsize=8, facecolor='#0d1117', edgecolor='#30363d', labelcolor='#e6edf3')
ax1.set_ylabel('价格 / KDJ', color='#8b949e', fontsize=10)
ax1.tick_params(colors='#8b949e', labelsize=8)
ax1.grid(True, alpha=0.1, color='#30363d')
ax1.set_xlim(date_idx[0], date_idx[-1])

# ===== 子图2：概率曲线 =====
ax2 = fig.add_subplot(3, 1, 2, facecolor='#161b22')

ax2.plot(date_idx, p_up, color='#3fb950', linewidth=2.0, alpha=0.9, label='P_up 上涨概率')
ax2.plot(date_idx, p_down, color='#f85149', linewidth=2.0, alpha=0.9, label='P_down 下降概率')
ax2.plot(date_idx, p_risk, color='#d29922', linewidth=2.0, alpha=0.9, label='P_risk 风险概率')

# 60%买入线
ax2.axhline(y=60, color='#3fb950', linestyle='--', alpha=0.4, linewidth=0.8)
ax2.axhline(y=50, color='#8b949e', linestyle=':', alpha=0.3, linewidth=0.6)

# 填充买入区域
ax2.fill_between(date_idx[N:], 60, p_up[N:], alpha=0.1, color='#3fb950', 
                 where=(p_up[N:] >= 60), label='买入区(P_up≥60)')

# 同样标注状态区间
for si, ei, st in state_regions:
    if st == "↑上升":
        ax2.axvspan(date_idx[si], date_idx[ei], alpha=0.06, color='#3fb950', zorder=0)
    elif st == "⚠风险":
        ax2.axvspan(date_idx[si], date_idx[ei], alpha=0.08, color='#d29922', zorder=0)
    elif st == "↓下降":
        ax2.axvspan(date_idx[si], date_idx[ei], alpha=0.08, color='#f85149', zorder=0)

ax2.set_title('KDJ概率趋势系统 — P_up(绿) / P_risk(黄) / P_down(红)', fontsize=14, color='#e6edf3', fontweight='bold')
ax2.legend(loc='upper left', fontsize=8, facecolor='#0d1117', edgecolor='#30363d', labelcolor='#e6edf3')
ax2.set_ylabel('概率 %', color='#8b949e', fontsize=10)
ax2.set_ylim(0, 100)
ax2.tick_params(colors='#8b949e', labelsize=8)
ax2.grid(True, alpha=0.1, color='#30363d')
ax2.set_xlim(date_idx[0], date_idx[-1])

# 标记关键信号点
golden_dates = []
death_dates = []
for i in range(N, len(close)):
    if np.isnan(k[i]) or np.isnan(k[i-1]) or np.isnan(d[i]) or np.isnan(d[i-1]):
        continue
    if k[i-1] <= d[i-1] and k[i] > d[i]:
        ax2.scatter(date_idx[i], p_up[i], color='#3fb950', s=30, marker='^', zorder=5)
        golden_dates.append(i)
    if k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85:
        ax2.scatter(date_idx[i], p_risk[i], color='#d29922', s=30, marker='v', zorder=5)
        death_dates.append(i)

# ===== 子图3：成交量 =====
ax3 = fig.add_subplot(3, 1, 3, facecolor='#161b22')
colors_vol = ['#f85149' if close[i] >= df['open'].iloc[i] else '#3fb950' for i in range(len(df))]
ax3.bar(date_idx, df['vol'].values / 1e8, color=colors_vol, alpha=0.55, width=0.7)
ax3.set_title('成交量', fontsize=14, color='#e6edf3', fontweight='bold')
ax3.set_ylabel('成交量 (亿手)', color='#8b949e', fontsize=10)
ax3.tick_params(colors='#8b949e', labelsize=8)
ax3.grid(True, alpha=0.1, color='#30363d')
ax3.set_xlim(date_idx[0], date_idx[-1])

# 日期格式
for ax in [ax1, ax2, ax3]:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=7)

plt.tight_layout(pad=2.5)
output_path = '/mnt/e/Hermes_workspace/上证指数_概率趋势系统.png'
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print(f"✅ 图表已保存: {output_path}")
print(f"数据: {len(close)}个交易日, 状态切换{len(state_regions)}次")
