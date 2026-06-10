#!/usr/bin/env python3
"""
大盘趋势策略回测 v3 对比 (第二轮优化)
- 原版：纯KDJ概率系统
- v3版：KDJ + 成交量融合 + 智能信号确认(高置信免延迟) + MACD辅助 + 量价背离强化
回测区间：2022-2025 (4年)
"""
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

print("拉取上证指数数据 (2021-2025)...")
df = pro.index_daily(ts_code="000001.SH", start_date="20210701", end_date="20251231")
df = df.sort_values("trade_date").reset_index(drop=True)
print(f"  共 {len(df)} 条数据: {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")

close = df["close"].values
high = df["high"].values
low = df["low"].values
opens = df["open"].values
vol = df["vol"].values
dates = pd.to_datetime(df["trade_date"]).values
ds = df["trade_date"].values

N, M1, M2 = 14, 5, 3

# ═══════════════════════════════════════════
#  KDJ 计算 (共用)
# ═══════════════════════════════════════════
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

# ═══════════════════════════════════════════
#  MACD 计算 (v3辅助指标)
# ═══════════════════════════════════════════
def ema(data, span):
    result = np.full(len(data), np.nan, dtype=float)
    k_ema = 2.0 / (span + 1)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = data[i] * k_ema + result[i-1] * (1 - k_ema)
    return result

ema12 = ema(close, 12)
ema26 = ema(close, 26)
dif = ema12 - ema26
dea = ema(dif, 9)
macd_hist = 2 * (dif - dea)  # MACD柱

# MACD信号
macd_bullish = np.zeros(len(close), dtype=bool)  # MACD金叉
macd_bearish = np.zeros(len(close), dtype=bool)  # MACD死叉
for i in range(1, len(close)):
    if not np.isnan(dif[i]) and not np.isnan(dif[i-1]):
        macd_bullish[i] = (dif[i-1] <= dea[i-1]) and (dif[i] > dea[i])
        macd_bearish[i] = (dif[i-1] >= dea[i-1]) and (dif[i] < dea[i])

# MACD方向: DIF > DEA 且 DIF 上升
macd_trend = np.zeros(len(close), dtype=float)  # -1 ~ +1
for i in range(len(close)):
    if not np.isnan(dif[i]) and not np.isnan(dea[i]):
        if dif[i] > dea[i] and (i == 0 or dif[i] > dif[i-1]):
            macd_trend[i] = 1.0  # 多头趋势且动能增强
        elif dif[i] > dea[i]:
            macd_trend[i] = 0.5  # 多头但动能减弱
        elif dif[i] < dea[i] and (i == 0 or dif[i] < dif[i-1]):
            macd_trend[i] = -1.0  # 空头趋势且动能增强
        else:
            macd_trend[i] = -0.5  # 空头但动能减弱

# ═══════════════════════════════════════════
#  成交量特征计算
# ═══════════════════════════════════════════
vol_ma20 = np.full(len(close), np.nan, dtype=float)
for i in range(19, len(close)):
    vol_ma20[i] = np.mean(vol[i - 19:i + 1])

vol_ma5 = np.full(len(close), np.nan, dtype=float)
for i in range(4, len(close)):
    vol_ma5[i] = np.mean(vol[i - 4:i + 1])

# 量比
vol_ratio = np.full(len(close), 1.0)
for i in range(len(close)):
    if not np.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
        vol_ratio[i] = vol[i] / vol_ma20[i]

# 量价背离 (近20日窗口)
vol_divergence = np.zeros(len(close), dtype=float)
for i in range(20, len(close)):
    # 顶背离: 价格创新高但量能萎缩
    price_high_20 = np.max(close[i - 19:i])
    if close[i] >= price_high_20 * 0.995:
        recent_vol_max = np.max(vol[i - 19:i])
        if recent_vol_max > 0 and vol[i] < recent_vol_max * 0.65:
            vol_divergence[i] = 1.0

    # 底背离: 价格创新低但量能萎缩 (抛压衰竭)
    price_low_20 = np.min(close[i - 19:i])
    if close[i] <= price_low_20 * 1.005:
        recent_vol_avg = np.mean(vol[i - 19:i])
        if recent_vol_avg > 0 and vol[i] < recent_vol_avg * 0.6:
            vol_divergence[i] = -1.0

# 量能趋势
vol_trend = np.full(len(close), 0.0)
for i in range(len(close)):
    if not np.isnan(vol_ma5[i]) and not np.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
        vol_trend[i] = (vol_ma5[i] / vol_ma20[i]) - 1.0

# ═══════════════════════════════════════════
#  原版概率系统
# ═══════════════════════════════════════════
def calc_prob_original():
    p_up = np.full(len(close), 50.0)
    p_down = np.full(len(close), 50.0)
    p_risk = np.full(len(close), 50.0)
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

        if k[i] > d[i]:
            p_up_val = 80 if low_golden_bonus else (60 if is_golden else min(60+up_days*5, 92))
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

    state = np.full(len(close), 0, dtype=int)
    for i in range(N, len(close)):
        pu=p_up[i]; pdw=p_down[i]; pr=p_risk[i]
        if pu > pr and pu > pdw: state[i] = 1
        elif pr > pu and pr > pdw: state[i] = 2
        elif pdw > pu and pdw > pr: state[i] = 3
    return p_up, p_down, p_risk, state

# ═══════════════════════════════════════════
#  v3 概率系统 (成交量融合 + MACD辅助 + 智能确认)
# ═══════════════════════════════════════════
def calc_prob_v3():
    p_up = np.full(len(close), 50.0)
    p_down = np.full(len(close), 50.0)
    p_risk = np.full(len(close), 50.0)
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

        # ── 成交量修正 ──
        vr = vol_ratio[i]
        vt = vol_trend[i]
        vd = vol_divergence[i]

        # MACD辅助
        mt = macd_trend[i]
        mb = macd_bullish[i]
        ms = macd_bearish[i]

        # 量能因子
        vol_boost_up = 0.0
        vol_boost_down = 0.0
        vol_penalty_up = 0.0
        vol_penalty_risk = 0.0

        # 放量确认 (加强版)
        if vr > 1.3:  # 放量门槛降低
            if k[i] > d[i]:
                vol_boost_up = min((vr - 1.0) * 12, 18)  # 最多+18
            else:
                vol_boost_down = min((vr - 1.0) * 10, 15)
        elif vr < 0.5:  # 极度缩量
            if k[i] > d[i]:
                vol_penalty_up = -10  # 缩量上涨不可靠
            # 缩量下跌 → 抛压减轻 → 下跌概率微调低

        # 量价背离 (加强版)
        if vd > 0:  # 顶背离
            vol_penalty_risk = 18  # 大幅增加风险概率
            vol_penalty_up -= 8    # 降低上涨信心
        elif vd < 0:  # 底背离 (抛压衰竭，可能见底)
            vol_boost_up += 12  # 强看涨信号

        # 量能趋势
        if vt > 0.15 and k[i] > d[i]:
            vol_boost_up += min(vt * 8, 8)
        elif vt < -0.25 and k[i] > d[i]:
            vol_penalty_up -= 5

        # MACD共振加成
        macd_boost_up = 0.0
        macd_boost_down = 0.0
        macd_boost_risk = 0.0

        if is_golden and mb:  # KDJ+MACD双金叉 → 强信号
            macd_boost_up = 10
        elif is_golden and mt > 0:  # KDJ金叉 + MACD多头
            macd_boost_up = 5
        elif is_death and ms:  # KDJ+MACD双死叉 → 强卖出信号
            macd_boost_down = 10
        elif is_death and mt < 0:
            macd_boost_down = 5

        # MACD趋势对概率的基础修正
        if mt > 0.5:
            macd_boost_up += 3
        elif mt < -0.5:
            macd_boost_down += 3
            if k[i] >= 70:
                macd_boost_risk += 5

        # ── P_UP ──
        if k[i] > d[i]:
            if low_golden_bonus:
                base = 80 + vol_boost_up + macd_boost_up
            elif is_golden:
                base = 60 + vol_boost_up + macd_boost_up
            else:
                base = min(60 + up_days * 5 + vol_boost_up * 0.5 + macd_boost_up * 0.5, 92)
            p_up_val = max(base + vol_penalty_up, 10)
        else:
            if is_death:
                p_up_val = 30
            else:
                p_up_val = max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)

        # ── P_DOWN ──
        if in_down_zone:
            p_down_val = min(55 + down_days * 5 + vol_boost_down + macd_boost_down, 88)
        elif k[i] < d[i] and k[i] < 50:
            p_down_val = min(45 + (50 - k[i]) * 1.5 + vol_boost_down * 0.5 + macd_boost_down * 0.5, 80)
        elif high_death:
            p_down_val = 50 + vol_boost_down * 0.5 + macd_boost_down * 0.5
        elif risk_days >= 1:
            p_down_val = min(50 + risk_days * 3 + macd_boost_down * 0.3, 70)
        elif is_golden:
            p_down_val = max(prev_down - 15, 10)
        else:
            decay = 2 if vr >= 0.8 else 1.5
            p_down_val = max(prev_down - decay, 20)

        # ── P_RISK ──
        if high_death:
            p_risk_val = 65 + vol_penalty_risk * 0.3 + macd_boost_risk
        elif risk_days >= 1 and k[i] < d[i]:
            p_risk_val = min(65 + risk_days * 5 + vol_penalty_risk * 0.5 + macd_boost_risk, 88)
        elif k[i] < d[i] and k[i] >= 75:
            p_risk_val = min(45 + (k[i] - 75) * 2 + vol_penalty_risk * 0.3 + macd_boost_risk, 70)
        elif in_down_zone:
            p_risk_val = max(prev_risk - 10, 10)
        elif is_golden:
            p_risk_val = max(prev_risk - 20, 5)
        else:
            p_risk_val = max(prev_risk - 2 + vol_penalty_risk * 0.2, 15)

        p_up_val = max(10, min(92, p_up_val))
        p_down_val = max(10, min(88, p_down_val))
        p_risk_val = max(5, min(88, p_risk_val))

        p_up[i] = p_up_val
        p_down[i] = p_down_val
        p_risk[i] = p_risk_val

    # ── 状态判定 (智能信号确认) ──
    # 高置信信号 (金叉+放量 / MACD共振 / 底背离) 跳过延迟
    # 普通信号需2天确认
    # 高位死叉 保持快速退出 (1天确认)
    HYSTERESIS = 3.0
    state = np.full(len(close), 0, dtype=int)
    prev_s = 0
    pending_s = 0
    pending_cnt = 0

    for i in range(N, len(close)):
        pu = p_up[i]; pdw = p_down[i]; pr = p_risk[i]

        # 原始信号
        if pu > pr + HYSTERESIS and pu > pdw + HYSTERESIS:
            raw_s = 1
        elif pr > pu + HYSTERESIS and pr > pdw + HYSTERESIS:
            raw_s = 2
        elif pdw > pu + HYSTERESIS and pdw > pr + HYSTERESIS:
            raw_s = 3
        else:
            raw_s = prev_s

        # 判断信号置信度
        is_golden = k[i-1] <= d[i-1] and k[i] > d[i] if i > 0 else False
        is_death = k[i-1] >= d[i-1] and k[i] < d[i] if i > 0 else False
        vr = vol_ratio[i]
        vd = vol_divergence[i]

        high_conf_bull = (is_golden and vr > 1.3) or \
                         (is_golden and macd_bullish[i]) or \
                         (vd < 0) or \
                         (pu > 70 and vr > 1.2)  # 高概率+放量

        high_conf_bear = (is_death and vr > 1.3) or \
                         (is_death and macd_bearish[i]) or \
                         (vd > 0 and k[i] > 70)  # 顶背离+高位死叉

        # 确定确认天数
        if raw_s == 1 and high_conf_bull:
            confirm_days = 1  # 高置信做多 → 立即入场
        elif raw_s == 3 or raw_s == 2:
            if high_conf_bear:
                confirm_days = 1  # 高置信做空 → 立即退出
            elif is_death:
                confirm_days = 1  # 死叉 → 快速退出
            else:
                confirm_days = 2  # 普通转空 → 2天确认
        else:
            confirm_days = 2  # 普通信号 → 2天确认

        # 信号确认逻辑
        if raw_s != pending_s:
            pending_s = raw_s
            pending_cnt = 1
        else:
            pending_cnt += 1

        if pending_cnt >= confirm_days:
            state[i] = pending_s
            prev_s = pending_s
        else:
            state[i] = prev_s

    return p_up, p_down, p_risk, state

# ═══════════════════════════════════════════
#  回测引擎
# ═══════════════════════════════════════════
def backtest(p_up, state, label=""):
    YEARS = [
        ('2022', '20220101', '20221231'),
        ('2023', '20230101', '20231231'),
        ('2024', '20240101', '20241231'),
        ('2025', '20250101', '20251231'),
    ]

    results = {}
    for yr, sd, ed in YEARS:
        mask = (df['trade_date'] >= sd) & (df['trade_date'] <= ed)
        idxs = np.where(mask)[0]
        valid = [i for i in idxs if i >= N]
        if not valid:
            continue

        trades = []
        in_position = False
        buy_idx = None
        buy_price = None

        for i in valid:
            current_state = state[i]
            current_p_up = p_up[i]

            if not in_position and current_state == 1 and current_p_up > 55:
                buy_idx = i
                buy_price = close[i]
                in_position = True
            elif in_position and current_state == 3:
                sell_price = close[i]
                ret = (sell_price - buy_price) / buy_price * 100
                hold_days = i - buy_idx
                trades.append((ds[buy_idx], buy_price, ds[i], sell_price, ret, hold_days))
                in_position = False

        if in_position:
            last_idx = valid[-1]
            sell_price = close[last_idx]
            ret = (sell_price - buy_price) / buy_price * 100
            hold_days = last_idx - buy_idx
            trades.append((ds[buy_idx], buy_price, ds[last_idx], sell_price, ret, hold_days))

        total_ret = 1.0
        for *_, r, _ in trades:
            total_ret *= (1 + r / 100)
        total_pct = (total_ret - 1) * 100

        wins = sum(1 for *_, r, _ in trades if r > 0)
        losses = sum(1 for *_, r, _ in trades if r <= 0)
        first_c = close[valid[0]]
        last_c = close[valid[-1]]
        bh = (last_c / first_c - 1) * 100

        results[yr] = {
            'trades': trades,
            'ret': total_pct,
            'bh': bh,
            'excess': total_pct - bh,
            'n_trades': len(trades),
            'wins': wins,
            'losses': losses,
            'winrate': wins / len(trades) * 100 if trades else 0,
        }
    return results

# ═══════════════════════════════════════════
#  执行
# ═══════════════════════════════════════════
print("\n计算原版概率系统...")
pu_orig, pd_orig, pr_orig, st_orig = calc_prob_original()
print("计算v3版概率系统 (成交量+MACD+智能确认)...")
pu_v3, pd_v3, pr_v3, st_v3 = calc_prob_v3()

print("\n回测原版...")
res_orig = backtest(pu_orig, st_orig, "原版")
print("回测v3版...")
res_v3 = backtest(pu_v3, st_v3, "v3")

# ═══════════════════════════════════════════
#  输出对比
# ═══════════════════════════════════════════
def print_report(results, label):
    print(f"\n{'━'*72}")
    print(f"  {label}")
    print(f"{'━'*72}")
    total_s = 1.0; total_b = 1.0; total_trades = 0; total_wins = 0

    for yr in ['2022', '2023', '2024', '2025']:
        if yr not in results: continue
        r = results[yr]
        print(f"\n  ── {yr}年 ──")
        print(f"  交易: {r['n_trades']}笔  胜率: {r['winrate']:.1f}% ({r['wins']}胜/{r['losses']}负)")
        for bd, bp, sd, sp, ret, hd in r['trades']:
            flag = "✅" if ret > 0 else "❌"
            print(f"    {flag} {bd}({bp:.0f}) → {sd}({sp:.0f})  {ret:+.2f}%  持仓{hd}天")
        print(f"  策略收益: {r['ret']:+.2f}%  上证: {r['bh']:+.2f}%  超额: {r['excess']:+.2f}%")
        total_s *= (1 + r['ret'] / 100)
        total_b *= (1 + r['bh'] / 100)
        total_trades += r['n_trades']
        total_wins += r['wins']

    total_pct = (total_s - 1) * 100
    total_bh = (total_b - 1) * 100
    total_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print(f"\n  {'═'*60}")
    print(f"  四年累计  策略: {total_pct:+.2f}%  上证: {total_bh:+.2f}%  超额: {total_pct-total_bh:+.2f}%")
    print(f"  总交易: {total_trades}笔  总胜率: {total_wr:.1f}%")
    print(f"  {'═'*60}")
    return total_pct, total_bh, total_pct - total_bh, total_trades, total_wr

r_orig = print_report(res_orig, "📊 原版策略 (纯KDJ概率系统)")
r_v3 = print_report(res_v3, "📊 v3版策略 (KDJ + 成交量 + MACD + 智能确认)")

# 最终对比
o_ret, o_bh, o_ex, o_n, o_wr = r_orig
v_ret, v_bh, v_ex, v_n, v_wr = r_v3

print(f"\n{'━'*72}")
print(f"  ⚔️  最终对比 (2022-2025)")
print(f"{'━'*72}")
print(f"  {'指标':<16} {'原版':>12} {'v3版':>12} {'差异':>12}")
print(f"  {'─'*52}")
print(f"  {'策略累计收益':<12} {o_ret:>+11.2f}% {v_ret:>+11.2f}% {v_ret-o_ret:>+11.2f}%")
print(f"  {'超额收益':<14} {o_ex:>+11.2f}% {v_ex:>+11.2f}% {v_ex-o_ex:>+11.2f}%")
print(f"  {'交易次数':<14} {o_n:>11d} {v_n:>11d} {v_n-o_n:>+11d}")
print(f"  {'总胜率':<14} {o_wr:>10.1f}% {v_wr:>10.1f}% {v_wr-o_wr:>+10.1f}%")
print(f"  {'上证同期':<14} {o_bh:>+11.2f}% {v_bh:>+11.2f}%")
print(f"{'━'*72}")

if v_ret > o_ret:
    print(f"\n  ✅ v3版跑赢原版! 累计收益高 {v_ret-o_ret:+.2f}%，超额多 {v_ex-o_ex:+.2f}%")
elif v_ex > o_ex:
    print(f"\n  ✅ v3版超额收益更高! 超额多 {v_ex-o_ex:+.2f}%")
else:
    print(f"\n  ⚠️ v3版未跑赢原版，需要进一步调优")
