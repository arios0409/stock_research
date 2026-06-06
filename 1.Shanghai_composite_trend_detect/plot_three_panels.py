#!/usr/bin/env python3
"""三子图：1.上证指数+状态区间(60%) 2.KDJ+信号标记(25%) 3.成交量(15%)"""

import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.ticker import FixedLocator, MultipleLocator
import os

# 字体
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf','/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif',[])
plt.rcParams['axes.unicode_minus'] = False

# ===== 数据 =====
TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)
df = pro.index_daily(ts_code="000001.SH", start_date="20240801", end_date="20260601")
df = df.sort_values("trade_date").reset_index(drop=True)
close = df["close"].values; high = df["high"].values; low = df["low"].values
opens = df["open"].values; vol = df["vol"].values
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
transitions = []  # (idx, from_state, to_state, trigger)

for i in range(N, len(close)):
    prev_up = p_up[i-1]; prev_down = p_down[i-1]; prev_risk = p_risk[i-1]
    is_golden = k[i-1] <= d[i-1] and k[i] > d[i]
    is_death = k[i-1] >= d[i-1] and k[i] < d[i]
    high_death = is_death and k[i] >= 85
    in_down_zone = k[i] < 35 and d[i] < 40
    low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30
    
    up_days = up_days+1 if k[i] > d[i] else 0
    down_days = down_days+1 if in_down_zone else 0
    risk_days = risk_days+1 if (k[i] < d[i] and k[i] >= 85) else 0
    
    if k[i] > d[i]:
        p_up_val = 80 if low_golden_bonus else (60 if is_golden else min(60+up_days*5,92))
    else:
        p_up_val = 30 if is_death else max(prev_up-(down_days*8 if down_days>0 else 3), 10)
    
    if in_down_zone: p_down_val = min(55+down_days*5, 88)
    elif k[i] < d[i] and k[i] < 50: p_down_val = min(45+(50-k[i])*1.5, 80)
    elif high_death: p_down_val = 50
    elif risk_days >= 1: p_down_val = min(50+risk_days*3, 70)
    elif is_golden: p_down_val = max(prev_down-15, 10)
    else: p_down_val = max(prev_down-2, 20)
    
    if high_death: p_risk_val = 65
    elif risk_days >= 1 and k[i] < d[i]: p_risk_val = min(65+risk_days*5, 88)
    elif k[i] < d[i] and k[i] >= 75: p_risk_val = min(45+(k[i]-75)*2, 65)
    elif in_down_zone: p_risk_val = max(prev_risk-10, 10)
    elif is_golden: p_risk_val = max(prev_risk-20, 5)
    else: p_risk_val = max(prev_risk-2, 15)
    
    p_up[i]=p_up_val; p_down[i]=p_down_val; p_risk[i]=p_risk_val

# ===== 状态判定 + 迁移记录 =====
state = np.full(len(close), 0, dtype=int)
prev_s = 0
signal_triggers = {"金叉", "高位死叉", "K<35&D<40"}

for i in range(N, len(close)):
    s = 1 if (p_up[i] > p_risk[i] and p_up[i] > p_down[i]) else \
        2 if (p_risk[i] > p_up[i] and p_risk[i] > p_down[i]) else \
        3 if (p_down[i] > p_up[i] and p_down[i] > p_risk[i]) else 0
    
    if s != prev_s and prev_s > 0 and s > 0:
        is_g = k[i-1] <= d[i-1] and k[i] > d[i] if not np.isnan(k[i]) and not np.isnan(d[i-1]) else False
        is_hd = (k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85) if not np.isnan(k[i]) else False
        is_dz = k[i] < 35 and d[i] < 40
        trig = "金叉" if is_g else ("高位死叉" if is_hd else ("K<35&D<40" if is_dz else "概率切换"))
        if trig in signal_triggers:
            transitions.append((i, prev_s, s, trig))
    
    state[i] = s
    prev_s = s

# ===== 高对比度配色 =====
c_bg = '#0d1117'
c_ax = '#161b22'
c_up = '#00ff00'      # 纯绿
c_risk = '#ffff00'    # 纯黄
c_down = '#ff0000'    # 纯红
c_price = '#ffffff'
c_k = '#ff9900'       # K线橙
c_d = '#33ddff'       # D线亮蓝
c_j = '#dd88ff'       # J线亮紫
c_grid = '#333333'
c_label = '#dddddd'

sn = {0:"—", 1:"↑上升", 2:"⚠风险", 3:"↓下降"}
sc = {0:c_label, 1:c_up, 2:c_risk, 3:c_down}

# 子图2用：最近4个月切片（约80个交易日）
M4_DAYS = 80
m4_start = max(N, len(close) - M4_DAYS)
d4 = dates[m4_start:]
c4 = close[m4_start:]
st4 = state[m4_start:]
pu4 = p_up[m4_start:]
pd4 = p_down[m4_start:]
pr4 = p_risk[m4_start:]

# 过滤子图2范围内的信号
t4 = [(idx, fs, ts, trig) for idx, fs, ts, trig in transitions
      if idx >= m4_start]

# ========================================================
# 四子图
# ========================================================
fig = plt.figure(figsize=(20, 14), facecolor=c_bg)

# 坐标轴 [left, bottom, width, height] — 同时间轴的放一起
ax1 = fig.add_axes([0.07, 0.58, 0.90, 0.42], facecolor=c_ax)  # 42% 上证全量
ax2 = fig.add_axes([0.07, 0.40, 0.90, 0.16], facecolor=c_ax)  # 16% KDJ
ax3 = fig.add_axes([0.07, 0.22, 0.90, 0.16], facecolor=c_ax)  # 16% 成交量
ax4 = fig.add_axes([0.07, 0.02, 0.90, 0.18], facecolor=c_ax)  # 18% 上证4月放大

# ---- 通用日期格式 ----
DATE_FMT = lambda: mdates.DateFormatter('Y%yM%m')  # Y25M06

# ---- 状态区间绘制函数（通用） ----
def draw_state_spans(ax, dates_arr, close_arr, state_arr, p_up_arr, p_down_arr, p_risk_arr,
                     show_label=True, y_label_top=0):
    """在指定axes上绘制状态区间背景"""
    ax.plot(dates_arr, close_arr, color=c_price, linewidth=1.6, alpha=0.95)
    i = 0
    while i < len(close_arr):
        if state_arr[i] == 0:
            i += 1
            continue
        s = state_arr[i]
        j = i
        while j < len(close_arr) and state_arr[j] == s:
            j += 1

        for idx in range(i, j):
            if s == 1:
                p_val = p_up_arr[idx]
                alpha = 0.10 + (p_val - 55) / 37 * 0.38 if p_val > 55 else 0.06
            elif s == 2:
                p_val = p_risk_arr[idx]
                alpha = 0.10 + (p_val - 50) / 38 * 0.38 if p_val > 50 else 0.06
            elif s == 3:
                p_val = p_down_arr[idx]
                alpha = 0.10 + (p_val - 50) / 38 * 0.38 if p_val > 50 else 0.06
            alpha = max(0.06, min(0.55, alpha))
            if idx < len(close_arr) - 1:
                ax.axvspan(dates_arr[idx], dates_arr[idx+1], alpha=alpha, color=sc[s],
                           linewidth=0, zorder=0)
            else:
                ax.axvspan(dates_arr[idx], dates_arr[idx], alpha=alpha, color=sc[s],
                           linewidth=0, zorder=0)

        # 标签
        if show_label and y_label_top:
            avg_p = np.mean(p_up_arr[i:j] if s == 1 else (p_risk_arr[i:j] if s == 2 else p_down_arr[i:j]))
            mid = i + (j - i) // 2
            if mid < len(close_arr):
                prob_text = f"{avg_p:.0f}%"
                ax.text(dates_arr[mid], y_label_top, f"{sn[s]} {prob_text}", color=sc[s], fontsize=9,
                        fontweight='bold', ha='center', va='top',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor=c_bg, edgecolor=sc[s], alpha=0.85))
        i = j

# ===== 子图1：上证指数 + 状态区间 (全量) =====
y1_min, y1_max = np.min(close), np.max(close)
y1_range = y1_max - y1_min
ax1_top = y1_max + y1_range * 0.065   # 标签位置（数据顶+6.5%）
ax1_lim = y1_max + y1_range * 0.15    # y轴顶（数据顶+15%）
ax1_bot = y1_min - y1_range * 0.10    # y轴底（数据底-10%）
draw_state_spans(ax1, dates, close, state, p_up, p_down, p_risk,
                 show_label=True, y_label_top=ax1_top)
ax1.set_ylim(ax1_bot, ax1_lim)
ax1.set_ylabel('上证指数', color=c_label, fontsize=20)
ax1.tick_params(colors=c_label, labelsize=14)
ax1.yaxis.set_minor_locator(MultipleLocator(100))
ax1.tick_params(which='minor', colors=c_label, length=3)
ax1.grid(True, alpha=0.08, color=c_grid)
ax1.set_xlim(dates[0], dates[-1])
ax1.set_xticklabels([])

# ===== 子图2：KDJ + 信号标记 (全量) =====
ax2.plot(dates, k, color=c_k, linewidth=1.5, alpha=0.9, label=f'K({M1})')
ax2.plot(dates, d, color=c_d, linewidth=1.5, alpha=0.9, label=f'D({M2})')
ax2.plot(dates, 3*k-2*d, color=c_j, linewidth=0.8, alpha=0.5, label='J')
ax2.axhline(y=85, color=c_risk, linestyle='--', alpha=0.4, linewidth=1.0)
ax2.axhline(y=35, color=c_down, linestyle='--', alpha=0.4, linewidth=1.0)
ax2.axhline(y=20, color=c_up, linestyle=':', alpha=0.3, linewidth=0.8)
ax2.axhline(y=80, color=c_risk, linestyle=':', alpha=0.3, linewidth=0.8)
ax2.text(dates[-1], 86, '超买85', color='#ffee00', fontsize=8, alpha=0.6)
ax2.text(dates[-1], 33, '危险35', color=c_down, fontsize=8, alpha=0.6)

for idx, fs, ts, trig in transitions:
    y_k = k[idx]
    if trig == "金叉":
        ax2.scatter(dates[idx], y_k, color=c_up, s=60, marker='^', zorder=6, edgecolors='white', linewidth=0.8)
        ax2.annotate('金叉', xy=(dates[idx], y_k), xytext=(dates[idx], y_k + 20),
                    fontsize=8, color=c_up, fontweight='bold', ha='center',
                    arrowprops=dict(arrowstyle='->', color=c_up, lw=1.5),
                    bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg, edgecolor=c_up, alpha=0.9))
    elif trig == "高位死叉":
        ax2.scatter(dates[idx], y_k, color=c_risk, s=60, marker='v', zorder=6, edgecolors='white', linewidth=0.8)
        ax2.annotate('高位死叉', xy=(dates[idx], y_k), xytext=(dates[idx], y_k - 22),
                    fontsize=8, color=c_risk, fontweight='bold', ha='center', va='top',
                    arrowprops=dict(arrowstyle='->', color=c_risk, lw=1.5),
                    bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg, edgecolor=c_risk, alpha=0.9))
    elif trig == "K<35&D<40":
        ax2.scatter(dates[idx], y_k, color=c_down, s=60, marker='s', zorder=6, edgecolors='white', linewidth=0.8)
        ax2.annotate('K<35&D<40', xy=(dates[idx], y_k), xytext=(dates[idx], y_k - 22),
                    fontsize=8, color=c_down, fontweight='bold', ha='center', va='top',
                    arrowprops=dict(arrowstyle='->', color=c_down, lw=1.5),
                    bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg, edgecolor=c_down, alpha=0.9))

ax2.set_ylabel('KDJ', color=c_label, fontsize=16)
ax2.tick_params(colors=c_label, labelsize=12)
ax2.grid(True, alpha=0.12, color=c_grid)
ax2.set_ylim(-10, 115)
ax2.set_xlim(dates[0], dates[-1])
ax2.set_xticklabels([])
ax2.legend(loc='upper left', fontsize=9, facecolor=c_bg, edgecolor=c_grid, labelcolor=c_label)

# ===== 子图3：成交量 (全量) =====
vol_colors = [c_down if close[i] >= opens[i] else c_up for i in range(len(close))]
ax3.bar(dates, vol/1e8, color=vol_colors, alpha=0.6, width=0.7)
ax3.set_ylabel('成交量(亿手)', color=c_label, fontsize=16)
ax3.tick_params(colors=c_label, labelsize=12)
ax3.grid(True, alpha=0.1, color=c_grid)
ax3.set_xlim(dates[0], dates[-1])

# 子图3显示共享时间轴 + 5日刻度
ax3.xaxis.set_major_formatter(DATE_FMT())
ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
ax3.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
ax3.tick_params(which='minor', colors=c_label, length=3)
plt.setp(ax3.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=12, color=c_label)

# 对齐全量子图X轴
for ax in [ax1, ax2]:
    ax.set_xlim(dates[0], dates[-1])
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(DATE_FMT())
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
    ax.tick_params(which='minor', colors=c_label, length=3)
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=12, color=c_label)

# ===== 子图4：上证指数近4月放大 (独立时间轴) =====
draw_state_spans(ax4, d4, c4, st4, pu4, pd4, pr4,
                 show_label=True, y_label_top=np.max(c4) + (np.max(c4)-np.min(c4)) * 0.06)
y_min, y_max = np.min(c4), np.max(c4)
y_rng = y_max - y_min
ax4.set_ylim(y_min - y_rng * 0.10, y_max + y_rng * 0.10)
ax4.set_ylabel('上证指数(近4月)', color=c_label, fontsize=15)
ax4.tick_params(colors=c_label, labelsize=12)
ax4.grid(True, alpha=0.08, color=c_grid)
ax4.set_xlim(d4[0], d4[-1])
ax4.xaxis.set_major_formatter(DATE_FMT())
ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
ax4.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
ax4.tick_params(which='minor', colors=c_label, length=3)
plt.setp(ax4.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=12, color=c_label)

last_date = str(df['trade_date'].iloc[-1])
output_path = f'/mnt/d/Hermes_workspace/stock_research/1.Shanghai_composite_trend_detect/{last_date}_三子图_高对比.png'
fig.savefig(output_path, dpi=150, facecolor=c_bg)
plt.close(fig)
print(f"✅ 已保存: {output_path}")

# 信号汇总
print(f"\n=== 信号标记 ({len(transitions)}次) ===")
for idx, fs, ts, trig in transitions:
    print(f"  {pd.Timestamp(dates[idx]).strftime('%Y-%m-%d'):<14} {sn[fs]:>8} → {sn[ts]:>8}  {trig}")
