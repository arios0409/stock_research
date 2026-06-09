#!/usr/bin/env python3
"""
个股趋势扫描器 — 基于 KDJ(14,5,3) 概率趋势系统
仿大盘趋势扫描，用于单只个股上升/下降趋势检测

用法:
  cd /mnt/d/Hermes_workspace/stock_research
  source .venv/bin/activate
  python 5.Individual_stock_trend/stock_trend_scanner.py 300450.SZ
  python 5.Individual_stock_trend/stock_trend_scanner.py 300450.SZ --save-chart
  python 5.Individual_stock_trend/stock_trend_scanner.py 000858.SZ --start 20230101
"""

import sys, os, argparse
from datetime import datetime
import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator

# ===== 配置 =====
TUSHARE_TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===== 字体 =====
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False

# ===== KDJ 参数 =====
N, M1, M2 = 14, 5, 3


def fetch_stock_data(ts_code, start_date, end_date):
    """拉取个股日线数据"""
    pro = ts.pro_api(TUSHARE_TOKEN)
    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df.empty:
        raise ValueError(f"未获取到 {ts_code} 的数据")
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def get_stock_name(ts_code):
    """获取股票名称"""
    pro = ts.pro_api(TUSHARE_TOKEN)
    info = pro.stock_basic(ts_code=ts_code,
                           fields='ts_code,name,industry')
    if info.empty:
        return ts_code, "未知行业"
    return info.iloc[0]['name'], info.iloc[0].get('industry', '未知行业')


def compute_kdj(high, low, close):
    """计算 KDJ(14,5,3)"""
    k = np.full(len(close), np.nan, dtype=float)
    d = np.full(len(close), np.nan, dtype=float)

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
    return k, d


def compute_probability_system(close, high, low, k, d):
    """计算三概率系统 (P_up, P_down, P_risk) + 状态判定"""
    p_up = np.full(len(close), 50.0)
    p_down = np.full(len(close), 50.0)
    p_risk = np.full(len(close), 50.0)

    up_days = down_days = risk_days = 0

    for i in range(N, len(close)):
        prev_up = p_up[i - 1]
        prev_down = p_down[i - 1]
        prev_risk = p_risk[i - 1]

        # 信号检测
        is_golden = k[i - 1] <= d[i - 1] and k[i] > d[i]
        is_death = k[i - 1] >= d[i - 1] and k[i] < d[i]
        high_death = is_death and k[i] >= 85
        in_down_zone = k[i] < 35 and d[i] < 40
        low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30

        # 持续天数
        up_days = up_days + 1 if k[i] > d[i] else 0
        down_days = down_days + 1 if in_down_zone else 0
        risk_days = risk_days + 1 if (k[i] < d[i] and k[i] >= 85) else 0

        # === 上涨概率 P_up ===
        if k[i] > d[i]:
            if low_golden_bonus:
                p_up_val = 80
            elif is_golden:
                p_up_val = 60
            else:
                p_up_val = min(60 + up_days * 5, 92)
        else:
            if is_death:
                p_up_val = 30
            else:
                decay = down_days * 8 if down_days > 0 else 3
                p_up_val = max(prev_up - decay, 10)

        # === 下降概率 P_down ===
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

        # === 风险概率 P_risk ===
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

        p_up[i] = p_up_val
        p_down[i] = p_down_val
        p_risk[i] = p_risk_val

    # === 状态判定 ===
    state = np.full(len(close), 0, dtype=int)
    signal_triggers = {"金叉", "高位死叉", "K<35&D<40"}
    transitions = []
    prev_s = 0

    for i in range(N, len(close)):
        if p_up[i] > p_risk[i] and p_up[i] > p_down[i]:
            s = 1  # 上升
        elif p_risk[i] > p_up[i] and p_risk[i] > p_down[i]:
            s = 2  # 风险
        elif p_down[i] > p_up[i] and p_down[i] > p_risk[i]:
            s = 3  # 下降
        else:
            s = 0  # 震荡

        if s != prev_s and prev_s > 0 and s > 0:
            is_g = k[i - 1] <= d[i - 1] and k[i] > d[i]
            is_hd = k[i - 1] >= d[i - 1] and k[i] < d[i] and k[i] >= 85
            is_dz = k[i] < 35 and d[i] < 40
            trig = "金叉" if is_g else ("高位死叉" if is_hd else ("K<35&D<40" if is_dz else "概率切换"))
            if trig in signal_triggers:
                transitions.append((i, prev_s, s, trig))
        state[i] = s
        prev_s = s

    return p_up, p_down, p_risk, state, transitions


def generate_chart(dates, close, high, low, opens, vol,
                   k, d, p_up, p_down, p_risk, state, transitions,
                   stock_name, ts_code, save_path):
    """生成四子图趋势图表"""
    c_bg = '#0d1117'
    c_ax = '#161b22'
    c_up = '#00ff00'
    c_risk = '#ffff00'
    c_down = '#ff0000'
    c_price = '#ffffff'
    c_k = '#ff9900'
    c_d = '#33ddff'
    c_j = '#dd88ff'
    c_grid = '#333333'
    c_label = '#dddddd'

    sn = {0: "—", 1: "↑上升", 2: "△风险", 3: "↓下降"}
    sc = {0: c_label, 1: c_up, 2: c_risk, 3: c_down}

    # 近4月放大
    M4_DAYS = 80
    m4_start = max(N, len(close) - M4_DAYS)
    d4 = dates[m4_start:]
    c4 = close[m4_start:]
    st4 = state[m4_start:]
    pu4 = p_up[m4_start:]
    pd4 = p_down[m4_start:]
    pr4 = p_risk[m4_start:]
    t4 = [(idx, fs, ts, trig) for idx, fs, ts, trig in transitions if idx >= m4_start]

    fig = plt.figure(figsize=(20, 14), facecolor=c_bg)
    ax1 = fig.add_axes([0.07, 0.58, 0.90, 0.42], facecolor=c_ax)
    ax2 = fig.add_axes([0.07, 0.40, 0.90, 0.16], facecolor=c_ax)
    ax3 = fig.add_axes([0.07, 0.22, 0.90, 0.16], facecolor=c_ax)
    ax4 = fig.add_axes([0.07, 0.02, 0.90, 0.18], facecolor=c_ax)

    DATE_FMT = lambda: mdates.DateFormatter('Y%yM%m')

    def draw_state_spans(ax, dates_arr, close_arr, state_arr,
                         p_up_arr, p_down_arr, p_risk_arr,
                         show_label=True, y_label_top=0):
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
                    ax.axvspan(dates_arr[idx], dates_arr[idx + 1],
                               alpha=alpha, color=sc[s], linewidth=0, zorder=0)

            if show_label and y_label_top:
                avg_p = np.mean(
                    p_up_arr[i:j] if s == 1 else
                    (p_risk_arr[i:j] if s == 2 else p_down_arr[i:j])
                )
                mid = i + (j - i) // 2
                if mid < len(close_arr):
                    ax.text(dates_arr[mid], y_label_top,
                            f"{sn[s]} {avg_p:.0f}%",
                            color=sc[s], fontsize=9, fontweight='bold',
                            ha='center', va='top',
                            bbox=dict(boxstyle='round,pad=0.2',
                                      facecolor=c_bg, edgecolor=sc[s], alpha=0.85))
            i = j

    # === 子图1: 全量K线 + 状态区间 ===
    y1_min, y1_max = np.min(close), np.max(close)
    y1_range = y1_max - y1_min
    ax1_top = y1_max + y1_range * 0.065
    ax1_lim = y1_max + y1_range * 0.15
    ax1_bot = y1_min - y1_range * 0.10
    draw_state_spans(ax1, dates, close, state, p_up, p_down, p_risk,
                     show_label=True, y_label_top=ax1_top)
    ax1.set_ylim(ax1_bot, ax1_lim)
    ax1.set_ylabel(f'{stock_name}({ts_code})', color=c_label, fontsize=18)
    ax1.tick_params(colors=c_label, labelsize=14)
    ax1.grid(True, alpha=0.08, color=c_grid)
    ax1.set_xlim(dates[0], dates[-1])
    ax1.set_xticklabels([])

    # === 子图2: KDJ ===
    ax2.plot(dates, k, color=c_k, linewidth=1.5, alpha=0.9)
    ax2.plot(dates, d, color=c_d, linewidth=1.5, alpha=0.9)
    ax2.plot(dates, 3 * k - 2 * d, color=c_j, linewidth=0.8, alpha=0.5)
    ax2.axhline(y=85, color=c_risk, linestyle='--', alpha=0.4, linewidth=1.0)
    ax2.axhline(y=35, color=c_down, linestyle='--', alpha=0.4, linewidth=1.0)
    ax2.text(dates[-1], 86, '超买85', color='#ffee00', fontsize=8, alpha=0.6)
    ax2.text(dates[-1], 33, '危险35', color=c_down, fontsize=8, alpha=0.6)

    for idx, fs, ts, trig in transitions:
        y_k = k[idx]
        if trig == "金叉":
            ax2.scatter(dates[idx], y_k, color=c_up, s=60, marker='^',
                        zorder=6, edgecolors='white', linewidth=0.8)
            ax2.annotate('金叉', xy=(dates[idx], y_k),
                         xytext=(dates[idx], y_k + 20),
                         fontsize=8, color=c_up, fontweight='bold', ha='center',
                         arrowprops=dict(arrowstyle='->', color=c_up, lw=1.5),
                         bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg,
                                   edgecolor=c_up, alpha=0.9))
        elif trig == "高位死叉":
            ax2.scatter(dates[idx], y_k, color=c_risk, s=60, marker='v',
                        zorder=6, edgecolors='white', linewidth=0.8)
            ax2.annotate('高位死叉', xy=(dates[idx], y_k),
                         xytext=(dates[idx], y_k - 22),
                         fontsize=8, color=c_risk, fontweight='bold',
                         ha='center', va='top',
                         arrowprops=dict(arrowstyle='->', color=c_risk, lw=1.5),
                         bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg,
                                   edgecolor=c_risk, alpha=0.9))
        elif trig == "K<35&D<40":
            ax2.scatter(dates[idx], y_k, color=c_down, s=60, marker='s',
                        zorder=6, edgecolors='white', linewidth=0.8)
            ax2.annotate('K<35&D<40', xy=(dates[idx], y_k),
                         xytext=(dates[idx], y_k - 22),
                         fontsize=8, color=c_down, fontweight='bold',
                         ha='center', va='top',
                         arrowprops=dict(arrowstyle='->', color=c_down, lw=1.5),
                         bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg,
                                   edgecolor=c_down, alpha=0.9))

    ax2.set_ylabel('KDJ', color=c_label, fontsize=16)
    ax2.tick_params(colors=c_label, labelsize=12)
    ax2.grid(True, alpha=0.12, color=c_grid)
    ax2.set_ylim(-10, 115)
    ax2.set_xlim(dates[0], dates[-1])
    ax2.set_xticklabels([])

    # === 子图3: 成交量 ===
    vol_colors = [c_up if close[i] >= opens[i] else c_down
                  for i in range(len(close))]
    ax3.bar(dates, vol / 1e6, color=vol_colors, alpha=0.6, width=0.7)
    ax3.set_ylabel('成交量(百万手)', color=c_label, fontsize=16)
    ax3.tick_params(colors=c_label, labelsize=12)
    ax3.grid(True, alpha=0.1, color=c_grid)
    ax3.set_xlim(dates[0], dates[-1])
    ax3.xaxis.set_major_formatter(DATE_FMT())
    ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax3.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
    ax3.tick_params(which='minor', colors=c_label, length=3)
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=0, ha='center',
             fontsize=12, color=c_label)

    for ax in [ax1, ax2]:
        ax.set_xlim(dates[0], dates[-1])
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        ax.xaxis.set_major_formatter(DATE_FMT())
        ax.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
        ax.tick_params(which='minor', colors=c_label, length=3)

    # === 子图4: 近4月放大 ===
    draw_state_spans(ax4, d4, c4, st4, pu4, pd4, pr4,
                     show_label=True,
                     y_label_top=np.max(c4) + (np.max(c4) - np.min(c4)) * 0.06)
    y_min, y_max = np.min(c4), np.max(c4)
    y_rng = y_max - y_min
    ax4.set_ylim(y_min - y_rng * 0.10, y_max + y_rng * 0.10)
    ax4.set_ylabel('近4月放大', color=c_label, fontsize=15)
    ax4.tick_params(colors=c_label, labelsize=12)
    ax4.grid(True, alpha=0.08, color=c_grid)
    ax4.set_xlim(d4[0], d4[-1])
    ax4.xaxis.set_major_formatter(DATE_FMT())
    ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax4.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
    ax4.tick_params(which='minor', colors=c_label, length=3)
    plt.setp(ax4.xaxis.get_majorticklabels(), rotation=0, ha='center',
             fontsize=12, color=c_label)

    fig.savefig(save_path, dpi=150, facecolor=c_bg)
    plt.close(fig)
    return save_path


def print_analysis(name, ts_code, industry, dates, close, k, d,
                   p_up, p_down, p_risk, state, transitions):
    """打印分析报告"""
    last_idx = len(close) - 1
    cur_k = k[last_idx]
    cur_d = d[last_idx]
    cur_pu = p_up[last_idx]
    cur_pd = p_down[last_idx]
    cur_pr = p_risk[last_idx]

    sn = {0: "—震荡", 1: "↑上升", 2: "△风险", 3: "↓下降"}
    cur_state = sn[state[last_idx]]

    # 建议文字
    cur_s = state[last_idx]
    if cur_s == 3:
        if cur_pd >= 60:
            advice = "下降趋势明确，回避为主，等待底部信号"
        elif cur_pd >= 50:
            advice = "下降趋势概率偏高，轻仓或观望"
        else:
            advice = "下降动能减弱，关注是否企稳反弹"
    elif cur_s == 1:
        if cur_pu >= 75:
            advice = f"强上升趋势，上升概率{cur_pu:.0f}%，可积极参与"
        elif cur_pu >= 60:
            advice = f"上升趋势确立，上升概率{cur_pu:.0f}%，可考虑入场"
        else:
            advice = "上升信号初现但强度不足，轻仓试探"
    elif cur_s == 2:
        if cur_k >= 80:
            advice = "高位风险积聚，建议减仓观望"
        else:
            advice = "震荡偏风险，方向不明，观望为主"
    else:
        advice = "方向不明，观望为主"

    # 近5日趋势
    recent_5 = min(5, len(close))
    close_5d = close[-recent_5:]
    chg_5d = (close_5d[-1] - close_5d[0]) / close_5d[0] * 100

    # 近20日趋势
    recent_20 = min(20, len(close))
    close_20d = close[-recent_20:]
    chg_20d = (close_20d[-1] - close_20d[0]) / close_20d[0] * 100

    print()
    print("=" * 70)
    print(f"  {name}({ts_code})  KDJ(14,5,3) 概率趋势系统")
    print(f"  行业: {industry}")
    print("=" * 70)
    print(f"  最新交易日: {pd.Timestamp(dates[-1]).strftime('%Y-%m-%d')}")
    print(f"  收盘价: {close[-1]:.2f}")
    print(f"  当前状态: {cur_state}")
    print(f"  上升概率: {cur_pu:.0f}%  |  下跌概率: {cur_pd:.0f}%  |  震荡概率: {cur_pr:.0f}%")
    print(f"  K={cur_k:.1f}  D={cur_d:.1f}  J={3*cur_k-2*cur_d:.1f}")
    print(f"  近5日涨跌: {chg_5d:+.2f}%  |  近20日涨跌: {chg_20d:+.2f}%")
    print(f"  建议: {advice}")
    print("-" * 70)

    # KDJ 位置判断
    if cur_k > 80:
        print("  ⚡ K值>80 超买区，短期回调风险较高")
    elif cur_k < 20:
        print("  💡 K值<20 超卖区，短期反弹概率较高")
    if cur_k > cur_d:
        print("  ✅ K>D 多头排列，短期偏多")
    else:
        print("  ❌ K<D 空头排列，短期偏空")

    # 最近信号
    if transitions:
        last_sig = transitions[-1]
        sig_date = pd.Timestamp(dates[last_sig[0]]).strftime('%Y-%m-%d')
        sn_map = {0: "—", 1: "↑上升", 2: "△风险", 3: "↓下降"}
        print(f"\n  最近信号: [{sig_date}] {last_sig[3]} "
              f"({sn_map[last_sig[1]]} → {sn_map[last_sig[2]]})")

    # 近期状态分布
    total_days = len(close) - N
    up_days = np.sum(state[N:] == 1)
    risk_days = np.sum(state[N:] == 2)
    down_days = np.sum(state[N:] == 3)
    osc_days = np.sum(state[N:] == 0)
    print(f"\n  状态分布(自计算起始): "
          f"↑上升 {up_days/total_days*100:.0f}%  "
          f"△风险 {risk_days/total_days*100:.0f}%  "
          f"↓下降 {down_days/total_days*100:.0f}%  "
          f"—震荡 {osc_days/total_days*100:.0f}%")

    # 快速回测: P_up≥60 买入，3日/5日胜率
    print(f"\n  快速回测 (P_up≥60 买入):")
    buy_signals = []
    in_trade = False
    for i in range(N, len(close)):
        if p_up[i] >= 60 and not in_trade:
            buy_signals.append(i)
            in_trade = True
        if p_up[i] < 50:
            in_trade = False

    if buy_signals:
        w3 = sum(1 for idx in buy_signals
                 if idx + 3 < len(close) and close[idx + 3] > close[idx])
        w5 = sum(1 for idx in buy_signals
                 if idx + 5 < len(close) and close[idx + 5] > close[idx])
        t3 = sum(1 for idx in buy_signals if idx + 3 < len(close))
        t5 = sum(1 for idx in buy_signals if idx + 5 < len(close))
        print(f"  买入信号: {len(buy_signals)}次  "
              f"+3d胜率={w3}/{t3}={w3/t3*100:.1f}%  "
              f"+5d胜率={w5}/{t5}={w5/t5*100:.1f}%")
    else:
        print(f"  买入信号: 0次")

    # P_down≥55 卖出信号
    sell_signals = []
    in_sell = False
    for i in range(N, len(close)):
        if p_down[i] >= 55 and not in_sell:
            sell_signals.append(i)
            in_sell = True
        if p_down[i] < 45:
            in_sell = False

    if sell_signals:
        w3 = sum(1 for idx in sell_signals
                 if idx + 3 < len(close) and close[idx + 3] < close[idx])
        t3 = sum(1 for idx in sell_signals if idx + 3 < len(close))
        print(f"  卖出信号(P_down≥55): {len(sell_signals)}次  "
              f"+3d下跌胜率={w3}/{t3}={w3/t3*100:.1f}%")
    else:
        print(f"  卖出信号(P_down≥55): 0次")

    print("=" * 70)

    return advice


def main():
    parser = argparse.ArgumentParser(
        description='个股KDJ概率趋势扫描器')
    parser.add_argument('code', nargs='?', default='300450.SZ',
                        help='股票代码 (默认: 300450.SZ 先导智能)')
    parser.add_argument('--start', default='20240801',
                        help='起始日期 YYYYMMDD (默认: 20240801)')
    parser.add_argument('--save-chart', action='store_true',
                        help='保存图表到 output/ 目录')
    parser.add_argument('--no-chart', action='store_true',
                        help='不生成图表')
    args = parser.parse_args()

    ts_code = args.code.upper()
    if '.' not in ts_code:
        # 自动补全后缀: 6开头→SH, 0/3开头→SZ
        if ts_code.startswith('6'):
            ts_code += '.SH'
        else:
            ts_code += '.SZ'

    end_date = datetime.now().strftime('%Y%m%d')

    # 1. 获取股票名称
    print(f"查询 {ts_code} ...")
    name, industry = get_stock_name(ts_code)
    print(f"  股票: {name}  行业: {industry}")

    # 2. 拉取数据
    print(f"拉取日线数据 ({args.start} ~ {end_date}) ...")
    df = fetch_stock_data(ts_code, args.start, end_date)
    print(f"  获取 {len(df)} 条记录，最新: {df['trade_date'].iloc[-1]}")

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    opens = df["open"].values
    vol = df["vol"].values
    dates = pd.to_datetime(df["trade_date"]).values

    # 3. KDJ
    print("计算 KDJ(14,5,3) ...")
    k, d = compute_kdj(high, low, close)

    # 4. 概率系统
    print("计算概率趋势系统 ...")
    p_up, p_down, p_risk, state, transitions = \
        compute_probability_system(close, high, low, k, d)

    # 5. 输出分析
    advice = print_analysis(name, ts_code, industry,
                            dates, close, k, d,
                            p_up, p_down, p_risk, state, transitions)

    # 6. 图表
    if not args.no_chart:
        chart_name = f"{ts_code.replace('.', '_')}_{end_date}_趋势图.png"
        chart_path = os.path.join(OUTPUT_DIR, chart_name) if args.save_chart \
            else os.path.join(OUTPUT_DIR, chart_name)
        print(f"\n生成图表 ...")
        generate_chart(dates, close, high, low, opens, vol,
                       k, d, p_up, p_down, p_risk, state, transitions,
                       name, ts_code, chart_path)
        print(f"  图表已保存: {chart_path}")

    # 7. 返回状态码 (供脚本调用)
    cur_s = state[len(close) - 1]
    return cur_s


if __name__ == '__main__':
    sys.exit(main())
