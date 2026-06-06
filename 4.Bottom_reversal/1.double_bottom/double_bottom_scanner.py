"""
双底形态扫描器 - 近期突破版 (无第三方依赖)
条件:
- 双底形态形成于 2025年12月 ~ 2026年5月10日
- 首次突破颈线距离 2026-05-10 越近越好
- 拉升可能性高
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
START_DATE = '20241001'  # 往前多取一些数据用于计算指标
DOUBLE_BOTTOM_START = '20251201'  # 双底形态开始时间
MAX_SCAN = 400  # 扫描数量限制

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

# ============ 双底检测 ============

def detect_double_bottom(df, window=8):
    n = len(df)
    if n < window * 2 + 1: return []
    
    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    
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
        if n_price / min(l1_price, l2_price) < 1.05: continue
        
        # 双底必须在指定时间范围内开始形成
        if dates[l1_idx] < DOUBLE_BOTTOM_START: continue
        
        # 检查突破颈线的时间
        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:  # 突破1%算有效突破
                break_idx = j
                break
        
        if break_idx is None: continue  # 未突破
        
        results.append({
            'left_idx': l1_idx, 'left_price': l1_price, 'left_date': dates[l1_idx], 'left_vol': l1_vol,
            'right_idx': l2_idx, 'right_price': l2_price, 'right_date': dates[l2_idx], 'right_vol': l2_vol,
            'neck_idx': n_idx, 'neck_price': n_price, 'neck_date': dates[n_idx],
            'break_idx': break_idx, 'break_date': dates[break_idx],
            'gap': gap,
            'price_diff_pct': abs(l1_price - l2_price) / min(l1_price, l2_price),
            'height_pct': (n_price - min(l1_price, l2_price)) / min(l1_price, l2_price),
            'left_macd': macd[l1_idx], 'right_macd': macd[l2_idx],
            'left_rsi': rsi[l1_idx], 'right_rsi': rsi[l2_idx],
            'closes': closes, 'volumes': volumes, 'dates': dates
        })
    
    return results

def score_pattern(df, pattern):
    """评分 (0-100)，侧重突破新鲜度和拉升潜力"""
    score = 0
    reasons = []
    current_price = float(df[-1]['close'])
    n = len(df)
    end_date = df[-1]['trade_date']
    
    # === 核心过滤 ===
    neck_price = pattern['neck_price']
    if current_price <= neck_price: return -1, []  # 未突破
    
    # 突破幅度不能超过5%
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05: return -1, []
    
    # 计算目标位及剩余空间
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08: return -1, []  # 空间不足
    
    # === 评分项 ===
    
    # 1. 突破新鲜度 (最高权重 25分) - 距离5月10日越近越好
    break_idx = pattern['break_idx']
    days_since_break = n - 1 - break_idx
    if days_since_break <= 3:
        score += 25; reasons.append(f'刚刚突破({days_since_break}天前)')
    elif days_since_break <= 5:
        score += 20; reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 10:
        score += 15; reasons.append(f'突破{days_since_break}天')
    else:
        score += 5; reasons.append(f'突破已{days_since_break}天(较久)')
    
    # 2. 右底缩量 (20分)
    if pattern['left_vol'] > 0:
        vol_ratio = pattern['right_vol'] / pattern['left_vol']
        if vol_ratio < 0.3: score += 20; reasons.append(f'右底极度缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.5: score += 18; reasons.append(f'右底显著缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.7: score += 12; reasons.append(f'右底缩量({vol_ratio:.0%})')
    
    # 3. 形态跨度 (15分)
    gap = pattern['gap']
    if gap >= 30: score += 15; reasons.append(f'形态跨度大({gap}根K线)')
    elif gap >= 20: score += 10; reasons.append(f'形态跨度适中({gap}根K线)')
    
    # 4. MACD底背离 (15分)
    if pattern['right_macd'] > pattern['left_macd'] and pattern['left_price'] >= pattern['right_price']:
        score += 15; reasons.append('MACD底背离')
    elif pattern['right_macd'] > pattern['left_macd']:
        score += 10; reasons.append('MACD改善')
    
    # 5. 右底高于左底 (10分)
    if pattern['right_price'] > pattern['left_price']:
        score += 10; reasons.append('右底高于左底(抬高低点)')
    elif abs(pattern['right_price'] - pattern['left_price']) / pattern['left_price'] < 0.01:
        score += 8; reasons.append('两底齐平(强支撑)')
    
    # 6. 振幅合理 (10分)
    h = pattern['height_pct']
    if 0.10 <= h <= 0.25: score += 10; reasons.append(f'振幅理想({h:.1%})')
    elif 0.08 <= h < 0.10: score += 7; reasons.append(f'振幅合理({h:.1%})')
    
    # 7. RSI底背离 (5分)
    if pattern['right_rsi'] > pattern['left_rsi'] and pattern['left_price'] >= pattern['right_price']:
        score += 5; reasons.append('RSI底背离')
    
    return score, reasons

# ============ SVG 绘图 ============

def format_date(ds): return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"

def draw_svg_chart(df, pattern, score, reasons, stock_name, stock_code, save_path):
    W, H = 900, 650
    margin = {'top': 50, 'right': 60, 'bottom': 100, 'left': 70}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.65; vol_h = chart_h * 0.25; gap_h = chart_h * 0.1
    
    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    n = len(df)
    
    min_p = min(closes) * 0.97; max_p = max(closes) * 1.02
    max_v = max(volumes) * 1.2
    
    def px(i): return margin['left'] + (i / (n - 1)) * chart_w
    def py(price): return margin['top'] + (1 - (price - min_p) / (max_p - min_p)) * price_h
    def vy(vol): return margin['top'] + price_h + gap_h + (1 - vol / max_v) * vol_h
    
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           f'<rect width="{W}" height="{H}" fill="#1a1a2e"/>',
           f'<text x="{W/2}" y="28" text-anchor="middle" font-size="16" fill="#e0e0e0" font-weight="bold">{stock_name} ({stock_code})  双底突破  评分:{score}/100</text>']
    
    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i; yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#2a2a4a" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-5}" y="{yy+4}" text-anchor="end" font-size="10" fill="#888">{gp:.2f}</text>')
    
    # 日期
    for i in range(0, n, max(1, n//8)):
        svg.append(f'<text x="{px(i)}" y="{margin["top"]+price_h+15}" text-anchor="middle" font-size="9" fill="#888">{format_date(dates[i])}</text>')
    
    # 双底区域高亮
    hl_start = max(0, pattern['left_idx']-10); hl_end = min(n-1, pattern['right_idx']+10)
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
    
    # 颈线 & 目标
    neck_price = pattern['neck_price']; current_price = closes[-1]
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    
    ny = py(neck_price)
    svg.append(f'<line x1="{margin["left"]}" y1="{ny}" x2="{W-margin["right"]}" y2="{ny}" stroke="#f44336" stroke-width="1.5"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{ny+4}" font-size="10" fill="#f44336">颈线 {neck_price:.2f}</text>')
    
    if target < max_p * 1.1:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W-margin["right"]}" y2="{ty}" stroke="#FF9800" stroke-width="1" stroke-dasharray="5,5"/>')
        svg.append(f'<text x="{W-margin["right"]+5}" y="{ty+4}" font-size="10" fill="#FF9800">目标 {target:.2f}</text>')
    
    # 关键点
    svg.append(f'<circle cx="{px(pattern["left_idx"])}" cy="{py(pattern["left_price"])}" r="6" fill="#4CAF50" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["left_idx"])}" y="{py(pattern["left_price"])+20}" text-anchor="middle" font-size="10" fill="#4CAF50">左底</text>')
    svg.append(f'<circle cx="{px(pattern["right_idx"])}" cy="{py(pattern["right_price"])}" r="6" fill="#9C27B0" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["right_idx"])}" y="{py(pattern["right_price"])+20}" text-anchor="middle" font-size="10" fill="#9C27B0">右底</text>')
    
    # 突破点标记
    svg.append(f'<circle cx="{px(pattern["break_idx"])}" cy="{py(neck_price)}" r="5" fill="#FF9800" stroke="#fff" stroke-width="2"/>')
    
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
    print("双底突破形态扫描 (近期突破版)")
    print("条件: 双底始于2025年12月, 刚突破颈线")
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
    
    print(f"\n[2/4] 扫描双底形态 (突破距{END_DATE}越近越好)...")
    all_patterns = []
    
    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0: print(f"  进度: {idx}/{len(scan_codes)}")
        
        try:
            df = get_daily_data(code)
            if not df or len(df) < 60: continue
            
            patterns = detect_double_bottom(df, window=8)
            name = stock_map.get(code, code)
            
            for p in patterns:
                score, reasons = score_pattern(df, p)
                if score >= 40:
                    all_patterns.append({
                        'code': code, 'name': name, 'df': df,
                        'pattern': p, 'score': score, 'reasons': reasons
                    })
            time.sleep(0.12)
        except: continue
    
    # 排序: 突破越近越好（优先），其次评分越高越好
    all_patterns.sort(key=lambda x: (len(x['df'])-1-x['pattern']['break_idx'], -x['score']))
    top5 = all_patterns[:5]
    
    print(f"\n[3/4] 前5名:")
    for i, item in enumerate(top5):
        p = item['pattern']
        days_ago = len(item['df']) - 1 - p['break_idx']
        print(f"  {i+1}. {item['name']} ({item['code']}) 评分:{item['score']} 突破于{p['break_date']} ({days_ago}天前)")
    
    print(f"\n[4/4] 生成图片...")
    output_svg = os.path.expanduser('~/double_bottom_charts_20260510')
    os.makedirs(output_svg, exist_ok=True)
    
    for i, item in enumerate(top5):
        svg_path = os.path.join(output_svg, f'top{i+1}_{item["code"]}.svg')
        draw_svg_chart(item['df'], item['pattern'], item['score'], item['reasons'], item['name'], item['code'], svg_path)
        print(f"  SVG: {svg_path}")
    
    # 转 PNG
    output_png = os.path.expanduser('~/storage/shared/termux/20260510双底')
    os.makedirs(output_png, exist_ok=True)
    for f in os.listdir(output_svg):
        if f.endswith('.svg'):
            os.system(f'magick "{os.path.join(output_svg, f)}" "{os.path.join(output_png, f.replace(".svg", ".png"))}" 2>&1')
    
    print(f"\n完成! PNG保存在: {output_png}")
    print("=" * 50)
    
    for i, item in enumerate(top5):
        p = item['pattern']
        cp = float(item['df'][-1]['close'])
        dist = (cp - p['neck_price']) / p['neck_price'] * 100
        min_b = min(p['left_price'], p['right_price'])
        target = p['neck_price'] + (p['neck_price'] - min_b)
        space = (target - cp) / cp * 100
        print(f"\n{'='*40}")
        print(f"第{i+1}名: {item['name']} ({item['code']})")
        print(f"  评分: {item['score']}/100")
        print(f"  突破日: {p['break_date']} (距今{len(item['df'])-1-p['break_idx']}天)")
        print(f"  左底: {format_date(p['left_date'])} @{p['left_price']:.2f}")
        print(f"  右底: {format_date(p['right_date'])} @{p['right_price']:.2f}")
        print(f"  颈线: @{p['neck_price']:.2f} | 现价: {cp:.2f} (突破{dist:.1f}%)")
        print(f"  目标: @{target:.2f} (剩余空间{space:.1f}%)")
        for r in item['reasons']: print(f"  + {r}")

if __name__ == '__main__':
    main()
