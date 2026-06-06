"""
双底形态扫描器 - 全A股版 (无第三方依赖)
扫描日期: 2026-05-19
条件:
- 双底形态形成于 2025年12月 ~ 2026年5月19日
- 首次突破颈线, 突破后涨幅(现价相对颈线)不超过5%
- 距目标位剩余空间 >= 8% (否则排除)
- 评分 >= 40
- 扫描全A股市场
输出: 前10名生成SVG图表 + Discord消息
"""

import sys
sys.stdout = sys.stderr  # unbuffered

import urllib.request
import json
import os
import time
import math

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
END_DATE = '20260519'
START_DATE = '20241001'
DOUBLE_BOTTOM_START = '20251201'
API_SLEEP = 0.12
TOP_N = 10

# ============ Tushare API ============

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
    stocks = []
    for item in result['items']:
        d = dict(zip(fields, item))
        if d.get('list_status') == 'L':
            name = d.get('name', '')
            if 'ST' not in name and '退' not in name:
                stocks.append(d)
    return stocks

def get_daily_data(ts_code, start_date=START_DATE, end_date=END_DATE):
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
    ema12, ema26 = ema(closes, 12), ema(closes, 26)
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
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, n - 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi

# ============ 双底检测 ============

def detect_double_bottom(df, window=8):
    n = len(df)
    if n < window * 2 + 1:
        return []

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)

    lows, highs = [], []
    for i in range(window, n - window):
        price = closes[i]
        bs, ae = max(0, i - window), min(n, i + window + 1)
        if all(closes[j] > price for j in range(bs, ae) if j != i):
            lows.append((i, price, volumes[i]))
        if all(closes[j] < price for j in range(bs, ae) if j != i):
            highs.append((i, price))

    if len(lows) < 2 or len(highs) < 1:
        return []

    results = []
    for i in range(len(lows) - 1):
        l1_idx, l1_price, l1_vol = lows[i]
        l2_idx, l2_price, l2_vol = lows[i + 1]

        gap = l2_idx - l1_idx
        if gap < 15 or gap > 150:
            continue
        if abs(l1_price - l2_price) / min(l1_price, l2_price) > 0.05:
            continue

        necks = [h for h in highs if l1_idx < h[0] < l2_idx]
        if not necks:
            continue
        n_idx, n_price = max(necks, key=lambda x: x[1])
        if n_price / min(l1_price, l2_price) < 1.05:
            continue
        if dates[l1_idx] < DOUBLE_BOTTOM_START:
            continue

        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:
                break_idx = j
                break
        if break_idx is None:
            continue

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
        })
    return results

def score_pattern(df, pattern):
    score = 0
    reasons = []
    current_price = float(df[-1]['close'])
    n = len(df)
    neck_price = pattern['neck_price']

    # 核心过滤
    if current_price <= neck_price:
        return -1, []
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05:
        return -1, []  # 突破幅度>5%排除

    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08:
        return -1, []  # 剩余空间<8%排除

    # 1. 突破新鲜度 (25分)
    break_idx = pattern['break_idx']
    days_since_break = n - 1 - break_idx
    if days_since_break <= 3:
        score += 25; reasons.append(f'刚刚突破({days_since_break}天前)')
    elif days_since_break <= 5:
        score += 20; reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 10:
        score += 15; reasons.append(f'突破{days_since_break}天')
    else:
        score += 5; reasons.append(f'突破已{days_since_break}天')

    # 2. 右底缩量 (20分)
    vol_ratio = None
    if pattern['left_vol'] > 0:
        vol_ratio = pattern['right_vol'] / pattern['left_vol']
        if vol_ratio < 0.3:
            score += 20; reasons.append(f'右底极度缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.5:
            score += 18; reasons.append(f'右底显著缩量({vol_ratio:.0%})')
        elif vol_ratio < 0.7:
            score += 12; reasons.append(f'右底缩量({vol_ratio:.0%})')

    # 3. 形态跨度 (15分)
    gap = pattern['gap']
    if gap >= 30:
        score += 15; reasons.append(f'形态跨度大({gap}根K线)')
    elif gap >= 20:
        score += 10; reasons.append(f'形态跨度适中({gap}根K线)')

    # 4. MACD底背离 (15分)
    if pattern['right_macd'] > pattern['left_macd'] and pattern['left_price'] >= pattern['right_price']:
        score += 15; reasons.append('MACD底背离')
    elif pattern['right_macd'] > pattern['left_macd']:
        score += 10; reasons.append('MACD改善')

    # 5. 右底高于左底 (10分)
    if pattern['right_price'] > pattern['left_price']:
        score += 10; reasons.append('右底高于左底')
    elif abs(pattern['right_price'] - pattern['left_price']) / pattern['left_price'] < 0.01:
        score += 8; reasons.append('两底齐平')

    # 6. 振幅合理 (10分)
    h = pattern['height_pct']
    if 0.10 <= h <= 0.25:
        score += 10; reasons.append(f'振幅理想({h:.1%})')
    elif 0.08 <= h < 0.10:
        score += 7; reasons.append(f'振幅合理({h:.1%})')

    # 7. RSI底背离 (5分)
    if pattern['right_rsi'] > pattern['left_rsi'] and pattern['left_price'] >= pattern['right_price']:
        score += 5; reasons.append('RSI底背离')

    return score, reasons

# ============ SVG 图表 ============

def format_date(ds):
    return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"

def draw_svg_chart(df, pattern, score, reasons, stock_name, stock_code, save_path):
    """生成双底标注SVG图表"""
    W, H = 1000, 700
    margin = {'top': 60, 'right': 80, 'bottom': 120, 'left': 80}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.62
    vol_h = chart_h * 0.25
    gap_h = chart_h * 0.13

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    n = len(df)

    min_p = min(closes) * 0.97
    max_p = max(closes) * 1.02
    max_v = max(volumes) * 1.2

    def px(i):
        return margin['left'] + (i / (n - 1)) * chart_w
    def py(price):
        return margin['top'] + (1 - (price - min_p) / (max_p - min_p)) * price_h
    def vy(vol):
        return margin['top'] + price_h + gap_h + (1 - vol / max_v) * vol_h

    neck_price = pattern['neck_price']
    current_price = closes[-1]
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    post_breakout_pct = (current_price - neck_price) / neck_price * 100
    upside_pct = (target - current_price) / current_price * 100

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    svg.append(f'<rect width="{W}" height="{H}" fill="#0d1117"/>')

    # 标题
    svg.append(f'<text x="{W/2}" y="24" text-anchor="middle" font-size="18" fill="#58a6ff" font-weight="bold">'
               f'{stock_name} ({stock_code})</text>')
    svg.append(f'<text x="{W/2}" y="46" text-anchor="middle" font-size="14" fill="#8b949e">'
               f'双底突破 | 评分:{score}/100 | 突破后涨幅:{post_breakout_pct:.1f}% | 目标空间:{upside_pct:.1f}%</text>')

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-8}" y="{yy+4}" text-anchor="end" font-size="10" fill="#8b949e">{gp:.2f}</text>')

    # 日期标签
    step = max(1, n // 8)
    for i in range(0, n, step):
        svg.append(f'<text x="{px(i)}" y="{margin["top"]+price_h+14}" text-anchor="middle" font-size="9" fill="#8b949e">{format_date(dates[i])}</text>')

    # === 双底区域高亮 ===
    hl_start = max(0, pattern['left_idx'] - 10)
    hl_end = min(n - 1, pattern['break_idx'] + 5)
    svg.append(f'<rect x="{px(hl_start)}" y="{margin["top"]}" width="{px(hl_end)-px(hl_start)}" '
               f'height="{price_h+vol_h+gap_h}" fill="#238636" opacity="0.10" rx="4"/>')
    svg.append(f'<text x="{(px(hl_start)+px(hl_end))/2}" y="{margin["top"]-8}" text-anchor="middle" '
               f'font-size="11" fill="#3fb950" font-weight="bold">双底区域</text>')

    # 成交量柱
    for i in range(n):
        bar_w = max(1, chart_w / n * 0.6)
        x = px(i) - bar_w / 2
        y = vy(volumes[i])
        bh = margin['top'] + price_h + gap_h + vol_h - y
        color = '#3fb950' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#f85149'
        svg.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" opacity="0.45"/>')

    # 价格线
    pts = ' '.join(f'{px(i)},{py(closes[i])}' for i in range(n))
    svg.append(f'<polyline points="{pts}" stroke="#58a6ff" stroke-width="1.8" fill="none"/>')

    # 颈线
    ny = py(neck_price)
    svg.append(f'<line x1="{margin["left"]}" y1="{ny}" x2="{W-margin["right"]}" y2="{ny}" '
               f'stroke="#f0883e" stroke-width="1.5" stroke-dasharray="6,3"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{ny+4}" font-size="11" fill="#f0883e" font-weight="bold">'
               f'颈线 {neck_price:.2f}</text>')

    # 目标线
    if target < max_p * 1.15:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W-margin["right"]}" y2="{ty}" '
                   f'stroke="#a371f7" stroke-width="1.2" stroke-dasharray="4,4"/>')
        svg.append(f'<text x="{W-margin["right"]+5}" y="{ty+4}" font-size="11" fill="#a371f7" font-weight="bold">'
                   f'目标 {target:.2f} (+{upside_pct:.1f}%)</text>')

    # 左底标记
    svg.append(f'<circle cx="{px(pattern["left_idx"])}" cy="{py(pattern["left_price"])}" r="6" '
               f'fill="#238636" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["left_idx"])}" y="{py(pattern["left_price"])+20}" '
               f'text-anchor="middle" font-size="10" fill="#3fb950">左底 {pattern["left_price"]:.2f}</text>')

    # 右底标记
    svg.append(f'<circle cx="{px(pattern["right_idx"])}" cy="{py(pattern["right_price"])}" r="6" '
               f'fill="#8957e5" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["right_idx"])}" y="{py(pattern["right_price"])+20}" '
               f'text-anchor="middle" font-size="10" fill="#bc8cff">右底 {pattern["right_price"]:.2f}</text>')

    # 突破点标记
    svg.append(f'<circle cx="{px(pattern["break_idx"])}" cy="{ny}" r="7" '
               f'fill="#f0883e" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["break_idx"])}" y="{ny-12}" '
               f'text-anchor="middle" font-size="10" fill="#f0883e">突破</text>')

    # 现价标记
    cpy = py(current_price)
    svg.append(f'<line x1="{px(n-1)}" y1="{cpy}" x2="{W-margin["right"]}" y2="{cpy}" '
               f'stroke="#f85149" stroke-width="1"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{cpy+4}" font-size="11" fill="#f85149" font-weight="bold">'
               f'现价 {current_price:.2f}</text>')

    # 底部: 高分原因
    base_y = H - margin['bottom'] + 18
    svg.append(f'<text x="{margin["left"]}" y="{base_y}" font-size="13" fill="#58a6ff" font-weight="bold">筛选高分原因:</text>')
    for i, r in enumerate(reasons[:5]):
        svg.append(f'<text x="{margin["left"]+10}" y="{base_y+20+i*18}" font-size="11" fill="#c9d1d9">  {i+1}. {r}</text>')

    # 右侧信息栏
    info_x = W - margin['right'] + 8
    info_y = margin['top'] + 20
    svg.append(f'<text x="{info_x}" y="{info_y}" font-size="11" fill="#8b949e">突破日: {format_date(pattern["break_date"])}</text>')
    svg.append(f'<text x="{info_x}" y="{info_y+18}" font-size="11" fill="#8b949e">突破后涨幅: {post_breakout_pct:.1f}%</text>')
    svg.append(f'<text x="{info_x}" y="{info_y+36}" font-size="11" fill="#8b949e">目标空间: {upside_pct:.1f}%</text>')
    svg.append(f'<text x="{info_x}" y="{info_y+54}" font-size="11" fill="#8b949e">形态跨度: {pattern["gap"]}根K线</text>')

    svg.append('</svg>')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg))

# ============ 主程序 ============

def build_discord_message(top10):
    """构建Discord消息"""
    lines = []
    lines.append("🔍 **全A股双底突破扫描结果** (2026-05-19)")
    lines.append("")
    lines.append("扫描全市场正常上市A股，筛选双底形态刚突破颈线的标的。")
    lines.append("条件: 双底始于2025年12月 | 突破涨幅≤5% | 剩余空间≥8%")
    lines.append("排序: 按评分(综合技术面)降序")
    lines.append("")

    for i, item in enumerate(top10):
        lines.append(f"**#{i+1} {item['name']} ({item['code']})**  评分:{item['score']}/100")
        lines.append(f"  左底: {item['left_date']} @{item['left_price']}  |  右底: {item['right_date']} @{item['right_price']}")
        lines.append(f"  颈线: {item['neck_price']}  |  现价: {item['current_price']}  |  目标: {item['target_price']}")
        lines.append(f"  突破日: {item['break_date']} ({item['days_since_break']}天前)")
        lines.append(f"  突破后涨幅: {item['post_breakout_pct']:.1f}%  |  剩余空间: {item['upside_pct']:.1f}%")
        reasons_str = ', '.join(item['reasons'][:4])
        lines.append(f"  ✅ {reasons_str}")
        lines.append("")

    lines.append("⚠️ 仅供参考，不构成投资建议。")
    return '\n'.join(lines)

def main():
    print("=" * 50, flush=True)
    print("双底突破形态扫描 (全A股版)", flush=True)
    print("=" * 50, flush=True)

    print("\n[1/4] 获取全A股股票列表...", flush=True)
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}
    print(f"  共 {len(stocks)} 只正常上市A股", flush=True)

    scan_codes = list(stock_map.keys())
    print(f"  准备扫描 {len(scan_codes)} 只...", flush=True)

    print(f"\n[2/4] 扫描双底形态...", flush=True)
    all_patterns = []
    scanned = 0
    start_time = time.time()

    for idx, code in enumerate(scan_codes):
        if idx % 50 == 0 and idx > 0:
            elapsed = time.time() - start_time
            eta = (elapsed / idx) * (len(scan_codes) - idx)
            print(f"  进度: {idx}/{len(scan_codes)} | 命中: {len(all_patterns)} | ETA: {eta/60:.0f}分钟", flush=True)

        try:
            df = get_daily_data(code)
            if not df or len(df) < 60:
                continue

            patterns = detect_double_bottom(df, window=8)
            name = stock_map.get(code, code)

            for p in patterns:
                score, reasons = score_pattern(df, p)
                if score >= 40:
                    cp = float(df[-1]['close'])
                    min_b = min(p['left_price'], p['right_price'])
                    target = p['neck_price'] + (p['neck_price'] - min_b)
                    space = (target - cp) / cp * 100
                    days_ago = len(df) - 1 - p['break_idx']
                    post_breakout = (cp - p['neck_price']) / p['neck_price'] * 100

                    all_patterns.append({
                        'code': code,
                        'name': name,
                        'score': score,
                        'break_date': p['break_date'],
                        'days_since_break': days_ago,
                        'left_date': format_date(p['left_date']),
                        'left_price': round(p['left_price'], 2),
                        'right_date': format_date(p['right_date']),
                        'right_price': round(p['right_price'], 2),
                        'neck_price': round(p['neck_price'], 2),
                        'current_price': round(cp, 2),
                        'target_price': round(target, 2),
                        'upside_pct': round(space, 1),
                        'post_breakout_pct': round(post_breakout, 1),
                        'reasons': reasons,
                        'df': df,
                        'pattern': p,
                    })
            scanned += 1
            time.sleep(API_SLEEP)
        except:
            continue

    # 排序: 评分降序, 突破天数升序
    all_patterns.sort(key=lambda x: (-x['score'], x['days_since_break']))
    top10 = all_patterns[:TOP_N]

    elapsed = time.time() - start_time
    print(f"\n[3/4] 扫描完成: 扫描{scanned}只, 命中{len(all_patterns)}个", flush=True)
    print(f"  耗时: {elapsed/60:.1f}分钟", flush=True)
    print("=" * 80, flush=True)
    for i, item in enumerate(top10):
        print(f"  #{i+1}: {item['name']} ({item['code']})  评分:{item['score']}  "
              f"突破:{item['break_date']} ({item['days_since_break']}天前)  "
              f"现价:{item['current_price']}  目标:{item['target_price']}  空间:{item['upside_pct']}%", flush=True)

    # 生成图表
    print(f"\n[4/4] 生成前{TOP_N}名图表...", flush=True)
    chart_dir = f'/mnt/e/Hermes_workspace/Project/double_bottom_charts_20260519'
    os.makedirs(chart_dir, exist_ok=True)

    for i, item in enumerate(top10):
        svg_path = os.path.join(chart_dir, f'top{i+1}_{item["code"]}_{item["name"]}.svg')
        draw_svg_chart(item['df'], item['pattern'], item['score'], item['reasons'],
                       item['name'], item['code'], svg_path)
        print(f"  SVG: {svg_path}", flush=True)

    # 保存JSON结果
    result_data = []
    for item in top10:
        d = {k: v for k, v in item.items() if k not in ('df', 'pattern')}
        d['svg_path'] = os.path.join(chart_dir, f'top{i+1}_{item["code"]}_{item["name"]}.svg')
        result_data.append(d)

    output_path = '/mnt/e/Hermes_workspace/Project/double_bottom_full_results.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'scan_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'end_date': END_DATE,
            'total_scanned': scanned,
            'total_matches': len(all_patterns),
            'top10': result_data,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {output_path}", flush=True)

    # Discord消息
    print("\n" + "=" * 80, flush=True)
    print("DISCORD MESSAGE:", flush=True)
    msg = build_discord_message(top10)
    print(msg, flush=True)

if __name__ == '__main__':
    start_time = time.time()
    print("Script starting...", flush=True)
    main()
    total = time.time() - start_time
    print(f"\n总耗时: {total/60:.1f} 分钟", flush=True)
