"""
双底形态回测系统
================
输入：扫描基准日期（如 2026-01-20）
流程：
  1. 以输入日期为 END_DATE 扫描沪深300+中证500双底
  2. 选出前5名（评分>=40，突破后空间>=8%）
  3. 每只仿真买入100,000元
  4. 跟踪未来3个月每日价格：
     - 回撤≥3% → 止损卖出
     - 触及目标位 → 止盈卖出
     - 否则持有到期
  5. 计算最终收益
"""

import urllib.request
import json
import os
import sys
import time
from datetime import datetime, timedelta

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'

# 回测参数
INITIAL_CAPITAL_PER_STOCK = 100_000  # 每只买入金额
STOP_LOSS_PCT = 0.04                  # 止损：回撤4%
HOLD_MONTHS = 3                       # 持有期3个月

# ============ Tushare API 封装 ============

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields:
        payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') != 0:
            return None
        return result.get('data', {})
    except Exception:
        return None

def get_stock_list():
    result = api_call('stock_basic', fields='ts_code,symbol,name,industry,list_status')
    if not result or 'fields' not in result or 'items' not in result:
        return []
    fields = result['fields']
    return [dict(zip(fields, item)) for item in result['items']
            if dict(zip(fields, item)).get('list_status') == 'L']

def get_hs300_components():
    result = api_call('index_weight', index_code='399300.SZ', fields='con_code')
    if not result or 'items' not in result:
        return None
    return list(set(item[0] for item in result['items']))

def get_zz500_components():
    result = api_call('index_weight', index_code='000905.SH', fields='con_code')
    if not result or 'items' not in result:
        return []
    return list(set(item[0] for item in result['items']))

def get_daily_data(ts_code, start_date, end_date):
    """获取日线数据，返回按日期升序排列的列表"""
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result:
        return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df


# ============ 技术指标 ============

def calc_macd(closes):
    n = len(closes)
    def ema(data, span):
        k = 2.0 / (span + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(n)]
    dea = ema(dif, 9)
    return [2 * (dif[i] - dea[i]) for i in range(n)]

def calc_rsi(closes, period=14):
    n = len(closes)
    rsi = [50.0] * n
    if n < period + 1:
        return rsi
    gains, losses = [], []
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, n - 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


# ============ 双底检测 ============

def detect_double_bottom(df, window=8, double_bottom_start=None):
    """检测双底形态"""
    n = len(df)
    if n < window * 2 + 1:
        return []

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)

    # 找局部高低点
    lows, highs = [], []
    for i in range(window, n - window):
        price = closes[i]
        if all(closes[j] > price for j in range(max(0, i - window), min(n, i + window + 1)) if j != i):
            lows.append((i, price, volumes[i]))
        if all(closes[j] < price for j in range(max(0, i - window), min(n, i + window + 1)) if j != i):
            highs.append((i, price))

    if len(lows) < 2 or len(highs) < 1:
        return []

    results = []
    for i in range(len(lows) - 1):
        l1_idx, l1_price, l1_vol = lows[i]
        l2_idx, l2_price, l2_vol = lows[i + 1]

        # 间距要求
        gap = l2_idx - l1_idx
        if gap < 15 or gap > 150:
            continue

        # 价格接近
        if abs(l1_price - l2_price) / min(l1_price, l2_price) > 0.05:
            continue

        # 找颈线（两底之间的最高点）
        necks = [h for h in highs if l1_idx < h[0] < l2_idx]
        if not necks:
            continue
        n_idx, n_price = max(necks, key=lambda x: x[1])
        if n_price / min(l1_price, l2_price) < 1.05:
            continue

        # 双底开始时间过滤
        if double_bottom_start and dates[l1_idx] < double_bottom_start:
            continue

        # 检查突破颈线（从右底之后开始找）
        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:  # 突破1%算有效
                break_idx = j
                break

        if break_idx is None:
            continue  # 未突破

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
            'height_pct': (n_price - min(l1_price, l2_price)) / min(l1_price, l2_price),
            'left_macd': macd[l1_idx], 'right_macd': macd[l2_idx],
            'left_rsi': rsi[l1_idx], 'right_rsi': rsi[l2_idx],
        })

    return results


def score_pattern(df, pattern, end_date):
    """评分 (0-100)
    
    注意：回测模式下，end_date 是扫描基准日，
    current_price = 基准日的收盘价
    """
    score = 0
    reasons = []

    # 找到 end_date 在 df 中的位置
    end_idx = None
    for i, d in enumerate(df):
        if d['trade_date'] == end_date:
            end_idx = i
            break
    if end_idx is None:
        # 如果找不到精确匹配，用最后一个交易日
        end_idx = len(df) - 1

    current_price = float(df[end_idx]['close'])
    neck_price = pattern['neck_price']

    # === 核心过滤 ===
    if current_price <= neck_price:
        return -1, []  # 未突破

    # 突破幅度不能超过5%
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05:
        return -1, []

    # 计算目标位及剩余空间
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08:
        return -1, []  # 空间不足

    # === 评分项 ===

    # 1. 突破新鲜度 (25分)
    break_idx = pattern['break_idx']
    days_since_break = end_idx - break_idx
    if days_since_break <= 3:
        score += 25
        reasons.append(f'刚刚突破({days_since_break}天前)')
    elif days_since_break <= 5:
        score += 20
        reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 10:
        score += 15
        reasons.append(f'突破{days_since_break}天')
    else:
        score += 5
        reasons.append(f'突破已{days_since_break}天(较久)')

    # 2. 右底缩量 (20分)
    if pattern['left_vol'] > 0:
        vol_ratio = pattern['right_vol'] / pattern['left_vol']
        if vol_ratio < 0.3:
            score += 20
            reasons.append(f'右底极度缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.5:
            score += 18
            reasons.append(f'右底显著缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.7:
            score += 12
            reasons.append(f'右底缩量({vol_ratio:.0%})')

    # 3. 形态跨度 (15分)
    gap = pattern['gap']
    if gap >= 30:
        score += 15
        reasons.append(f'形态跨度大({gap}根K线)')
    elif gap >= 20:
        score += 10
        reasons.append(f'形态跨度适中({gap}根K线)')

    # 4. MACD底背离 (15分)
    if pattern['right_macd'] > pattern['left_macd'] and pattern['left_price'] >= pattern['right_price']:
        score += 15
        reasons.append('MACD底背离')
    elif pattern['right_macd'] > pattern['left_macd']:
        score += 10
        reasons.append('MACD改善')

    # 5. 右底高于左底 (10分)
    if pattern['right_price'] > pattern['left_price']:
        score += 10
        reasons.append('右底高于左底(抬高低点)')
    elif abs(pattern['right_price'] - pattern['left_price']) / pattern['left_price'] < 0.01:
        score += 8
        reasons.append('两底齐平(强支撑)')

    # 6. 振幅合理 (10分)
    h = pattern['height_pct']
    if 0.10 <= h <= 0.25:
        score += 10
        reasons.append(f'振幅理想({h:.1%})')
    elif 0.08 <= h < 0.10:
        score += 7
        reasons.append(f'振幅合理({h:.1%})')

    # 7. RSI底背离 (5分)
    if pattern['right_rsi'] > pattern['left_rsi'] and pattern['left_price'] >= pattern['right_price']:
        score += 5
        reasons.append('RSI底背离')

    return score, reasons


# ============ 回测引擎 ============

def add_months(date_str, months):
    """日期加N个月"""
    dt = datetime.strptime(date_str, '%Y%m%d')
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, 28)  # 简化处理月末
    return datetime(year, month, day).strftime('%Y%m%d')

def simulate_trade(df, entry_date, entry_price, target_price, stop_loss_price):
    """
    模拟交易：从 entry_date 的下一个交易日开始持有
    返回: (exit_date, exit_price, reason, return_pct)
    reason: 'stop_loss', 'take_profit', 'hold_expiry'
    """
    # 找到 entry_date 在 df 中的位置
    entry_idx = None
    for i, d in enumerate(df):
        if d['trade_date'] == entry_date:
            entry_idx = i
            break

    if entry_idx is None or entry_idx + 1 >= len(df):
        return entry_date, entry_price, 'no_data', 0.0

    # 从下一个交易日开始跟踪
    for i in range(entry_idx + 1, len(df)):
        low = float(df[i]['low'])
        high = float(df[i]['high'])
        close = float(df[i]['close'])
        date = df[i]['trade_date']

        # 先用最低价检查止损（日内触及即触发）
        if low <= stop_loss_price:
            ret = (stop_loss_price - entry_price) / entry_price
            return date, stop_loss_price, 'stop_loss', ret

        # 检查止盈（日内触及即触发）
        if high >= target_price:
            ret = (target_price - entry_price) / entry_price
            return date, target_price, 'take_profit', ret

    # 持有到期
    final_price = float(df[-1]['close'])
    ret = (final_price - entry_price) / entry_price
    return df[-1]['trade_date'], final_price, 'hold_expiry', ret


def run_backtest(scan_date):
    """
    运行回测
    
    参数:
        scan_date: str, 扫描基准日期, 格式 YYYYMMDD
    """
    # 计算数据范围
    scan_start = add_months(scan_date, -18)  # 回看18个月用于形态检测
    forward_end = add_months(scan_date, HOLD_MONTHS + 1)  # 向前3个月+1个月buffer

    # 双底形态开始时间：基准日前6个月（相对过滤，而非绝对日期）
    double_bottom_start = add_months(scan_date, -6)

    print("=" * 70)
    print(f"双底形态回测系统")
    print(f"扫描基准日: {scan_date[:4]}-{scan_date[4:6]}-{scan_date[6:]}")
    print(f"持有期: {HOLD_MONTHS}个月 (至 {forward_end[:4]}-{forward_end[4:6]}-{forward_end[6:]})")
    print(f"每只买入金额: ¥{INITIAL_CAPITAL_PER_STOCK:,.0f}")
    print(f"止损: {STOP_LOSS_PCT:.0%} | 止盈: 量度目标位")
    print("=" * 70)

    # ---- Step 1: 获取股票列表 ----
    print("\n[1/5] 获取股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}

    hs300 = get_hs300_components()
    zz500 = get_zz500_components()
    all_codes = set((hs300 or []) + (zz500 or []))
    scan_codes = [c for c in all_codes if c in stock_map]
    print(f"  沪深300+中证500 共 {len(scan_codes)} 只")

    # ---- Step 2: 扫描双底 ----
    print(f"\n[2/5] 扫描双底形态 (基准日: {scan_date})...")
    all_candidates = []
    scanned = 0
    found = 0

    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0:
            print(f"  进度: {idx}/{len(scan_codes)}, 已发现{found}个候选")

        try:
            # 获取历史数据（用于形态检测）
            hist_data = get_daily_data(code, scan_start, scan_date)
            if not hist_data or len(hist_data) < 60:
                continue

            patterns = detect_double_bottom(hist_data, window=8,
                                            double_bottom_start=double_bottom_start)

            name = stock_map.get(code, code)
            for p in patterns:
                score, reasons = score_pattern(hist_data, p, scan_date)
                if score >= 40:
                    all_candidates.append({
                        'code': code, 'name': name,
                        'pattern': p, 'score': score, 'reasons': reasons,
                        'hist_data': hist_data,
                    })
                    found += 1
            time.sleep(0.12)
            scanned += 1
        except:
            continue

    print(f"  扫描完成: {scanned}只, 发现{found}个候选")

    # ---- Step 3: 去重 + 排序 + 选Top 5 ----
    print(f"\n[3/5] 筛选Top 5...")

    # 去重：每只股票保留最高分
    deduped = {}
    for c in all_candidates:
        code = c['code']
        if code not in deduped or c['score'] > deduped[code]['score']:
            deduped[code] = c

    unique_candidates = list(deduped.values())
    # 排序：突破越近越好（主要），评分越高越好（次要）
    unique_candidates.sort(key=lambda x: (
        x['hist_data'][-1]['trade_date'] == scan_date and
        (len(x['hist_data']) - 1 - x['pattern']['break_idx']),
        -x['score']
    ))

    top5 = unique_candidates[:5]
    print(f"  去重后 {len(unique_candidates)} 只，取 Top 5:")
    for i, item in enumerate(top5):
        p = item['pattern']
        end_idx = len(item['hist_data']) - 1
        for j, d in enumerate(item['hist_data']):
            if d['trade_date'] == scan_date:
                end_idx = j
                break
        days_ago = end_idx - p['break_idx']
        cp = float(item['hist_data'][end_idx]['close'])
        min_b = min(p['left_price'], p['right_price'])
        target = p['neck_price'] + (p['neck_price'] - min_b)
        space = (target - cp) / cp * 100
        print(f"  {i+1}. {item['name']} ({item['code']}) 评分:{item['score']} "
              f"突破:{p['break_date']} ({days_ago}天前) "
              f"颈线:{p['neck_price']:.2f} 现价:{cp:.2f} 空间:{space:.1f}%")

    if not top5:
        print("\n  ⚠ 无符合条件的股票，回测结束")
        return

    # ---- Step 4: 获取未来数据并模拟交易 ----
    print(f"\n[4/5] 获取未来{HOLD_MONTHS}个月数据并模拟交易...")
    # 获取所有top5股票的未来数据
    next_day_start = scan_date  # 从基准日之后开始

    trades = []
    for i, item in enumerate(top5):
        code = item['code']
        name = item['name']
        p = item['pattern']

        print(f"  [{i+1}/5] {name} ({code})...", end=' ')

        # 获取未来数据
        future_data = get_daily_data(code, scan_date, forward_end)
        if not future_data or len(future_data) < 2:
            print("⚠ 未来数据不足，跳过")
            continue

        # 找到 entry_date（扫描基准日）在 future_data 中的收盘价作为买入价
        entry_date = scan_date
        entry_price = None
        for d in future_data:
            if d['trade_date'] == entry_date:
                entry_price = float(d['close'])
                break

        if entry_price is None:
            # 如果基准日没有数据（非交易日），用第一个交易日
            entry_date = future_data[0]['trade_date']
            entry_price = float(future_data[0]['close'])

        # 计算目标价和止损价
        min_bottom = min(p['left_price'], p['right_price'])
        target_price = p['neck_price'] + (p['neck_price'] - min_bottom)
        stop_loss_price = entry_price * (1 - STOP_LOSS_PCT)

        # 模拟交易
        exit_date, exit_price, reason, ret = simulate_trade(
            future_data, entry_date, entry_price, target_price, stop_loss_price
        )

        buy_shares = INITIAL_CAPITAL_PER_STOCK / entry_price
        final_value = buy_shares * exit_price
        pnl = final_value - INITIAL_CAPITAL_PER_STOCK

        trade = {
            'code': code, 'name': name,
            'entry_date': entry_date, 'entry_price': entry_price,
            'exit_date': exit_date, 'exit_price': exit_price,
            'target_price': target_price, 'stop_loss_price': stop_loss_price,
            'reason': reason, 'return_pct': ret,
            'shares': buy_shares, 'pnl': pnl,
            'score': item['score'], 'reasons': item['reasons'],
            'neck_price': p['neck_price'],
            'left_price': p['left_price'], 'right_price': p['right_price'],
        }
        trades.append(trade)

        reason_cn = {'stop_loss': '止损', 'take_profit': '止盈', 'hold_expiry': '持有到期', 'no_data': '无数据'}
        print(f"✓ 买入@{entry_price:.2f}({entry_date}) → "
              f"卖出@{exit_price:.2f}({exit_date}) "
              f"[{reason_cn.get(reason, reason)}] "
              f"收益: {ret:+.2%} (¥{pnl:+,.0f})")

    # ---- Step 5: 输出报告 ----
    print(f"\n[5/5] 回测报告")
    print("=" * 70)
    print(f"{'序号':<4} {'代码':<10} {'名称':<8} {'买入日':<10} {'买入价':>8} "
          f"{'卖出日':<10} {'卖出价':>8} {'原因':<8} {'收益率':>8} {'盈亏':>12}")
    print("-" * 70)

    total_pnl = 0
    total_invested = 0
    win_count = 0

    for i, t in enumerate(trades):
        reason_cn = {'stop_loss': '止损', 'take_profit': '止盈',
                     'hold_expiry': '持有到期', 'no_data': '无数据'}
        print(f"{i+1:<4} {t['code']:<10} {t['name']:<8} {t['entry_date']:<10} "
              f"{t['entry_price']:>8.2f} {t['exit_date']:<10} {t['exit_price']:>8.2f} "
              f"{reason_cn.get(t['reason'], t['reason']):<8} "
              f"{t['return_pct']:>+7.2%} ¥{t['pnl']:>+11,.0f}")
        total_pnl += t['pnl']
        total_invested += INITIAL_CAPITAL_PER_STOCK
        if t['pnl'] > 0:
            win_count += 1

    print("-" * 70)
    total_return = total_pnl / total_invested if total_invested > 0 else 0
    win_rate = win_count / len(trades) * 100 if trades else 0
    final_capital = total_invested + total_pnl

    print(f"\n总投入:       ¥{total_invested:>12,.0f}  ({len(trades)}只 × ¥{INITIAL_CAPITAL_PER_STOCK:,})")
    print(f"最终资产:     ¥{final_capital:>12,.0f}")
    print(f"总盈亏:       ¥{total_pnl:>12,.0f}")
    print(f"总收益率:     {total_return:+.2%}")
    print(f"胜率:         {win_rate:.0f}% ({win_count}/{len(trades)})")
    print("=" * 70)

    # 详细交易说明
    print(f"\n详细交易记录:")
    for i, t in enumerate(trades):
        print(f"\n  --- 交易 {i+1}: {t['name']} ({t['code']}) ---")
        print(f"  评分: {t['score']}/100 | 上榜理由: {', '.join(t['reasons'][:4])}")
        print(f"  左底: {t['left_price']:.2f} | 右底: {t['right_price']:.2f} | 颈线: {t['neck_price']:.2f}")
        print(f"  量度目标: {t['target_price']:.2f}")
        print(f"  买入: {t['entry_date']} @ {t['entry_price']:.2f} ({t['shares']:.0f}股)")
        print(f"  止损价: {t['stop_loss_price']:.2f} (-{STOP_LOSS_PCT:.0%})")
        print(f"  卖出: {t['exit_date']} @ {t['exit_price']:.2f} [{t['reason']}]")
        print(f"  收益率: {t['return_pct']:+.2%} | 盈亏: ¥{t['pnl']:+,.0f}")

    return trades


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        scan_date = sys.argv[1].replace('-', '')
    else:
        scan_date = '20260120'
    run_backtest(scan_date)
