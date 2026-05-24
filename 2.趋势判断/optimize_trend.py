#!/usr/bin/env python3
"""
趋势判断算法优化

测试多种趋势算法，比较次日方向预测准确率
数据: 1年交易日
"""
import sys, os, time
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

END_DATE = '20260522'

# ============ 获取1年数据 ============
print("→ 获取交易日...")
days = []
for offset in range(400):
    td = (datetime.strptime(END_DATE, '%Y%m%d') - timedelta(days=offset)).strftime('%Y%m%d')
    data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
    if data and data.get('items'):
        days.append(td)
        if len(days) >= 250:
            break
    time.sleep(0.08)
days.sort()
print(f"  {len(days)} 天: {days[0]} ~ {days[-1]}")

print("→ 获取HS300...")
hs300 = {}
for td in days:
    data = hs.api_call('index_daily', ts_code='000300.SH',
                       start_date=td, end_date=td,
                       fields='trade_date,close,pct_chg,vol')
    rows = hs.parse_data(data)
    if rows:
        hs300[td] = {
            'close': float(rows[0]['close']),
            'pct': float(rows[0]['pct_chg']),
            'vol': float(rows[0].get('vol', 0))
        }
    time.sleep(0.06)

# 构建价格序列（便于计算各种指标）
prices = []
dates = []
for td in days:
    if td in hs300:
        prices.append(hs300[td]['close'])
        dates.append(td)
    else:
        prices.append(None)
        dates.append(td)

# 填充None
valid_prices = []
valid_dates = []
for d, p in zip(dates, prices):
    if p is not None:
        valid_prices.append(p)
        valid_dates.append(d)

print(f"  {len(valid_prices)} 个有效价格数据")

# ============ 次日收益 ============
nxt_rets = {}
for i in range(len(valid_dates)-1):
    nxt_rets[valid_dates[i]] = (valid_prices[i+1] - valid_prices[i]) / valid_prices[i] * 100

# ============ 算法列表 ============

def algo_current(d, idx):
    """当前: 5日累计 ≥1.5%"""
    if idx < 5: return None
    ret = sum(hs300[valid_dates[j]]['pct'] for j in range(idx-4, idx+1) if valid_dates[j] in hs300)
    if ret >= 1.5: return 'up'
    if ret <= -1.5: return 'down'
    return 'sideways'

def algo_ma5_ma10(d, idx):
    """MA5 vs MA10 交叉"""
    if idx < 10: return None
    ma5 = sum(valid_prices[idx-4:idx+1]) / 5
    ma10 = sum(valid_prices[idx-9:idx+1]) / 10
    if ma5 > ma10 * 1.003: return 'up'    # 0.3% 摩擦
    if ma5 < ma10 * 0.997: return 'down'
    return 'sideways'

def algo_ma10_ma20(d, idx):
    """MA10 vs MA20 交叉"""
    if idx < 20: return None
    ma10 = sum(valid_prices[idx-9:idx+1]) / 10
    ma20 = sum(valid_prices[idx-19:idx+1]) / 20
    if ma10 > ma20 * 1.002: return 'up'
    if ma10 < ma20 * 0.998: return 'down'
    return 'sideways'

def algo_roc5(d, idx):
    """5日变化率"""
    if idx < 5: return None
    roc = (valid_prices[idx] - valid_prices[idx-5]) / valid_prices[idx-5] * 100
    if roc >= 1.0: return 'up'
    if roc <= -1.0: return 'down'
    return 'sideways'

def algo_roc10(d, idx):
    """10日变化率"""
    if idx < 10: return None
    roc = (valid_prices[idx] - valid_prices[idx-10]) / valid_prices[idx-10] * 100
    if roc >= 2.0: return 'up'
    if roc <= -2.0: return 'down'
    return 'sideways'

def algo_roc3(d, idx):
    """3日变化率"""
    if idx < 3: return None
    roc = (valid_prices[idx] - valid_prices[idx-3]) / valid_prices[idx-3] * 100
    if roc >= 0.8: return 'up'
    if roc <= -0.8: return 'down'
    return 'sideways'

def algo_vol_ma5(d, idx):
    """量价结合: 涨幅+放量"""
    if idx < 5: return None
    ret = sum(hs300[valid_dates[j]]['pct'] for j in range(idx-4, idx+1) if valid_dates[j] in hs300)
    avg_vol = sum(hs300[valid_dates[j]]['vol'] for j in range(idx-4, idx+1) if valid_dates[j] in hs300) / 5
    cur_vol = hs300[valid_dates[idx]]['vol'] if valid_dates[idx] in hs300 else avg_vol
    vol_ratio = cur_vol / max(avg_vol, 1)
    if ret >= 1.0 and vol_ratio >= 1.2: return 'up'
    if ret <= -1.0 and vol_ratio >= 1.2: return 'down'
    if ret >= 1.5: return 'up'
    if ret <= -1.5: return 'down'
    return 'sideways'

def algo_consecutive(d, idx):
    """连续上涨/下跌天数"""
    if idx < 3: return None
    streak = 0
    for j in range(idx, max(0, idx-5)-1, -1):
        ret = hs300[valid_dates[j]]['pct'] if valid_dates[j] in hs300 else 0
        if ret > 0: streak += 1
        else: break
    if streak >= 3: return 'up'
    # 下跌连续
    streak_d = 0
    for j in range(idx, max(0, idx-5)-1, -1):
        ret = hs300[valid_dates[j]]['pct'] if valid_dates[j] in hs300 else 0
        if ret < 0: streak_d += 1
        else: break
    if streak_d >= 3: return 'down'
    return 'sideways'

def algo_combined_vote(d, idx):
    """多算法投票"""
    votes = {'up': 0, 'down': 0, 'sideways': 0}
    for algo in [algo_current, algo_roc5, algo_consecutive, algo_ma5_ma10]:
        r = algo(d, idx)
        if r: votes[r] += 1
    if votes['up'] >= 3: return 'up'
    if votes['down'] >= 3: return 'down'
    if votes['up'] == 2 and votes['down'] == 0: return 'up'
    if votes['down'] == 2 and votes['up'] == 0: return 'down'
    return 'sideways'

# ============ 回测 ============

algorithms = [
    ('current ±1.5% (当前方案)', algo_current),
    ('MA5 vs MA10 交叉', algo_ma5_ma10),
    ('MA10 vs MA20 交叉', algo_ma10_ma20),
    ('ROC 3日 ±0.8%', algo_roc3),
    ('ROC 5日 ±1.0%', algo_roc5),
    ('ROC 10日 ±2.0%', algo_roc10),
    ('量价结合', algo_vol_ma5),
    ('连续涨跌≥3天', algo_consecutive),
    ('多算法投票(≥3/4)', algo_combined_vote),
]

print(f"\n{'='*70}")
print(f"趋势算法对比回测  ({valid_dates[0]} ~ {valid_dates[-1]})")
print(f"{'='*70}")
print(f"{'算法名':<20} {'天数':>5} {'上涨信号':>16} {'下跌信号':>16} {'综合得分':>10}")
print(f"{'':20} {'':5} {'准确率':>8} {'均涨':>7} {'准确率':>8} {'均跌':>7} {'':>10}")
print(f"{'-'*70}")

best_score = -999
best_name = ''
best_up_acc = 0
best_down_acc = 0

for name, algo in algorithms:
    up_correct = 0
    up_total = 0
    down_correct = 0
    down_total = 0
    up_avg_ret = 0
    down_avg_ret = 0
    
    for idx, d in enumerate(valid_dates):
        if d not in nxt_rets:
            continue
        trend = algo(d, idx)
        if trend is None:
            continue
        nxt = nxt_rets[d]
        
        if trend == 'up':
            up_total += 1
            up_avg_ret += nxt
            if nxt > 0:
                up_correct += 1
        elif trend == 'down':
            down_total += 1
            down_avg_ret += nxt
            if nxt < 0:
                down_correct += 1
    
    up_acc = up_correct / max(up_total, 1) * 100
    down_acc = down_correct / max(down_total, 1) * 100
    up_avg = up_avg_ret / max(up_total, 1)
    down_avg = down_avg_ret / max(down_total, 1)
    
    # 综合得分: 上涨准确率 + 下跌准确率（各取50%权重）
    score = (up_acc + down_acc) / 2
    
    print(f"{name:<20} {up_total+down_total:>5} "
          f"{up_acc:>7.1f}% {up_avg:>+6.2f}% "
          f"{down_acc:>7.1f}% {down_avg:>+6.2f}% "
          f"{score:>8.1f}")
    
    if score > best_score:
        best_score = score
        best_name = name
        best_up_acc = up_acc
        best_down_acc = down_acc

print(f"{'-'*70}")
print(f"🏆 最佳: {best_name} (综合{best_score:.1f}分, 上涨{best_up_acc:.0f}%, 下跌{best_down_acc:.0f}%)")
print()

# ============ 最佳算法详细分析 ============
print(f"{'='*70}")
print(f"最佳算法详细分析: {best_name}")
print(f"{'='*70}")

# 找到最佳算法对应的函数
best_algo_fn = None
for name, fn in algorithms:
    if name == best_name:
        best_algo_fn = fn
        break

if best_algo_fn:
    up_samples = []
    down_samples = []
    
    for idx, d in enumerate(valid_dates):
        if d not in nxt_rets:
            continue
        trend = best_algo_fn(d, idx)
        if trend is None:
            continue
        nxt = nxt_rets[d]
        if trend == 'up':
            up_samples.append((d, nxt))
        elif trend == 'down':
            down_samples.append((d, nxt))
    
    # 按市场状态分
    for label, samples in [('📈 上升信号', up_samples), ('📉 下降信号', down_samples)]:
        if not samples:
            continue
        dates_only = [s[0] for s in samples]
        rets = [s[1] for s in samples]
        
        # 分布
        pos = sum(1 for r in rets if r > 0)
        neg = sum(1 for r in rets if r < 0)
        zero = len(rets) - pos - neg
        
        print(f"\n{label} ({len(samples)}天):")
        print(f"  涨{pos}({pos/len(rets)*100:.0f}%) 跌{neg}({neg/len(rets)*100:.0f}%) 平{zero}")
        print(f"  最大涨: {max(rets):+.2f}%  最大跌: {min(rets):+.2f}%")
        print(f"  平均涨: {sum(rets)/len(rets):+.3f}%")
        
        # 连续信号持续力
        streak_results = []
        for i in range(len(dates_only)):
            if i < len(dates_only) - 1:
                streak_results.append(rets[i])
        
        print(f"  信号持续期间的日均收益: {sum(streak_results)/max(len(streak_results),1):+.3f}%")
        
        # 前5最佳/最差
        sorted_by_ret = sorted(samples, key=lambda x: -x[1])
        print(f"  最佳3: ", end='')
        for d, r in sorted_by_ret[:3]:
            print(f"{d}({r:+.2f}%) ", end='')
        print()
        print(f"  最差3: ", end='')
        for d, r in sorted_by_ret[-3:]:
            print(f"{d}({r:+.2f}%) ", end='')
        print()
    
    # 趋势跃迁概率
    print(f"\n  趋势跃迁:")
    trend_seq = []
    for idx, d in enumerate(valid_dates):
        if d not in nxt_rets:
            trend_seq.append(None)
        else:
            trend_seq.append(best_algo_fn(d, idx))
    
    trans = defaultdict(lambda: defaultdict(int))
    for i in range(1, len(trend_seq)):
        if trend_seq[i-1] and trend_seq[i]:
            trans[trend_seq[i-1]][trend_seq[i]] += 1
    
    for ft in ['up', 'sideways', 'down']:
        total = sum(trans[ft].values())
        if total == 0:
            continue
        parts = [f"{tt}={trans[ft][tt]/total*100:.0f}%" for tt in ['up', 'sideways', 'down'] if trans[ft][tt] > 0]
        print(f"    {ft} → {' | '.join(parts)}")

# ============ 最优阈值搜索 ============
print(f"\n{'='*70}")
print(f"最优阈值搜索 (ROC 5日)")
print(f"{'='*70}")
print(f"{'阈值':>8} {'上升信号':>20} {'下降信号':>20} {'综合':>8}")
print(f"{'':8} {'天':>4} {'准确率':>8} {'均涨':>7} {'天':>4} {'准确率':>8} {'均涨':>7}")

for th in [0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0]:
    up_c = up_t = down_c = down_t = 0
    up_r = down_r = 0
    for idx, d in enumerate(valid_dates):
        if d not in nxt_rets or idx < 5:
            continue
        roc = (valid_prices[idx] - valid_prices[idx-5]) / valid_prices[idx-5] * 100
        nxt = nxt_rets[d]
        if roc >= th:
            up_t += 1
            up_r += nxt
            if nxt > 0: up_c += 1
        elif roc <= -th:
            down_t += 1
            down_r += nxt
            if nxt < 0: down_c += 1
    
    ua = up_c/max(up_t,1)*100
    da = down_c/max(down_t,1)*100
    score = (ua + da) / 2
    print(f"  ±{th:.1f}%  {up_t:>4} {ua:>7.1f}% {up_r/max(up_t,1):>+6.2f}% "
          f"{down_t:>4} {da:>7.1f}% {down_r/max(down_t,1):>+6.2f}% {score:>7.1f}")
