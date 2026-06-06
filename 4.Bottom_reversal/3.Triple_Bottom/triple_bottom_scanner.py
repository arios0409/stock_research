"""
三重底形态扫描器 (Triple Bottom)
条件:
- 三个连续低点，价格接近 (偏差 < 5%)
- 低点之间有反弹高点形成阻力位
- 突破阻力位且距离越近越好
- 距目标位剩余空间 >= 8%
"""

import urllib.request
import json
import os
import time
import math
import statistics

# ============ 配置 ============
TUSHARE_TOKEN='026586...ad60'
API_URL = 'http://api.tushare.pro'
END_DATE = '20260517'
START_DATE = '20241001'
PATTERN_START = '20251201'
MAX_SCAN = 400

# ============ Tushare API 封装 ============

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

def get_daily_data(ts_code, start_date=START_DATE, end_date=END_DATE):
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
    ema12, ema26 = ema(closes, 12), ema(closes, 26)
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

# ============ 三重底检测 ============

def detect_triple_bottom(df, window=10):
    """
    检测三重底形态:
    - 三个连续低点，价格接近
    - 每两个低点之间有反弹高点
    - 第三个底 > 前两个底为佳（抬高低点）
    """
    n = len(df)
    if n < window * 3 + 1: return []

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)

    # 找局部低点和高点
    lows, highs = [], []
    for i in range(window, n - window):
        price = closes[i]
        if all(closes[j] > price for j in range(max(0, i-window), min(n, i+window+1)) if j != i):
            lows.append((i, price, volumes[i]))
        if all(closes[j] < price for j in range(max(0, i-window), min(n, i+window+1)) if j != i):
            highs.append((i, price))

    if len(lows) < 3 or len(highs) < 2: return []

    results = []
    for i in range(len(lows) - 2):
        b1_idx, b1_price, b1_vol = lows[i]
        b2_idx, b2_price, b2_vol = lows[i + 1]
        b3_idx, b3_price, b3_vol = lows[i + 2]

        # 三个底价格接近 (任意两两偏差 < 6%)
        prices = [b1_price, b2_price, b3_price]
        avg_p = statistics.mean(prices)
        if max(abs(p - avg_p) / avg_p for p in prices) > 0.06:
            continue

        # 间距合理
        gap12 = b2_idx - b1_idx
        gap23 = b3_idx - b2_idx
        if gap12 < 10 or gap12 > 120: continue
        if gap23 < 10 or gap23 > 120: continue

        # 找阻力位: b1→b2之间和b2→b3之间的最高点
        resist1 = [h for h in highs if b1_idx < h[0] < b2_idx]
        resist2 = [h for h in highs if b2_idx < h[0] < b3_idx]
        if not resist1 or not resist2: continue

        r1_idx, r1_price = max(resist1, key=lambda x: x[1])
        r2_idx, r2_price = max(resist2, key=lambda x: x[1])

        # 阻力位: 取两个高点中较高的
        resistance_price = max(r1_price, r2_price)
        resistance_idx = r2_idx if r2_price > r1_price else r1_idx

        # 阻力位必须明显高于底部
        if resistance_price / avg_p < 1.05: continue

        # 检查突破阻力位
        break_idx = None
        for j in range(b3_idx, n):
            if closes[j] > resistance_price * 1.01:
                break_idx = j
                break

        if break_idx is None: continue  # 未突破

        # 形态必须在指定时间范围内
        if dates[b1_idx] < PATTERN_START: continue

        results.append({
            'b1_idx': b1_idx, 'b1_price': b1_price, 'b1_date': dates[b1_idx], 'b1_vol': b1_vol,
            'b2_idx': b2_idx, 'b2_price': b2_price, 'b2_date': dates[b2_idx], 'b2_vol': b2_vol,
            'b3_idx': b3_idx, 'b3_price': b3_price, 'b3_date': dates[b3_idx], 'b3_vol': b3_vol,
            'resistance_price': resistance_price, 'resistance_idx': resistance_idx,
            'break_idx': break_idx, 'break_date': dates[break_idx],
            'height_pct': (resistance_price - avg_p) / avg_p,
            'price_spread': max(prices) - min(prices),
            'b1_macd': macd[b1_idx], 'b2_macd': macd[b2_idx], 'b3_macd': macd[b3_idx],
            'b1_rsi': rsi[b1_idx], 'b2_rsi': rsi[b2_idx], 'b3_rsi': rsi[b3_idx],
            'closes': closes, 'volumes': volumes, 'dates': dates
        })

    return results

def score_triple_bottom(df, pattern):
    """评分 (0-100)"""
    score = 0
    reasons = []
    current_price = float(df[-1]['close'])
    n = len(df)
    resistance = pattern['resistance_price']

    # === 核心过滤 ===
    if current_price <= resistance: return -1, []

    dist = (current_price - resistance) / resistance
    if dist > 0.05: return -1, []

    # 目标位
    min_bottom = min(pattern['b1_price'], pattern['b2_price'], pattern['b3_price'])
    target = resistance + (resistance - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08: return -1, []

    # === 评分项 ===

    # 1. 突破新鲜度 (25分)
    break_idx = pattern['break_idx']
    days_since_break = n - 1 - break_idx
    if days_since_break <= 3: score += 25; reasons.append(f'刚刚突破({days_since_break}天前)')
    elif days_since_break <= 5: score += 20; reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 10: score += 15; reasons.append(f'突破{days_since_break}天')
    else: score += 5; reasons.append(f'突破已{days_since_break}天(较久)')

    # 2. 成交量递减 (20分) — 三重底的成交量应该依次减少
    b1_vol, b2_vol, b3_vol = pattern['b1_vol'], pattern['b2_vol'], pattern['b3_vol']
    if b1_vol > 0 and b3_vol > 0:
        vol_ratio = b3_vol / b1_vol
        if vol_ratio < 0.3: score += 20; reasons.append(f'第三底极度缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.5: score += 18; reasons.append(f'成交量显著递减({vol_ratio:.0%})')
        elif vol_ratio < 0.7: score += 12; reasons.append(f'成交量递减({vol_ratio:.0%})')

    # 3. 形态跨度 (15分)
    total_gap = pattern['b3_idx'] - pattern['b1_idx']
    if total_gap >= 80: score += 15; reasons.append(f'形态跨度大({total_gap}根K线)')
    elif total_gap >= 40: score += 10; reasons.append(f'形态跨度适中({total_gap}根K线)')

    # 4. MACD三重底背离 (15分)
    if pattern['b3_macd'] > pattern['b2_macd'] > pattern['b1_macd']:
        score += 15; reasons.append('MACD三重底背离(逐底改善)')
    elif pattern['b3_macd'] > pattern['b1_macd']:
        score += 10; reasons.append('MACD改善')

    # 5. 第三底高于前两底 (10分) — 抬高低点
    if pattern['b3_price'] > pattern['b1_price'] and pattern['b3_price'] > pattern['b2_price']:
        score += 10; reasons.append('第三底抬高(底点逐次上移)')
    elif pattern['b3_price'] > pattern['b1_price']:
        score += 7; reasons.append('第三底高于第一底')

    # 6. 三个底价格紧凑 (10分) — 越紧凑支撑越强
    spread_pct = pattern['price_spread'] / min(pattern['b1_price'], pattern['b2_price'], pattern['b3_price'])
    if spread_pct < 0.02: score += 10; reasons.append(f'三底极紧凑(偏差{spread_pct:.1%})')
    elif spread_pct < 0.04: score += 7; reasons.append(f'三底紧凑(偏差{spread_pct:.1%})')

    # 7. RSI三重底背离 (5分)
    if pattern['b3_rsi'] > pattern['b2_rsi'] > pattern['b1_rsi']:
        score += 5; reasons.append('RSI逐底改善')

    return score, reasons


# ============ SVG 绘图 ============

def format_date(ds): return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"

def draw_svg_chart(df, pattern, score, reasons, stock_name, stock_code, save_path):
    W, H = 1000, 700
    margin = {'top': 50, 'right': 80, 'bottom': 100, 'left': 70}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.65; vol_h = chart_h * 0.25; gap_h = chart_h * 0.1

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    n = len(df)

    min_p = min(closes) * 0.93; max_p = max(closes) * 1.05
    max_v = max(volumes) * 1.2

    def px(i): return margin['left'] + (i / (n - 1)) * chart_w
    def py(price): return margin['top'] + (1 - (price - min_p) / (max_p - min_p)) * price_h
    def vy(vol): return margin['top'] + price_h + gap_h + (1 - vol / max_v) * vol_h

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           f'<rect width="{W}" height="{H}" fill="#1a1a2e"/>',
           f'<text x="{W/2}" y="28" text-anchor="middle" font-size="16" fill="#e0e0e0" font-weight="bold">{stock_name} ({stock_code})  三重底突破  评分:{score}/100</text>']

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i; yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#2a2a4a" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-5}" y="{yy+4}" text-anchor="end" font-size="10" fill="#888">{gp:.2f}</text>')

    # 日期
    for i in range(0, n, max(1, n//8)):
        svg.append(f'<text x="{px(i)}" y="{margin["top"]+price_h+15}" text-anchor="middle" font-size="9" fill="#888">{format_date(dates[i])}</text>')

    # 三重底区域高亮
    hl_start = max(0, pattern['b1_idx']-10); hl_end = min(n-1, pattern['break_idx']+5)
    svg.append(f'<rect x="{px(hl_start)}" y="{margin["top"]}" width="{px(hl_end)-px(hl_start)}" height="{price_h+vol_h+gap_h}" fill="#4CAF50" opacity="0.08"/>')

    # 成交量柱
    for i in range(n):
        bar_w = max(1, chart_w/n*0.7); x = px(i)-bar_w/2; y = vy(volumes[i])
        bh = margin['top']+price_h+gap_h+vol_h - y
        color = '#4CAF50' if closes[i] >= (closes[i-1] if i>0 else closes[i]) else '#f44336'
        svg.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" opacity="0.5"/>')

    # 价格线
    pts = ' '.join(f'{px(i)} {py(closes[i])}' for i in range(n))
    svg.append(f'<path d="M {pts}" stroke="#2196F3" stroke-width="2" fill="none"/>')

    # 阻力线
    resistance = pattern['resistance_price']
    current_price = closes[-1]
    ry = py(resistance)
    svg.append(f'<line x1="{margin["left"]}" y1="{ry}" x2="{W-margin["right"]}" y2="{ry}" stroke="#f44336" stroke-width="1.5" stroke-dasharray="8,4"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{ry+4}" font-size="10" fill="#f44336">阻力 {resistance:.2f}</text>')

    # 目标位
    min_bottom = min(pattern['b1_price'], pattern['b2_price'], pattern['b3_price'])
    target = resistance + (resistance - min_bottom)
    if target < max_p * 1.1:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W-margin["right"]}" y2="{ty}" stroke="#FF9800" stroke-width="1" stroke-dasharray="5,5"/>')
        svg.append(f'<text x="{W-margin["right"]+5}" y="{ty+4}" font-size="10" fill="#FF9800">目标 {target:.2f}</text>')

    # 标注三个底
    colors = ['#4CAF50', '#2196F3', '#9C27B0']
    labels = ['第一底', '第二底', '第三底']
    keys = [('b1_idx', 'b1_price'), ('b2_idx', 'b2_price'), ('b3_idx', 'b3_price')]
    for c, lab, (ik, pk) in zip(colors, labels, keys):
        svg.append(f'<circle cx="{px(pattern[ik])}" cy="{py(pattern[pk])}" r="6" fill="{c}" stroke="#fff" stroke-width="2"/>')
        svg.append(f'<text x="{px(pattern[ik])}" y="{py(pattern[pk])+20}" text-anchor="middle" font-size="10" fill="{c}">{lab}</text>')

    # 突破点
    if pattern['break_idx'] < n:
        svg.append(f'<circle cx="{px(pattern["break_idx"])}" cy="{ry}" r="5" fill="#FF9800" stroke="#fff" stroke-width="2"/>')

    # 现价
    cpy = py(current_price)
    svg.append(f'<line x1="{px(n-1)}" y1="{cpy}" x2="{W-margin["right"]}" y2="{cpy}" stroke="#FF9800" stroke-width="1"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{cpy+4}" font-size="10" fill="#FF9800">现价 {current_price:.2f}</text>')

    # 底部说明
    reasons_text = '\n'.join([f'{i+1}. {r}' for i, r in enumerate(reasons[:6])])
    base_y = H - margin['bottom'] + 15
    svg.append(f'<text x="{margin["left"]}" y="{base_y}" font-size="12" fill="#e0e0e0" font-weight="bold">高分原因:</text>')
    for i, line in enumerate(reasons_text.split('\n')):
        svg.append(f'<text x="{margin["left"]}" y="{base_y+18+i*18}" font-size="11" fill="#aaa">{line}</text>')

    svg.append('</svg>')
    with open(save_path, 'w') as f: f.write('\n'.join(svg))


# ============ 主程序 ============

def main():
    print("=" * 50)
    print("三重底突破形态扫描 (Triple Bottom)")
    print("条件: 三底价格接近, 刚突破阻力位")
    print("=" * 50)

    print("\n[1/4] 获取股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}

    hs300 = get_hs300_components()
    zz500_result = api_call('index_weight', index_code='000905.SH', fields='con_code')
    zz500 = list(set(item[0] for item in zz500_result['items'])) if zz500_result and 'items' in zz500_result else []

    all_codes = set((hs300 or []) + zz500)
    scan_codes = [c for c in all_codes if c in stock_map]
    print(f"  扫描沪深300+中证500共 {len(scan_codes)} 只股票")

    print(f"\n[2/4] 扫描三重底形态 (突破距{END_DATE}越近越好)...")
    all_patterns = []

    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0: print(f"  进度: {idx}/{len(scan_codes)}")

        try:
            df = get_daily_data(code)
            if not df or len(df) < 80: continue

            patterns = detect_triple_bottom(df, window=10)
            name = stock_map.get(code, code)

            for p in patterns:
                score, reasons = score_triple_bottom(df, p)
                if score >= 40:
                    all_patterns.append({
                        'code': code, 'name': name, 'df': df,
                        'pattern': p, 'score': score, 'reasons': reasons
                    })
            time.sleep(0.12)
        except: continue

    all_patterns.sort(key=lambda x: (len(x['df'])-1-x['pattern']['break_idx'], -x['score']))
    top5 = all_patterns[:5]

    print(f"\n[3/4] 前5名:")
    for i, item in enumerate(top5):
        p = item['pattern']
        days_ago = len(item['df']) - 1 - p['break_idx']
        print(f"  {i+1}. {item['name']} ({item['code']}) 评分:{item['score']} 突破于{p['break_date']} ({days_ago}天前)")

    print(f"\n[4/4] 生成图片...")
    output_dir = os.path.expanduser('~/triple_bottom_charts')
    os.makedirs(output_dir, exist_ok=True)

    for i, item in enumerate(top5):
        svg_path = os.path.join(output_dir, f'top{i+1}_{item["code"]}.svg')
        draw_svg_chart(item['df'], item['pattern'], item['score'], item['reasons'], item['name'], item['code'], svg_path)
        print(f"  SVG: {svg_path}")

    print(f"\n{'='*50}")
    for i, item in enumerate(top5):
        p = item['pattern']
        cp = float(item['df'][-1]['close'])
        dist = (cp - p['resistance_price']) / p['resistance_price'] * 100
        min_b = min(p['b1_price'], p['b2_price'], p['b3_price'])
        target = p['resistance_price'] + (p['resistance_price'] - min_b)
        space = (target - cp) / cp * 100

        print(f"\n{'='*40}")
        print(f"第{i+1}名: {item['name']} ({item['code']})")
        print(f"  评分: {item['score']}/100 | 突破日: {p['break_date']}")
        print(f"  第一底: {format_date(p['b1_date'])} @{p['b1_price']:.2f}")
        print(f"  第二底: {format_date(p['b2_date'])} @{p['b2_price']:.2f}")
        print(f"  第三底: {format_date(p['b3_date'])} @{p['b3_price']:.2f}")
        print(f"  阻力: @{p['resistance_price']:.2f} | 现价: {cp:.2f} (突破{dist:.1f}%)")
        print(f"  目标: @{target:.2f} (剩余空间{space:.1f}%)")
        for r in item['reasons']: print(f"  + {r}")

    print(f"\n完成! 图表保存在: {output_dir}")

if __name__ == '__main__':
    main()
