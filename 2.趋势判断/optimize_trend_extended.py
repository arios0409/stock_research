#!/usr/bin/env python3
"""
趋势检测算法扩展对比: RSI + 布林线 + KDJ

测试多种趋势指标及参数组合，比较次日方向预测准确率
重点: KDJ参数调优 (K, D, J的各种变体)
"""
import sys, os, time, math
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

END_DATE = '20260522'

# ============ 获取1年数据 ============
print("→ 获取数据...")
days = []
for offset in range(600):
    td = (datetime.strptime(END_DATE, '%Y%m%d') - timedelta(days=offset)).strftime('%Y%m%d')
    data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
    if data and data.get('items'):
        days.append(td)
        if len(days) >= 350:
            break
    time.sleep(0.06)
days.sort()

print(f"  找到 {len(days)} 个交易日")

# 批量获取HS300日线 (一次API调用)
print("→ 获取HS300数据...")
hs300_batch = hs.api_call('index_daily', ts_code='000300.SH',
                          start_date=days[0], end_date=days[-1],
                          fields='trade_date,open,high,low,close,vol')
hs300_rows = hs.parse_data(hs300_batch)
hs300_full = {}
for r in hs300_rows:
    hs300_full[r['trade_date']] = {
        'open': float(r['open']),
        'high': float(r['high']),
        'low': float(r['low']),
        'close': float(r['close']),
        'vol': float(r.get('vol', 0))
    }
print(f"  {len(hs300_full)} 天数据")

# 构建价格序列 (用HS300实际返回的日期)
valid_dates = sorted([d for d in days if d in hs300_full])
closes = [hs300_full[d]['close'] for d in valid_dates]
highs = [hs300_full[d]['high'] for d in valid_dates]
lows = [hs300_full[d]['low'] for d in valid_dates]

print(f"  {len(closes)} 天数据: {valid_dates[0]} ~ {valid_dates[-1]}")

# 次日收益
nxt_rets = {}
for i in range(len(closes)-1):
    nxt_rets[valid_dates[i]] = (closes[i+1] - closes[i]) / closes[i] * 100


# ============ 技术指标计算 ============

def calc_rsi(closes, period=14):
    """RSI 指标"""
    rsis = [None] * len(closes)
    if len(closes) < period + 1:
        return rsis
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    rsis[period] = 100 - (100 / (1 + avg_g / max(avg_l, 0.001)))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        g = max(diff, 0)
        l = max(-diff, 0)
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period
        rsis[i] = 100 - (100 / (1 + avg_g / max(avg_l, 0.001)))
    return rsis


def calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    """KDJ 指标 (标准参数 9,3,3)
    返回: (K_list, D_list, J_list)
    """
    k_list = [50.0] * len(closes)
    d_list = [50.0] * len(closes)
    j_list = [50.0] * len(closes)
    
    for i in range(n, len(closes)):
        hn = max(highs[i-n+1:i+1])
        ln = min(lows[i-n+1:i+1])
        rsv = (closes[i] - ln) / (hn - ln) * 100 if hn != ln else 50
        k = 2/3 * k_list[i-1] + 1/3 * rsv
        d = 2/3 * d_list[i-1] + 1/3 * k
        j = 3 * k - 2 * d
        k_list[i] = k
        d_list[i] = d
        j_list[i] = j
    
    return k_list, d_list, j_list


def calc_bollinger(closes, period=20, mult=2):
    """布林带: 中轨(MA20), 上/下轨"""
    ma = [None] * len(closes)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        ma[i] = sum(closes[i-period+1:i+1]) / period
        std = math.sqrt(sum((c - ma[i])**2 for c in closes[i-period+1:i+1]) / period)
        upper[i] = ma[i] + mult * std
        lower[i] = ma[i] - mult * std
    return ma, upper, lower


# 预计算所有指标
print("→ 计算技术指标...")
rsi_6 = calc_rsi(closes, 6)
rsi_14 = calc_rsi(closes, 14)
rsi_21 = calc_rsi(closes, 21)

# KDJ 多参数组合
kdj_variants = {}
for n in [5, 9, 14, 21]:
    for m1 in [3, 5]:
        for m2 in [3, 5]:
            name = f"KDJ({n},{m1},{m2})"
            kdj_variants[name] = calc_kdj(highs, lows, closes, n, m1, m2)

# 布林带
bb_ma, bb_upper, bb_lower = calc_bollinger(closes, 20, 2)
bb_ma_10, bb_upper_10, bb_lower_10 = calc_bollinger(closes, 10, 2)
bb_ma_30, bb_upper_30, bb_lower_30 = calc_bollinger(closes, 30, 2)

# ============ 算法测试 ============

algorithms = []

# --- 1. 基准: MA10/MA20 ---
def test_ma10_ma20(idx):
    if idx < 20: return None
    ma10 = sum(closes[idx-9:idx+1]) / 10
    ma20 = sum(closes[idx-19:idx+1]) / 20
    if ma10 > ma20 * 1.002: return 'up'
    if ma10 < ma20 * 0.998: return 'down'
    return 'sideways'
algorithms.append(('MA10/MA20 (当前基准)', test_ma10_ma20))

# --- 2. RSI 变体 ---
def make_rsi_algo(rsi_values, period, up_th, down_th):
    def algo(idx):
        if idx < period + 5 or rsi_values[idx] is None: return None
        r = rsi_values[idx]
        # RSI趋势: 上升趋势(>60), 下降趋势(<40), 中间震荡
        if r >= up_th: return 'up'
        if r <= down_th: return 'down'
        return 'sideways'
    return algo

algorithms.append((f'RSI(6) (>{70}/<{30})', make_rsi_algo(rsi_6, 6, 70, 30)))
algorithms.append((f'RSI(14) (>{70}/<{30})', make_rsi_algo(rsi_14, 14, 70, 30)))
algorithms.append((f'RSI(6) (>{60}/<{40})', make_rsi_algo(rsi_6, 6, 60, 40)))
algorithms.append((f'RSI(14) (>{60}/<{40})', make_rsi_algo(rsi_14, 14, 60, 40)))

# RSI 斜率法: RSI trend direction
def make_rsi_slope(rsi_values, period):
    def algo(idx):
        if idx < period + 5 or rsi_values[idx] is None or rsi_values[idx-3] is None:
            return None
        # RSI 3日变化
        slope = rsi_values[idx] - rsi_values[idx-3]
        r = rsi_values[idx]
        if slope > 5 and r > 50: return 'up'
        if slope < -5 and r < 50: return 'down'
        return 'sideways'
    return algo

algorithms.append(('RSI(14) 斜率法', make_rsi_slope(rsi_14, 14)))

# --- 3. KDJ 变体 ---
def make_kdj_algo(name, k, d, j, use_j=False):
    def algo(idx):
        if idx < 14 or k[idx] is None or d[idx] is None: return None
        k_val = k[idx]
        d_val = d[idx]
        
        if use_j:
            j_val = j[idx]
            # J 线更敏感
            if j_val > 100: return 'up'     # 超买区 → up信号
            if j_val < 0: return 'down'     # 超卖区 → down信号
            if k_val > 80 and j_val > 80: return 'up'
            if k_val < 20 and j_val < 20: return 'down'
            return 'sideways'
        else:
            # 标准 K-D 交叉判定
            # 用K和D的绝对值位置
            if k_val > 80 and d_val > 70: return 'up'
            if k_val < 20 and d_val < 30: return 'down'
            return 'sideways'
    return algo

# KDJ K-D 交叉法 (趋势信号)
def make_kdj_cross(name, k, d):
    def algo(idx):
        if idx < 14 or k[idx] is None or d[idx] is None or k[idx-1] is None or d[idx-1] is None:
            return None
        k_val, d_val = k[idx], d[idx]
        k_prev, d_prev = k[idx-1], d[idx-1]
        
        # K 上穿 D (金叉) → 看涨
        if k_prev <= d_prev and k_val > d_val:
            return 'up'
        # K 下穿 D (死叉) → 看跌
        if k_prev >= d_prev and k_val < d_val:
            return 'down'
        # 持续方向
        if k_val > d_val and k_val > 50:
            return 'up'
        if k_val < d_val and k_val < 50:
            return 'down'
        return 'sideways'
    return algo

# KDJ J线法
def make_kdj_j(name, k, d, j):
    def algo(idx):
        if idx < 14 or j[idx] is None: return None
        jv = j[idx]
        kv = k[idx]
        if jv > 100 and kv > 80: return 'up'
        if jv < 0 and kv < 20: return 'down'
        if jv > 80: return 'up'
        if jv < 20: return 'down'
        return 'sideways'
    return algo

# 添加 KDJ 变体
for name, (k, d, j) in kdj_variants.items():
    algorithms.append((f'{name} K-D位置', make_kdj_algo(name, k, d, j)))
    algorithms.append((f'{name} K-D交叉', make_kdj_cross(name, k, d)))
    algorithms.append((f'{name} J线', make_kdj_j(name, k, d, j)))

# --- 4. 布林带 ---
def make_bb_algo(ma, upper, lower):
    def algo(idx):
        if idx < 20 or ma[idx] is None: return None
        c = closes[idx]
        u = upper[idx]
        lw = lower[idx]
        m = ma[idx]
        if c > u: return 'up'       # 突破上轨 → 强势
        if c < lw: return 'down'    # 跌破下轨 → 弱势
        if c > m: return 'up'
        if c < m: return 'down'
        return 'sideways'
    return algo

algorithms.append(('布林带(20,2) 价格vs中轨', make_bb_algo(bb_ma, bb_upper, bb_lower)))

# 布林带带宽法 (volatility expansion → trend)
def make_bb_width(ma, upper, lower):
    def algo(idx):
        if idx < 20 or ma[idx] is None or ma[idx-5] is None: return None
        c = closes[idx]
        width_now = (upper[idx] - lower[idx]) / ma[idx] * 100
        width_5 = (upper[idx-5] - lower[idx-5]) / ma[idx-5] * 100
        # 带宽扩张 + 价格在轨外 = 趋势信号
        if width_now > width_5 * 1.2:  # 带宽扩大20%以上
            if c > upper[idx]: return 'up'
            if c < lower[idx]: return 'down'
        return 'sideways'
    return algo

algorithms.append(('布林带带宽扩张', make_bb_width(bb_ma, bb_upper, bb_lower)))

# --- 5. 组合指标 ---
algos_ref = {}

def algo_ma(idx): return test_ma10_ma20(idx)
algos_ref['MA'] = algo_ma

def make_algo_kdj_combined(n, m1, m2):
    name_k = f'KDJ({n},{m1},{m2})'
    k, d, j = kdj_variants[name_k]
    def algo(idx):
        if idx < 20: return None
        ma = test_ma10_ma20(idx)
        if k[idx] is None or d[idx] is None: return ma
        k_val, d_val = k[idx], d[idx]
        
        # MA + KDJ 投票
        votes = []
        if ma == 'up': votes.append('up')
        if ma == 'down': votes.append('down')
        if k_val > 80 and d_val > 70: votes.append('up')
        if k_val < 20 and d_val < 30: votes.append('down')
        
        up = votes.count('up')
        dn = votes.count('down')
        if up > dn: return 'up'
        if dn > up: return 'down'
        return ma  # 平票用MA
    return algo

algorithms.append(('MA10/20 + KDJ(9,3,3)', make_algo_kdj_combined(9, 3, 3)))
algorithms.append(('MA10/20 + KDJ(5,3,3)', make_algo_kdj_combined(5, 3, 3)))
algorithms.append(('MA10/20 + KDJ(14,3,3)', make_algo_kdj_combined(14, 3, 3)))

# MA + RSI 组合
def make_algo_ma_rsi(period, up_th, down_th):
    rsi_vals = calc_rsi(closes, period)
    def algo(idx):
        if idx < 20 or rsi_vals[idx] is None: return None
        ma = test_ma10_ma20(idx)
        r = rsi_vals[idx]
        votes = []
        if ma == 'up': votes.append('up')
        if ma == 'down': votes.append('down')
        if r >= up_th: votes.append('up')
        if r <= down_th: votes.append('down')
        up = votes.count('up')
        dn = votes.count('down')
        if up > dn: return 'up'
        if dn > up: return 'down'
        return ma
    return algo

algorithms.append(('MA + RSI(14) >70/<30', make_algo_ma_rsi(14, 70, 30)))
algorithms.append(('MA + RSI(6) >70/<30', make_algo_ma_rsi(6, 70, 30)))

# --- 6. KDJ J线调优 (特殊参数) ---
# J线是3K-2D, 比K/D更敏感。调整J的阈值
def make_kdj_j_tuned(n, m1, m2, j_up, j_down, k_up, k_down):
    name = f'KDJ({n},{m1},{m2})'
    k, d, j = kdj_variants[name]
    def algo(idx):
        if idx < n + 5 or j[idx] is None: return None
        jv = j[idx]
        kv = k[idx] if k[idx] is not None else 50
        if jv > j_up and kv > k_up: return 'up'
        if jv < j_down and kv < k_down: return 'down'
        return 'sideways'
    return algo

# 测试不同的J线阈值
for j_up in [80, 90, 100, 110]:
    for j_down in [20, 10, 0]:
        name = f'KDJ(9,3,3) J调参 J>{j_up} J<{j_down}'
        algorithms.append((name, make_kdj_j_tuned(9, 3, 3, j_up, j_down, 50, 50)))


# ============ 回测 ============
print(f"\n{'='*75}")
print(f"趋势算法扩展对比  ({valid_dates[0]} ~ {valid_dates[-1]})")
print(f"{'='*75}")
print(f"{'算法名':<30} {'信号':>5} {'上涨准确率':>12} {'均涨':>7} {'下跌准确率':>12} {'均跌':>7} {'综合':>6}")
print(f"{'-'*75}")

results_list = []
for name, algo in algorithms:
    up_c, up_t, down_c, down_t = 0, 0, 0, 0
    up_r, down_r = 0, 0
    
    for idx, d in enumerate(valid_dates):
        if d not in nxt_rets: continue
        trend = algo(idx)
        if trend is None: continue
        nxt = nxt_rets[d]
        if trend == 'up':
            up_t += 1; up_r += nxt
            if nxt > 0: up_c += 1
        elif trend == 'down':
            down_t += 1; down_r += nxt
            if nxt < 0: down_c += 1
    
    if up_t + down_t < 20: continue  # 样本太少跳过
    
    ua = up_c/max(up_t,1)*100
    da = down_c/max(down_t,1)*100
    score = (ua + da) / 2
    
    results_list.append((score, name, up_t, ua, up_r/max(up_t,1), down_t, da, down_r/max(down_t,1)))

# 排序
results_list.sort(key=lambda x: -x[0])
for score, name, up_t, ua, ua_r, down_t, da, da_r in results_list:
    marker = '🏆' if results_list.index((score, name, up_t, ua, ua_r, down_t, da, da_r)) == 0 else ' '
    print(f"{marker} {name:<30} {up_t+down_t:>5} "
          f"{ua:>7.1f}% {ua_r:>+6.2f}% "
          f"{da:>7.1f}% {da_r:>+6.2f}% "
          f"{score:>5.1f}")

print(f"{'-'*75}")
print()

# ============ 最佳KDJ参数搜索 ============
print(f"{'='*75}")
print(f"KDJ 参数网格搜索 (J线法)")
print(f"{'='*75}")
print(f"{'参数':<16} {'信号':>5} {'上涨准确率':>12} {'均涨':>7} {'下跌准确率':>12} {'均跌':>7} {'综合':>6}")
print(f"{'-'*75}")

kdj_results = []
for name, (k, d, j) in sorted(kdj_variants.items()):
    # 用J线法测试多种阈值
    for j_up, j_down in [(100, 0), (90, 10), (80, 20), (110, -10), (120, -20)]:
        up_c, up_t, down_c, down_t = 0, 0, 0, 0
        up_r, down_r = 0, 0
        for idx, d in enumerate(valid_dates):
            if d not in nxt_rets or idx < 14 or j[idx] is None: continue
            jv = j[idx]
            if jv > j_up:
                up_t += 1; up_r += nxt_rets[d]
                if nxt_rets[d] > 0: up_c += 1
            elif jv < j_down:
                down_t += 1; down_r += nxt_rets[d]
                if nxt_rets[d] < 0: down_c += 1
        
        if up_t + down_t < 15: continue
        ua = up_c/max(up_t,1)*100
        da = down_c/max(down_t,1)*100
        score = (ua + da) / 2
        kdj_results.append((score, name, j_up, j_down, up_t, ua, up_r/max(up_t,1), down_t, da, down_r/max(down_t,1)))

kdj_results.sort(key=lambda x: -x[0])
for score, name, j_up, j_down, up_t, ua, ua_r, down_t, da, da_r in kdj_results[:20]:
    print(f"  {name} J>{j_up}/<{j_down:<3} {up_t+down_t:>5} "
          f"{ua:>7.1f}% {ua_r:>+6.2f}% "
          f"{da:>7.1f}% {da_r:>+6.2f}% "
          f"{score:>5.1f}")

# ============ 总结 ============
print()
print(f"{'='*60}")
print(f"结论")
print(f"{'='*60}")

top5 = results_list[:5]
print(f"\nTop 5 算法:")
for score, name, up_t, ua, ua_r, down_t, da, da_r in top5:
    print(f"  {name:<30} 综合{score:.1f}  上涨{ua:.0f}%  下跌{da:.0f}%")

print(f"\nMA10/MA20 基准排名:")
for i, (score, name, *_) in enumerate(results_list):
    if 'MA10/MA20' in name:
        print(f"  第{i+1}/{len(results_list)}名 (综合{score:.1f})")

print(f"\nKDJ 最佳参数:")
for score, name, *rest in kdj_results[:3]:
    print(f"  {name}  J阈值{rest[0]}/{rest[1]}  综合{score:.1f}")

print(f"\nKDJ vs MA10/MA20:")
ma_score = None
kdj_best = None
for score, name, *rest in results_list:
    if 'MA10/MA20' in name and 'KDJ' not in name and '+' not in name:
        ma_score = score
    if 'KDJ' in name:
        if kdj_best is None or score > kdj_best[0]:
            kdj_best = (score, name)
if ma_score and kdj_best:
    diff = kdj_best[0] - ma_score
    print(f"  MA10/MA20: {ma_score:.1f}")
    print(f"  KDJ最佳:   {kdj_best[0]:.1f} ({kdj_best[1]})")
    print(f"  差距:      {diff:+.1f}")
    if diff > 0:
        print(f"  → KDJ 略优于 MA10/MA20，但信号数量差异需考察")
    else:
        print(f"  → MA10/MA20 仍优于 KDJ")
