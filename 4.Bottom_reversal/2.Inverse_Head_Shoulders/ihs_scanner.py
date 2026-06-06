"""
头肩底形态扫描器 (Inverse Head & Shoulders)
条件:
- 左肩-头-右肩结构完整
- 头部最低，右肩高于头部
- 突破颈线且距离越近越好
- 距目标位剩余空间 >= 8%
"""

import urllib.request
import json
import os
import time
import math
import statistics

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
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

def calc_ma(closes, period=20):
    n = len(closes); result = [0.0] * n
    for i in range(n):
        if i >= period - 1: result[i] = sum(closes[i-period+1:i+1]) / period
    return result

# ============ 头肩底检测 ============

def detect_ihs(df, window=10):
    """
    检测头肩底形态:
    - 三个连续低点: 左肩 → 头部(最低) → 右肩
    - 两个高点(连接成颈线)分别在肩-头、头-肩之间
    - 右肩高于头部, 颈线倾斜
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
    # 找三个连续低点: left_shoulder, head, right_shoulder
    for i in range(len(lows) - 2):
        ls_idx, ls_price, ls_vol = lows[i]
        h_idx, h_price, h_vol = lows[i + 1]
        rs_idx, rs_price, rs_vol = lows[i + 2]

        # 头部必须是最低点
        if h_price >= ls_price or h_price >= rs_price:
            continue

        # 左肩和右肩价格应该接近 (允许15%偏差)
        shoulder_avg = (ls_price + rs_price) / 2
        if abs(ls_price - rs_price) / shoulder_avg > 0.15:
            continue

        # 间距: 肩到头的K线数应在合理范围
        gap1 = h_idx - ls_idx  # 左肩→头
        gap2 = rs_idx - h_idx  # 头→右肩
        if gap1 < 10 or gap1 > 120: continue
        if gap2 < 10 or gap2 > 120: continue

        # 找颈线: 左肩→头之间的最高点, 头→右肩之间的最高点
        hl1 = [h for h in highs if ls_idx < h[0] < h_idx]
        hl2 = [h for h in highs if h_idx < h[0] < rs_idx]
        if not hl1 or not hl2: continue

        h1_idx, h1_price = max(hl1, key=lambda x: x[1])
        h2_idx, h2_price = max(hl2, key=lambda x: x[1])

        # 颈线应该接近水平或略向下倾斜(对头肩底是正常向上倾斜)
        neck_slope = (h2_price - h1_price) / (h2_idx - h1_idx + 1)
        if neck_slope > 0.1: continue  # 急剧上升的颈线不太可靠

        # 检查突破颈线
        # 颈线延长: 从h1到h2的直线, 延伸到当前
        neck_last = h2_price + neck_slope * (n - 1 - h2_idx)
        break_idx = None
        for j in range(rs_idx, n):
            neck_at_j = h2_price + neck_slope * (j - h2_idx)
            if closes[j] > neck_at_j * 1.01:
                break_idx = j
                break

        if break_idx is None: continue  # 未突破

        # 形态必须在指定时间范围内
        if dates[ls_idx] < PATTERN_START: continue

        results.append({
            'ls_idx': ls_idx, 'ls_price': ls_price, 'ls_date': dates[ls_idx], 'ls_vol': ls_vol,
            'h_idx': h_idx, 'h_price': h_price, 'h_date': dates[h_idx], 'h_vol': h_vol,
            'rs_idx': rs_idx, 'rs_price': rs_price, 'rs_date': dates[rs_idx], 'rs_vol': rs_vol,
            'neck1_idx': h1_idx, 'neck1_price': h1_price,
            'neck2_idx': h2_idx, 'neck2_price': h2_price,
            'neck_slope': neck_slope,
            'break_idx': break_idx, 'break_date': dates[break_idx],
            'height_pct': (h1_price - h_price) / h_price if h_price > 0 else 0,
            'ls_macd': macd[ls_idx], 'h_macd': macd[h_idx], 'rs_macd': macd[rs_idx],
            'ls_rsi': rsi[ls_idx], 'h_rsi': rsi[h_idx], 'rs_rsi': rsi[rs_idx],
            'closes': closes, 'volumes': volumes, 'dates': dates
        })

    return results

def score_ihs(df, pattern):
    """评分 (0-100)"""
    score = 0
    reasons = []
    current_price = float(df[-1]['close'])
    n = len(df)

    # === 核心过滤 ===
    h2_price = pattern['neck2_price']
    neck_slope = pattern['neck_slope']
    neck_current = h2_price + neck_slope * (n - 1 - pattern['neck2_idx'])

    if current_price <= neck_current: return -1, []  # 未突破

    # 突破不能太远(5%以内)
    dist = (current_price - neck_current) / neck_current
    if dist > 0.05: return -1, []

    # 计算目标位
    head_to_neck = h2_price - pattern['h_price']
    target = neck_current + head_to_neck
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08: return -1, []  # 空间不足

    # === 评分项 ===

    # 1. 突破新鲜度 (25分)
    break_idx = pattern['break_idx']
    days_since_break = n - 1 - break_idx
    if days_since_break <= 3: score += 25; reasons.append(f'刚刚突破({days_since_break}天前)')
    elif days_since_break <= 5: score += 20; reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 10: score += 15; reasons.append(f'突破{days_since_break}天')
    else: score += 5; reasons.append(f'突破已{days_since_break}天(较久)')

    # 2. 右肩缩量 (20分)
    if pattern['ls_vol'] > 0:
        vol_ratio = pattern['rs_vol'] / pattern['ls_vol']
        if vol_ratio < 0.3: score += 20; reasons.append(f'右肩极度缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.5: score += 18; reasons.append(f'右肩显著缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.7: score += 12; reasons.append(f'右肩缩量({vol_ratio:.0%})')

    # 3. 形态跨度 (15分)
    total_gap = pattern['rs_idx'] - pattern['ls_idx']
    if total_gap >= 60: score += 15; reasons.append(f'形态跨度大({total_gap}根K线)')
    elif total_gap >= 30: score += 10; reasons.append(f'形态跨度适中({total_gap}根K线)')

    # 4. MACD底背离: 右肩MACD > 头部MACD (15分)
    if pattern['rs_macd'] > pattern['h_macd'] and pattern['rs_price'] > pattern['h_price']:
        score += 15; reasons.append('MACD底背离(右肩vs头部)')
    elif pattern['rs_macd'] > pattern['ls_macd']:
        score += 10; reasons.append('MACD改善')

    # 5. 右肩高于左肩 (10分) - 头肩底理想形态
    if pattern['rs_price'] > pattern['ls_price']:
        score += 10; reasons.append('右肩高于左肩(理想形态)')
    elif abs(pattern['rs_price'] - pattern['ls_price']) / pattern['ls_price'] < 0.02:
        score += 8; reasons.append('两肩齐平')

    # 6. 头部深度合理 (10分)
    h = pattern['height_pct']
    if 0.10 <= h <= 0.30: score += 10; reasons.append(f'头部深度理想({h:.1%})')
    elif 0.08 <= h < 0.10: score += 7; reasons.append(f'头部深度合理({h:.1%})')

    # 7. RSI底背离 (5分)
    if pattern['rs_rsi'] > pattern['h_rsi']:
        score += 5; reasons.append('RSI底背离')

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
           f'<text x="{W/2}" y="28" text-anchor="middle" font-size="16" fill="#e0e0e0" font-weight="bold">{stock_name} ({stock_code})  头肩底突破  评分:{score}/100</text>']

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i; yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#2a2a4a" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-5}" y="{yy+4}" text-anchor="end" font-size="10" fill="#888">{gp:.2f}</text>')

    # 日期
    for i in range(0, n, max(1, n//8)):
        svg.append(f'<text x="{px(i)}" y="{margin["top"]+price_h+15}" text-anchor="middle" font-size="9" fill="#888">{format_date(dates[i])}</text>')

    # 头肩底区域高亮
    hl_start = max(0, pattern['ls_idx']-10); hl_end = min(n-1, pattern['break_idx']+5)
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

    # 颈线 (从neck1延伸到当前)
    neck_slope = pattern['neck_slope']
    h1_price = pattern['neck1_price']; h2_price = pattern['neck2_price']
    h1_idx = pattern['neck1_idx']; h2_idx = pattern['neck2_idx']
    current_price = closes[-1]

    n1y = py(h1_price); n2y = py(h2_price)
    neck_at_n = h2_price + neck_slope * (n - 1 - h2_idx)
    n3y = py(neck_at_n)
    svg.append(f'<line x1="{px(h1_idx-5)}" y1="{n1y}" x2="{W-margin["right"]}" y2="{n3y}" stroke="#f44336" stroke-width="1.5" stroke-dasharray="8,4"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{n3y+4}" font-size="10" fill="#f44336">颈线</text>')

    # 目标位
    head_to_neck = h2_price - pattern['h_price']
    target = neck_at_n + head_to_neck
    if target < max_p * 1.1:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W-margin["right"]}" y2="{ty}" stroke="#FF9800" stroke-width="1" stroke-dasharray="5,5"/>')
        svg.append(f'<text x="{W-margin["right"]+5}" y="{ty+4}" font-size="10" fill="#FF9800">目标 {target:.2f}</text>')

    # 标注左肩、头、右肩
    svg.append(f'<circle cx="{px(pattern["ls_idx"])}" cy="{py(pattern["ls_price"])}" r="6" fill="#4CAF50" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["ls_idx"])}" y="{py(pattern["ls_price"])+20}" text-anchor="middle" font-size="10" fill="#4CAF50">左肩</text>')

    svg.append(f'<circle cx="{px(pattern["h_idx"])}" cy="{py(pattern["h_price"])}" r="7" fill="#f44336" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["h_idx"])}" y="{py(pattern["h_price"])+20}" text-anchor="middle" font-size="10" fill="#f44336">头部</text>')

    svg.append(f'<circle cx="{px(pattern["rs_idx"])}" cy="{py(pattern["rs_price"])}" r="6" fill="#9C27B0" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["rs_idx"])}" y="{py(pattern["rs_price"])+20}" text-anchor="middle" font-size="10" fill="#9C27B0">右肩</text>')

    # 突破点
    svg.append(f'<circle cx="{px(pattern["break_idx"])}" cy="{py(neck_at_n)}" r="5" fill="#FF9800" stroke="#fff" stroke-width="2"/>')

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
    print("头肩底突破形态扫描 (Inverse H&S)")
    print("条件: 左肩-头部-右肩结构完整, 刚突破颈线")
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

    print(f"\n[2/4] 扫描头肩底形态 (突破距{END_DATE}越近越好)...")
    all_patterns = []

    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0: print(f"  进度: {idx}/{len(scan_codes)}")

        try:
            df = get_daily_data(code)
            if not df or len(df) < 80: continue

            patterns = detect_ihs(df, window=10)
            name = stock_map.get(code, code)

            for p in patterns:
                score, reasons = score_ihs(df, p)
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, f'{END_DATE}_data')
    os.makedirs(output_dir, exist_ok=True)

    for i, item in enumerate(top5):
        svg_path = os.path.join(output_dir, f'top{i+1}_{item["code"]}.svg')
        draw_svg_chart(item['df'], item['pattern'], item['score'], item['reasons'], item['name'], item['code'], svg_path)
        print(f"  SVG: {svg_path}")

    # 导出CSV (全部符合条件的结果)
    csv_path = os.path.join(output_dir, f'results_{END_DATE}.csv')
    with open(csv_path, 'w') as f:
        f.write('rank,code,name,score,break_date,ls_date,ls_price,h_date,h_price,rs_date,rs_price,neck_current,current_price,dist_pct,target,space_pct,reasons\n')
        for i, item in enumerate(all_patterns):
            p = item['pattern']
            cp = float(item['df'][-1]['close'])
            n_slope = p['neck_slope']
            neck_now = p['neck2_price'] + n_slope * (len(item['df'])-1-p['neck2_idx'])
            dist = (cp - neck_now) / neck_now * 100
            head_to_neck = p['neck2_price'] - p['h_price']
            target = neck_now + head_to_neck
            space = (target - cp) / cp * 100
            reasons_str = '; '.join(item['reasons'])
            f.write(f'{i+1},{item["code"]},{item["name"]},{item["score"]},{p["break_date"]},{p["ls_date"]},{p["ls_price"]:.2f},{p["h_date"]},{p["h_price"]:.2f},{p["rs_date"]},{p["rs_price"]:.2f},{neck_now:.2f},{cp:.2f},{dist:.1f},{target:.2f},{space:.1f},{reasons_str}\n')
    print(f"  CSV: {csv_path}")
    for i, item in enumerate(top5):
        p = item['pattern']
        cp = float(item['df'][-1]['close'])
        n_slope = p['neck_slope']
        neck_now = p['neck2_price'] + n_slope * (len(item['df'])-1-p['neck2_idx'])
        dist = (cp - neck_now) / neck_now * 100
        head_to_neck = p['neck2_price'] - p['h_price']
        target = neck_now + head_to_neck
        space = (target - cp) / cp * 100

        print(f"\n{'='*40}")
        print(f"第{i+1}名: {item['name']} ({item['code']})")
        print(f"  评分: {item['score']}/100 | 突破日: {p['break_date']}")
        print(f"  左肩: {format_date(p['ls_date'])} @{p['ls_price']:.2f}")
        print(f"  头部: {format_date(p['h_date'])} @{p['h_price']:.2f}")
        print(f"  右肩: {format_date(p['rs_date'])} @{p['rs_price']:.2f}")
        print(f"  颈线(现): {neck_now:.2f} | 现价: {cp:.2f} (突破{dist:.1f}%)")
        print(f"  目标: @{target:.2f} (剩余空间{space:.1f}%)")
        for r in item['reasons']: print(f"  + {r}")

    print(f"\n完成! 图表保存在: {output_dir}")

if __name__ == '__main__':
    main()
