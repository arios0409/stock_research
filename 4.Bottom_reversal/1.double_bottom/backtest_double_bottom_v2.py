"""
双底形态回测系统 v2 - 优化参数版
=================================
优化点：
  1. 颈线高度 > 10%（原5%）
  2. 突破要求放量：突破日成交量 > 20日均量 × 1.5
  3. 突破后3天内不回到颈线×0.98以下
  4. 其他参数不变
"""

import urllib.request
import json
import os
import sys
import time
from datetime import datetime

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'

INITIAL_CAPITAL_PER_STOCK = 100_000
STOP_LOSS_PCT = 0.03
HOLD_MONTHS = 3

# ============ Tushare API ============

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields: payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') != 0: return None
        return result.get('data', {})
    except Exception: return None

def get_stock_list():
    result = api_call('stock_basic', fields='ts_code,symbol,name,industry,list_status')
    if not result or 'fields' not in result or 'items' not in result: return []
    fields = result['fields']
    return [dict(zip(fields, item)) for item in result['items'] if dict(zip(fields, item)).get('list_status') == 'L']

def get_hs300_components():
    result = api_call('index_weight', index_code='399300.SZ', fields='con_code')
    if not result or 'items' not in result: return None
    return list(set(item[0] for item in result['items']))

def get_zz500_components():
    result = api_call('index_weight', index_code='000905.SH', fields='con_code')
    if not result or 'items' not in result: return []
    return list(set(item[0] for item in result['items']))

def get_daily_data(ts_code, start_date, end_date):
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result: return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df

# ============ 技术指标 ============

def calc_macd(closes):
    n = len(closes)
    def ema(data, span):
        k = 2.0 / (span + 1); result = [data[0]]
        for i in range(1, len(data)): result.append(data[i] * k + result[-1] * (1 - k))
        return result
    ema12 = ema(closes, 12); ema26 = ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(n)]
    dea = ema(dif, 9)
    return [2 * (dif[i] - dea[i]) for i in range(n)]

def calc_rsi(closes, period=14):
    n = len(closes); rsi = [50.0] * n
    if n < period + 1: return rsi
    gains, losses = [], []
    for i in range(1, n):
        diff = closes[i] - closes[i-1]; gains.append(max(0, diff)); losses.append(max(0, -diff))
    avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
    for i in range(period, n - 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi

def moving_avg(data, period):
    n = len(data)
    result = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(data[i - period + 1: i + 1]) / period
    return result

# ============ 双底检测 v2 ============

def detect_double_bottom_v2(df, window=8, double_bottom_start=None):
    """优化版双底检测"""
    n = len(df)
    if n < window * 2 + 1: return []

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    vol_ma20 = moving_avg(volumes, 20)

    # 找局部高低点
    lows, highs = [], []
    for i in range(window, n - window):
        price = closes[i]
        if all(closes[j] > price for j in range(max(0, i-window), min(n, i+window+1)) if j != i):
            lows.append((i, price, volumes[i]))
        if all(closes[j] < price for j in range(max(0, i-window), min(n, i+window+1)) if j != i):
            highs.append((i, price))

    if len(lows) < 2 or len(highs) < 1: return []

    results = []
    for i in range(len(lows) - 1):
        l1_idx, l1_price, l1_vol = lows[i]
        l2_idx, l2_price, l2_vol = lows[i + 1]

        # 间距要求
        gap = l2_idx - l1_idx
        if gap < 15 or gap > 150: continue

        # 价格接近
        if abs(l1_price - l2_price) / min(l1_price, l2_price) > 0.05: continue

        # 找颈线
        necks = [h for h in highs if l1_idx < h[0] < l2_idx]
        if not necks: continue
        n_idx, n_price = max(necks, key=lambda x: x[1])

        # === 优化1: 颈线高度 > 10% (原5%) ===
        neck_height_pct = (n_price - min(l1_price, l2_price)) / min(l1_price, l2_price)
        if neck_height_pct < 0.10: continue

        # 双底开始时间过滤
        if double_bottom_start and dates[l1_idx] < double_bottom_start: continue

        # === 从右底之后找突破 ===
        break_idx = None
        for j in range(l2_idx, n):
            # 突破阈值 > 1%
            if closes[j] > n_price * 1.01:
                # === 优化2: 突破要求放量 (成交量 > 20日均量 × 1.5) ===
                if vol_ma20[j] is not None and volumes[j] < vol_ma20[j] * 1.5:
                    continue
                # === 优化3: 突破后3天内不回到颈线×0.98以下 ===
                fake_breakout = False
                for k in range(j + 1, min(j + 4, n)):
                    if closes[k] < n_price * 0.98:
                        fake_breakout = True
                        break
                if fake_breakout:
                    continue
                # 通过所有过滤
                break_idx = j
                break

        if break_idx is None: continue

        results.append({
            'left_idx': l1_idx, 'left_price': l1_price,
            'left_date': dates[l1_idx], 'left_vol': l1_vol,
            'right_idx': l2_idx, 'right_price': l2_price,
            'right_date': dates[l2_idx], 'right_vol': l2_vol,
            'neck_idx': n_idx, 'neck_price': n_price,
            'neck_date': dates[n_idx],
            'break_idx': break_idx, 'break_date': dates[break_idx],
            'gap': gap,
            'price_diff_pct': abs(l1_price - l2_price) / min(l1_price, l2_price),
            'height_pct': neck_height_pct,
            'left_macd': macd[l1_idx], 'right_macd': macd[l2_idx],
            'left_rsi': rsi[l1_idx], 'right_rsi': rsi[l2_idx],
            'break_vol': volumes[break_idx],
            'break_vol_ma20': vol_ma20[break_idx],
            'break_vol_ratio': volumes[break_idx] / vol_ma20[break_idx] if vol_ma20[break_idx] and vol_ma20[break_idx] > 0 else 1,
        })

    return results


def score_pattern_v2(df, pattern, end_date):
    """优化版评分"""
    score = 0; reasons = []
    end_idx = None
    for i, d in enumerate(df):
        if d['trade_date'] == end_date: end_idx = i; break
    if end_idx is None: end_idx = len(df) - 1

    current_price = float(df[end_idx]['close'])
    neck_price = pattern['neck_price']

    if current_price <= neck_price: return -1, []
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05: return -1, []

    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space = (target - current_price) / current_price
    if space < 0.08: return -1, []

    break_idx = pattern['break_idx']
    days_since_break = end_idx - break_idx
    if days_since_break <= 3: score += 25; reasons.append(f'刚刚突破({days_since_break}天前)')
    elif days_since_break <= 5: score += 20; reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 10: score += 15; reasons.append(f'突破{days_since_break}天')
    else: score += 5; reasons.append(f'突破已{days_since_break}天(较久)')

    if pattern['left_vol'] > 0:
        vol_ratio = pattern['right_vol'] / pattern['left_vol']
        if vol_ratio < 0.3: score += 20; reasons.append(f'右底极度缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.5: score += 18; reasons.append(f'右底显著缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.7: score += 12; reasons.append(f'右底缩量({vol_ratio:.0%})')

    gap = pattern['gap']
    if gap >= 30: score += 15; reasons.append(f'形态跨度大({gap}根K线)')
    elif gap >= 20: score += 10; reasons.append(f'形态跨度适中({gap}根K线)')

    if pattern['right_macd'] > pattern['left_macd'] and pattern['left_price'] >= pattern['right_price']:
        score += 15; reasons.append('MACD底背离')
    elif pattern['right_macd'] > pattern['left_macd']:
        score += 10; reasons.append('MACD改善')

    if pattern['right_price'] > pattern['left_price']:
        score += 10; reasons.append('右底高于左底(抬高低点)')
    elif abs(pattern['right_price'] - pattern['left_price']) / pattern['left_price'] < 0.01:
        score += 8; reasons.append('两底齐平(强支撑)')

    h = pattern['height_pct']
    if 0.10 <= h <= 0.25: score += 10; reasons.append(f'振幅理想({h:.1%})')
    elif 0.08 <= h < 0.10: score += 7; reasons.append(f'振幅合理({h:.1%})')

    if pattern['right_rsi'] > pattern['left_rsi'] and pattern['left_price'] >= pattern['right_price']:
        score += 5; reasons.append('RSI底背离')

    # 新增：突破放量加分
    bvr = pattern.get('break_vol_ratio', 1)
    if bvr >= 2.5: score += 5; reasons.append(f'突破巨量({bvr:.1f}x)')
    elif bvr >= 2.0: score += 3; reasons.append(f'突破显著放量({bvr:.1f}x)')

    return score, reasons

def add_months(date_str, months):
    dt = datetime.strptime(date_str, '%Y%m%d')
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, 28)
    return datetime(year, month, day).strftime('%Y%m%d')

def simulate_trade(df, entry_date, entry_price, target_price, stop_loss_price):
    entry_idx = None
    for i, d in enumerate(df):
        if d['trade_date'] == entry_date: entry_idx = i; break
    if entry_idx is None or entry_idx + 1 >= len(df): return entry_date, entry_price, 'no_data', 0.0
    for i in range(entry_idx + 1, len(df)):
        low = float(df[i]['low']); high = float(df[i]['high']); date = df[i]['trade_date']
        if low <= stop_loss_price:
            ret = (stop_loss_price - entry_price) / entry_price
            return date, stop_loss_price, 'stop_loss', ret
        if high >= target_price:
            ret = (target_price - entry_price) / entry_price
            return date, target_price, 'take_profit', ret
    final_price = float(df[-1]['close'])
    ret = (final_price - entry_price) / entry_price
    return df[-1]['trade_date'], final_price, 'hold_expiry', ret

# ============ 主程序 ============

def run_backtest(scan_date):
    scan_start = add_months(scan_date, -18)
    forward_end = add_months(scan_date, HOLD_MONTHS + 2)
    double_bottom_start = add_months(scan_date, -6)

    print("=" * 80)
    print(f"双底形态回测 v2 (优化参数) | 基准日: {scan_date}")
    print(f"每只: ¥{INITIAL_CAPITAL_PER_STOCK:,} | 止损: {STOP_LOSS_PCT:.0%} | 持有: {HOLD_MONTHS}个月")
    print(f"颈线>10% | 突破放量>1.5xMA20 | 突破后3天不回踩颈线×0.98")
    print("=" * 80)

    print("\n[1/4] 获取股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}
    hs300 = get_hs300_components()
    zz500 = get_zz500_components()
    all_codes = set((hs300 or []) + (zz500 or []))
    scan_codes = [c for c in all_codes if c in stock_map]
    print(f"  扫描池: {len(scan_codes)} 只")

    print(f"\n[2/4] 扫描双底形态 v2...")
    all_candidates = []; found = 0
    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0: print(f"  进度: {idx}/{len(scan_codes)}, 发现{found}个候选")
        try:
            hist_data = get_daily_data(code, scan_start, scan_date)
            if not hist_data or len(hist_data) < 60: continue
            patterns = detect_double_bottom_v2(hist_data, window=8, double_bottom_start=double_bottom_start)
            name = stock_map.get(code, code)
            for p in patterns:
                score, reasons = score_pattern_v2(hist_data, p, scan_date)
                if score >= 40:
                    all_candidates.append({'code': code, 'name': name, 'pattern': p, 'score': score, 'reasons': reasons, 'hist_data': hist_data})
                    found += 1
            time.sleep(0.12)
        except: continue
    print(f"  扫描完成: 发现{found}个候选")

    print(f"\n[3/4] 筛选Top 5...")
    deduped = {}
    for c in all_candidates:
        code = c['code']
        if code not in deduped or c['score'] > deduped[code]['score']: deduped[code] = c
    unique = list(deduped.values())
    unique.sort(key=lambda x: (len(x['hist_data'])-1-x['pattern']['break_idx'], -x['score']))
    top5 = unique[:5]
    print(f"  去重后 {len(unique)} 只，取 Top 5:")
    for i, item in enumerate(top5):
        p = item['pattern']
        end_idx = len(item['hist_data']) - 1
        for j, d in enumerate(item['hist_data']):
            if d['trade_date'] == scan_date: end_idx = j; break
        days_ago = end_idx - p['break_idx']
        cp = float(item['hist_data'][end_idx]['close'])
        min_b = min(p['left_price'], p['right_price'])
        target = p['neck_price'] + (p['neck_price'] - min_b)
        space = (target - cp) / cp * 100
        print(f"  {i+1}. {item['name']} ({item['code']}) 评分:{item['score']} "
              f"突破:{p['break_date']} ({days_ago}天前) "
              f"颈线:{p['neck_price']:.2f} ({p['height_pct']:.0%}) "
              f"现价:{cp:.2f} 空间:{space:.1f}% "
              f"突破量比:{p['break_vol_ratio']:.1f}x")

    if not top5:
        print("\n  ⚠ 无符合条件的股票"); return

    print(f"\n[4/4] 模拟交易...")
    trades = []
    for i, item in enumerate(top5):
        code = item['code']; p = item['pattern']
        print(f"  [{i+1}/5] {item['name']} ({code})...", end=' ')
        future_data = get_daily_data(code, scan_date, forward_end)
        if not future_data or len(future_data) < 2: print("⚠ 数据不足"); continue
        entry_date = scan_date; entry_price = None
        for d in future_data:
            if d['trade_date'] == entry_date: entry_price = float(d['close']); break
        if entry_price is None: entry_date = future_data[0]['trade_date']; entry_price = float(future_data[0]['close'])
        min_bottom = min(p['left_price'], p['right_price'])
        target_price = p['neck_price'] + (p['neck_price'] - min_bottom)
        stop_loss_price = entry_price * (1 - STOP_LOSS_PCT)
        exit_date, exit_price, reason, ret = simulate_trade(future_data, entry_date, entry_price, target_price, stop_loss_price)
        shares = INITIAL_CAPITAL_PER_STOCK / entry_price; pnl = shares * exit_price - INITIAL_CAPITAL_PER_STOCK
        trade = {'code': code, 'name': item['name'], 'entry_date': entry_date, 'entry_price': entry_price, 'exit_date': exit_date, 'exit_price': exit_price, 'target_price': target_price, 'stop_loss_price': stop_loss_price, 'reason': reason, 'return_pct': ret, 'pnl': pnl, 'score': item['score'], 'reasons': item['reasons'], 'neck_price': p['neck_price'], 'left_price': p['left_price'], 'right_price': p['right_price'], 'height_pct': p['height_pct'], 'break_vol_ratio': p['break_vol_ratio']}
        trades.append(trade)
        reason_cn = {'stop_loss': '止损', 'take_profit': '止盈', 'hold_expiry': '到期', 'no_data': '无数据'}
        print(f"✓ 买入@{entry_price:.2f}({entry_date}) → 卖出@{exit_price:.2f}({exit_date}) [{reason_cn.get(reason, reason)}] {ret:+.2%} (¥{pnl:+,.0f})")

    print(f"\n{'=' * 80}")
    print(f"回测报告 v2")
    print(f"{'=' * 80}")
    print(f"{'序号':<4} {'代码':<10} {'名称':<8} {'评分':>5} {'颈线高度':>8} {'买入价':>8} {'卖出价':>8} {'原因':<8} {'收益率':>8} {'盈亏':>12}")
    print("-" * 80)
    total_pnl = 0; win_count = 0
    for i, t in enumerate(trades):
        reason_cn = {'stop_loss': '止损', 'take_profit': '止盈', 'hold_expiry': '到期', 'no_data': '无数据'}
        print(f"{i+1:<4} {t['code']:<10} {t['name']:<8} {t['score']:>5} {t['height_pct']:>7.0%} "
              f"{t['entry_price']:>8.2f} {t['exit_price']:>8.2f} {reason_cn.get(t['reason'], t['reason']):<8} "
              f"{t['return_pct']:>+7.2%} ¥{t['pnl']:>+11,.0f}")
        total_pnl += t['pnl']; 
        if t['pnl'] > 0: win_count += 1
    total_invested = len(trades) * INITIAL_CAPITAL_PER_STOCK
    total_return = total_pnl / total_invested if total_invested > 0 else 0
    win_rate = win_count / len(trades) * 100 if trades else 0
    print("-" * 80)
    print(f"总投入:   ¥{total_invested:>12,.0f}")
    print(f"总盈亏:   ¥{total_pnl:>12,.0f}")
    print(f"总收益率: {total_return:+.2%}")
    print(f"胜率:     {win_rate:.0f}% ({win_count}/{len(trades)})")
    print(f"{'=' * 80}")
    return trades

if __name__ == '__main__':
    scan_date = sys.argv[1].replace('-', '') if len(sys.argv) > 1 else '20260120'
    run_backtest(scan_date)
