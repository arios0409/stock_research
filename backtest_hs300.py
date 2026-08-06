#!/usr/bin/env python3
"""沪深300 KDJ概率系统 V3 回测 (2022-2026)"""
import numpy as np
import tushare as ts
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates

TUSHARE_TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
INDEX_CODE = "000300.SH"
START_DATE = "20220101"

# 字体
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
    import os
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False

# ===== 1. 获取数据 =====
print("拉取沪深300数据 2022-2026...")
pro = ts.pro_api(TUSHARE_TOKEN)
from datetime import datetime
end_date = "20260626"  # latest
df_raw = pro.index_daily(ts_code=INDEX_CODE, start_date=START_DATE, end_date=end_date)
df_raw = df_raw.sort_values("trade_date").reset_index(drop=True)
print(f"获取到 {len(df_raw)} 条数据，{df_raw['trade_date'].iloc[0]} ~ {df_raw['trade_date'].iloc[-1]}")

close = df_raw["close"].values
high = df_raw["high"].values
low = df_raw["low"].values
opens = df_raw["open"].values
vol = df_raw["vol"].values
dates_raw = df_raw["trade_date"].values
dates_dt = [datetime.strptime(d, '%Y%m%d') for d in dates_raw]
N, M1, M2 = 14, 5, 3

# ===== 2. KDJ =====
k = np.full(len(close), np.nan, dtype=float)
d = np.full(len(close), np.nan, dtype=float)
for i in range(N - 1, len(close)):
    hh = np.max(high[i - N + 1:i + 1])
    ll = np.min(low[i - N + 1:i + 1])
    rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
    if np.isnan(k[i - 1]):
        k[i] = rsv; d[i] = rsv
    else:
        k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
        d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2

# ===== 3. 指标 =====
def ema(data, span):
    result = np.full(len(data), np.nan, dtype=float)
    k_ema = 2.0 / (span + 1)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] * k_ema + result[i-1] * (1 - k_ema)
    return result

ema12 = ema(close, 12); ema26 = ema(close, 26)
dif = ema12 - ema26; dea = ema(dif, 9)

macd_bullish = np.zeros(len(close), dtype=bool)
macd_bearish = np.zeros(len(close), dtype=bool)
for i in range(1, len(close)):
    if not np.isnan(dif[i]) and not np.isnan(dif[i-1]):
        macd_bullish[i] = (dif[i-1] <= dea[i-1]) and (dif[i] > dea[i])
        macd_bearish[i] = (dif[i-1] >= dea[i-1]) and (dif[i] < dea[i])

macd_trend = np.zeros(len(close), dtype=float)
for i in range(len(close)):
    if not np.isnan(dif[i]) and not np.isnan(dea[i]):
        if dif[i] > dea[i] and (i == 0 or dif[i] > dif[i-1]): macd_trend[i] = 1.0
        elif dif[i] > dea[i]: macd_trend[i] = 0.5
        elif dif[i] < dea[i] and (i == 0 or dif[i] < dif[i-1]): macd_trend[i] = -1.0
        else: macd_trend[i] = -0.5

vol_ma20 = np.full(len(close), np.nan, dtype=float)
for i in range(19, len(close)):
    vol_ma20[i] = np.mean(vol[i - 19:i + 1])
vol_ma5 = np.full(len(close), np.nan, dtype=float)
for i in range(4, len(close)):
    vol_ma5[i] = np.mean(vol[i - 4:i + 1])

vol_ratio = np.full(len(close), 1.0)
for i in range(len(close)):
    if not np.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
        vol_ratio[i] = vol[i] / vol_ma20[i]

vol_divergence = np.zeros(len(close), dtype=float)
for i in range(20, len(close)):
    price_high_20 = np.max(close[i - 19:i])
    if close[i] >= price_high_20 * 0.995:
        recent_vol_max = np.max(vol[i - 19:i])
        if recent_vol_max > 0 and vol[i] < recent_vol_max * 0.65: vol_divergence[i] = 1.0
    price_low_20 = np.min(close[i - 19:i])
    if close[i] <= price_low_20 * 1.005:
        recent_vol_avg = np.mean(vol[i - 19:i])
        if recent_vol_avg > 0 and vol[i] < recent_vol_avg * 0.6: vol_divergence[i] = -1.0

vol_trend = np.full(len(close), 0.0)
for i in range(len(close)):
    if not np.isnan(vol_ma5[i]) and not np.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
        vol_trend[i] = (vol_ma5[i] / vol_ma20[i]) - 1.0

# ===== 4. V3 概率 + 状态 (同扫描器逻辑) =====
p_up = np.full(len(close), 50.0); p_down = np.full(len(close), 50.0); p_risk = np.full(len(close), 50.0)
up_days = down_days = risk_days = 0

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

    vr = vol_ratio[i]; vt = vol_trend[i]; vd = vol_divergence[i]
    mt = macd_trend[i]; mb = macd_bullish[i]; ms = macd_bearish[i]

    vol_boost_up = 0.0; vol_boost_down = 0.0; vol_penalty_up = 0.0; vol_penalty_risk = 0.0
    if vr > 1.3:
        if k[i] > d[i]: vol_boost_up = min((vr - 1.0) * 12, 18)
        else: vol_boost_down = min((vr - 1.0) * 10, 15)
    elif vr < 0.5:
        if k[i] > d[i]: vol_penalty_up = -10
    if vd > 0: vol_penalty_risk = 18; vol_penalty_up -= 8
    elif vd < 0: vol_boost_up += 12
    if vt > 0.15 and k[i] > d[i]: vol_boost_up += min(vt * 8, 8)
    elif vt < -0.25 and k[i] > d[i]: vol_penalty_up -= 5

    macd_boost_up = 0.0; macd_boost_down = 0.0; macd_boost_risk = 0.0
    if is_golden and mb: macd_boost_up = 10
    elif is_golden and mt > 0: macd_boost_up = 5
    elif is_death and ms: macd_boost_down = 10
    elif is_death and mt < 0: macd_boost_down = 5
    if mt > 0.5: macd_boost_up += 3
    elif mt < -0.5:
        macd_boost_down += 3
        if k[i] >= 70: macd_boost_risk += 5

    if k[i] > d[i]:
        if low_golden_bonus: base = 80 + vol_boost_up + macd_boost_up
        elif is_golden: base = 60 + vol_boost_up + macd_boost_up
        else: base = min(60 + up_days * 5 + vol_boost_up * 0.5 + macd_boost_up * 0.5, 92)
        p_up_val = max(base + vol_penalty_up, 10)
    else:
        p_up_val = 30 if is_death else max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)

    if in_down_zone: p_down_val = min(55 + down_days * 5 + vol_boost_down + macd_boost_down, 88)
    elif k[i] < d[i] and k[i] < 50: p_down_val = min(45 + (50 - k[i]) * 1.5 + vol_boost_down * 0.5 + macd_boost_down * 0.5, 80)
    elif high_death: p_down_val = 50 + vol_boost_down * 0.5 + macd_boost_down * 0.5
    elif risk_days >= 1: p_down_val = min(50 + risk_days * 3 + macd_boost_down * 0.3, 70)
    elif is_golden: p_down_val = max(prev_down - 15, 10)
    else:
        decay = 2 if vr >= 0.8 else 1.5
        p_down_val = max(prev_down - decay, 20)

    if high_death: p_risk_val = 65 + vol_penalty_risk * 0.3 + macd_boost_risk
    elif risk_days >= 1 and k[i] < d[i]: p_risk_val = min(65 + risk_days * 5 + vol_penalty_risk * 0.5 + macd_boost_risk, 88)
    elif k[i] < d[i] and k[i] >= 75: p_risk_val = min(45 + (k[i] - 75) * 2 + vol_penalty_risk * 0.3 + macd_boost_risk, 70)
    elif in_down_zone: p_risk_val = max(prev_risk - 10, 10)
    elif is_golden: p_risk_val = max(prev_risk - 20, 5)
    else: p_risk_val = max(prev_risk - 2 + vol_penalty_risk * 0.2, 15)

    p_up[i] = max(10, min(92, p_up_val))
    p_down[i] = max(10, min(88, p_down_val))
    p_risk[i] = max(5, min(88, p_risk_val))

# 智能信号确认 (与扫描器完全一致)
HYSTERESIS = 3.0
state = np.full(len(close), 0, dtype=int)
prev_confirmed = 0; pending_s = 0; pending_cnt = 0

for i in range(N, len(close)):
    pu = p_up[i]; pdw = p_down[i]; pr = p_risk[i]
    if pu > pr + HYSTERESIS and pu > pdw + HYSTERESIS: raw_s = 1
    elif pr > pu + HYSTERESIS and pr > pdw + HYSTERESIS: raw_s = 2
    elif pdw > pu + HYSTERESIS and pdw > pr + HYSTERESIS: raw_s = 3
    else: raw_s = prev_confirmed

    is_g = k[i-1] <= d[i-1] and k[i] > d[i] if i > 0 else False
    is_hd = (k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85) if i > 0 else False
    vr = vol_ratio[i]; vd = vol_divergence[i]

    high_conf_bull = (is_g and vr > 1.3) or (is_g and macd_bullish[i]) or (vd < 0) or (pu > 70 and vr > 1.2)
    high_conf_bear = (is_hd and vr > 1.3) or (is_hd and macd_bearish[i]) or (vd > 0 and k[i] > 70)

    confirm_days = 1 if (raw_s == 1 and high_conf_bull) or ((raw_s == 3 or raw_s == 2) and (high_conf_bear or is_hd)) else 2

    if raw_s != pending_s: pending_s = raw_s; pending_cnt = 1
    else: pending_cnt += 1

    if pending_cnt >= confirm_days:
        state[i] = pending_s; prev_confirmed = pending_s
    else:
        state[i] = prev_confirmed

# ===== 5. 回测交易 =====
STATE_NAMES = {0:"—", 1:"↑买入", 2:"△卖出", 3:"↓卖出"}
INIT_CAPITAL = 100000  # 初始10万

positions = []     # (entry_date_idx, entry_price)
trades = []        # (entry_date, exit_date, entry_price, exit_price, return_pct, entry_state_name)
equity = np.full(len(close), np.nan, dtype=float)
equity[N] = INIT_CAPITAL

in_position = False
entry_idx = 0; entry_price = 0; entry_state_name = ""
cash = INIT_CAPITAL
shares = 0

for i in range(N + 1, len(close)):
    s = state[i]
    prev_s = state[i-1]
    
    if not in_position:
        # 绿色买入: state == 1 (↑上升)
        if s == 1 and prev_s != 1:
            in_position = True
            entry_idx = i
            entry_price = close[i]
            entry_state_name = STATE_NAMES[s]
            shares = cash / close[i]
            cash = 0
    else:
        # 黄色(2)或红色(3)卖出
        if s == 2 or s == 3:
            in_position = False
            exit_price = close[i]
            ret_pct = (exit_price - entry_price) / entry_price * 100
            trades.append((dates_raw[entry_idx], dates_raw[i], entry_price, exit_price, ret_pct, entry_state_name))
            cash = shares * close[i]
            shares = 0
    
    if in_position:
        equity[i] = shares * close[i]
    else:
        equity[i] = cash

# 最后如果还持仓，按最后价格平仓
if in_position:
    exit_price = close[-1]
    ret_pct = (exit_price - entry_price) / entry_price * 100
    trades.append((dates_raw[entry_idx], dates_raw[-1], entry_price, exit_price, ret_pct, entry_state_name))
    cash = shares * close[-1]
    equity[-1] = cash
    in_position = False

# 填充equity中nan值
for i in range(N + 1, len(close)):
    if np.isnan(equity[i]):
        equity[i] = equity[i-1]

# ===== 6. 统计 =====
final_value = equity[-1]
total_return = (final_value - INIT_CAPITAL) / INIT_CAPITAL * 100
buy_hold_return = (close[-1] - close[N]) / close[N] * 100

win_trades = [t for t in trades if t[4] > 0]
loss_trades = [t for t in trades if t[4] <= 0]
win_rate = len(win_trades) / len(trades) * 100 if trades else 0
avg_win = np.mean([t[4] for t in win_trades]) if win_trades else 0
avg_loss = np.mean([t[4] for t in loss_trades]) if loss_trades else 0

# 最大回撤
peak = equity[N]
max_dd = 0
for i in range(N, len(close)):
    if equity[i] > peak: peak = equity[i]
    dd = (peak - equity[i]) / peak * 100
    if dd > max_dd: max_dd = dd

# 年化
years = (dates_dt[-1] - dates_dt[N]).days / 365.25
cagr = ((final_value / INIT_CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0

# 夏普 (简化)
daily_returns = []
for i in range(N + 1, len(close)):
    if equity[i-1] > 0:
        daily_returns.append((equity[i] - equity[i-1]) / equity[i-1])
sharpe = (np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252)) if daily_returns and np.std(daily_returns) > 0 else 0

print(f"\n{'='*60}")
print(f"  沪深300 KDJ V3 回测结果")
print(f"  回测区间: {dates_raw[N]} ~ {dates_raw[-1]} ({years:.1f}年)")
print(f"{'='*60}")
print(f"  总收益率:     {total_return:+.1f}%")
print(f"  买入持有:     {buy_hold_return:+.1f}%")
print(f"  年化收益:     {cagr:+.1f}%")
print(f"  夏普比率:     {sharpe:.2f}")
print(f"  最大回撤:     {max_dd:.1f}%")
print(f"  交易次数:     {len(trades)}")
print(f"  胜率:         {win_rate:.1f}%")
print(f"  平均盈利:     {avg_win:+.1f}%")
print(f"  平均亏损:     {avg_loss:+.1f}%")
print(f"  最终资金:     ¥{final_value:,.0f}")
print()

# 逐年收益
print(f"  逐年收益:")
for yr in range(2022, 2027):
    yr_equity = []
    for i in range(N, len(close)):
        if dates_raw[i].startswith(str(yr)):
            yr_equity.append(equity[i])
    if yr_equity:
        yr_start = yr_equity[0]
        yr_end = yr_equity[-1]
        yr_ret = (yr_end - yr_start) / yr_start * 100
        print(f"    {yr}: {yr_ret:+.1f}%")

print(f"\n  最近5笔交易:")
for t in trades[-5:]:
    tag = "✓" if t[4] > 0 else "✗"
    print(f"    {t[0]} → {t[1]}  {t[4]:+.1f}% {tag}")

# ===== 7. 画图 =====
c_bg = '#0d1117'; c_ax = '#161b22'
c_up = '#00ff00'; c_risk = '#ffff00'; c_down = '#ff0000'
c_price = '#ffffff'; c_eq = '#00ffff'
c_grid = '#333333'; c_label = '#dddddd'

fig = plt.figure(figsize=(22, 14), facecolor=c_bg)

# 子图1: 价格 + 信号 + 买卖点
ax1 = fig.add_axes([0.06, 0.55, 0.92, 0.43], facecolor=c_ax)
ax1.plot(dates_dt, close, color=c_price, linewidth=1.0, alpha=0.7)

# 背景着色
i = N
while i < len(close):
    if state[i] == 0: i += 1; continue
    s = state[i]; j = i
    while j < len(close) and state[j] == s: j += 1
    for idx in range(i, min(j, len(close) - 1)):
        if s == 1: alpha = 0.12
        elif s == 2: alpha = 0.10
        elif s == 3: alpha = 0.12
        ax1.axvspan(dates_dt[idx], dates_dt[idx+1], alpha=alpha, color={1:c_up,2:c_risk,3:c_down}[s], linewidth=0, zorder=0)
    i = j

# 买卖箭头
for t in trades:
    entry_dt = datetime.strptime(t[0], '%Y%m%d')
    exit_dt = datetime.strptime(t[1], '%Y%m%d')
    ax1.scatter(entry_dt, t[2], color=c_up, marker='^', s=80, zorder=5, edgecolors='white', linewidth=0.5)
    ax1.scatter(exit_dt, t[3], color=c_down if t[4] <= 0 else c_risk, marker='v', s=60, zorder=5, edgecolors='white', linewidth=0.5)

ax1.set_ylabel('沪深300', color=c_label, fontsize=16)
ax1.tick_params(colors=c_label, labelsize=11)
ax1.grid(True, alpha=0.06, color=c_grid)
ax1.set_xlim(dates_dt[N], dates_dt[-1])
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax1.set_xticklabels([])

# 图例
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0], [0], marker='^', color='w', markerfacecolor=c_up, markersize=10, label='买入(绿色)'),
    Line2D([0], [0], marker='v', color='w', markerfacecolor=c_down, markersize=10, label='卖出亏(红色)'),
    Line2D([0], [0], marker='v', color='w', markerfacecolor=c_risk, markersize=10, label='卖出盈(黄色)'),
    Line2D([0], [0], color=c_up, linewidth=8, alpha=0.2, label='上升(绿色)'),
    Line2D([0], [0], color=c_risk, linewidth=8, alpha=0.2, label='风险(黄色)'),
    Line2D([0], [0], color=c_down, linewidth=8, alpha=0.2, label='下跌(红色)'),
]
ax1.legend(handles=legend_elements, loc='upper left', fontsize=9, facecolor=c_ax, edgecolor=c_grid, labelcolor=c_label)

# 子图2: 资金曲线
ax2 = fig.add_axes([0.06, 0.30, 0.92, 0.23], facecolor=c_ax)
ax2.plot(dates_dt[N:], equity[N:], color=c_eq, linewidth=1.5, label='策略净值')
ax2.axhline(y=INIT_CAPITAL, color=c_grid, linestyle='--', alpha=0.5)
ax2.fill_between(dates_dt[N:], INIT_CAPITAL, equity[N:], 
                  where=equity[N:] >= INIT_CAPITAL, color=c_up, alpha=0.08)
ax2.fill_between(dates_dt[N:], INIT_CAPITAL, equity[N:], 
                  where=equity[N:] < INIT_CAPITAL, color=c_down, alpha=0.08)
ax2.set_ylabel('资金', color=c_label, fontsize=14)
ax2.tick_params(colors=c_label, labelsize=11)
ax2.grid(True, alpha=0.08, color=c_grid)
ax2.set_xlim(dates_dt[N], dates_dt[-1])
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
ax2.set_xticklabels([])

# 子图3: 回撤
dd_curve = []
peak_v = equity[N]
for i in range(N, len(close)):
    if equity[i] > peak_v: peak_v = equity[i]
    dd_curve.append((peak_v - equity[i]) / peak_v * 100)

ax3 = fig.add_axes([0.06, 0.06, 0.92, 0.22], facecolor=c_ax)
ax3.fill_between(dates_dt[N:], 0, dd_curve, color=c_down, alpha=0.3)
ax3.plot(dates_dt[N:], dd_curve, color=c_down, linewidth=1.0)
ax3.set_ylabel('回撤%', color=c_label, fontsize=14)
ax3.tick_params(colors=c_label, labelsize=11)
ax3.grid(True, alpha=0.08, color=c_grid)
ax3.set_xlim(dates_dt[N], dates_dt[-1])
ax3.invert_yaxis()
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.setp(ax3.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=11, color=c_label)

# 标题
fig.suptitle(f'沪深300 KDJ概率V3 回测 | {total_return:+.1f}% ({years:.1f}年) | 胜率{win_rate:.0f}% | 夏普{sharpe:.2f} | 最大回撤{max_dd:.1f}%',
             color=c_label, fontsize=16, y=0.995)

out_path = '/mnt/d/Hermes_workspace/stock_research/1a.HS300_trend_detect/backtest_2022_2026.png'
fig.savefig(out_path, dpi=150, facecolor=c_bg)
plt.close(fig)
print(f"\n图表: {out_path}")
