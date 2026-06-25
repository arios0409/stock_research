"""
双底形态扫描器 v3 — 干净版
═══════════════════════════════════════════
- 全A股扫描（排除ST/退市）
- 每500只打擂台：保留得分最高的20只写入CSV
- 含行业列
- 最后top5画SVG图表
- 输出到 output/YYYYMMDD/ 目录
═══════════════════════════════════════════
"""

import urllib.request
import json
import os
import time
import math
from datetime import datetime

# ═══════════════════ 配置 ═══════════════════
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'

TODAY = datetime.now().strftime('%Y%m%d')
END_DATE = TODAY
START_DATE = '20241001'          # 日线数据起始
PLOT_START = '20240501'          # 画图数据起始（2年）
DB_START = '20250625'  # 1年内 (2026-06-25 - 365天)            # 双底形态起始日期
API_SLEEP = 0.12                 # API节流
BATCH_SIZE = 500                 # 每批扫描数量
TOP_K = 20                       # CSV保留数
TOP_CHART = 5                    # 画图数
MIN_SCORE = 40                   # 最低评分

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output', TODAY)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ═══════════════════ Tushare API ═══════════════════

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields:
        payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data,
                                 headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') != 0:
            return None
        return result.get('data', {})
    except Exception:
        return None


def get_stock_list():
    """获取全A股列表，排除ST/退市"""
    result = api_call('stock_basic',
                      fields='ts_code,symbol,name,industry,list_status')
    if not result or 'fields' not in result or 'items' not in result:
        return [], {}, {}
    fields = result['fields']
    stocks = []
    stock_map = {}
    industry_map = {}
    for item in result['items']:
        d = dict(zip(fields, item))
        if d.get('list_status') != 'L':
            continue
        name = d.get('name', '')
        if 'ST' in name or '退' in name:
            continue
        stocks.append(d)
        stock_map[d['ts_code']] = d['name']
        industry_map[d['ts_code']] = d.get('industry', '')
    return stocks, stock_map, industry_map


def get_daily(ts_code):
    """获取日线数据"""
    result = api_call('daily', ts_code=ts_code,
                      start_date=START_DATE, end_date=END_DATE)
    if not result or 'fields' not in result or 'items' not in result:
        return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df


def get_daily_plot(ts_code):
    """获取画图用日线（2年）"""
    result = api_call('daily', ts_code=ts_code,
                      start_date=PLOT_START, end_date=END_DATE)
    if not result or 'fields' not in result or 'items' not in result:
        return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df


# ═══════════════════ 技术指标 ═══════════════════

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


# ═══════════════════ 双底检测 ═══════════════════

def detect_double_bottom(df, window=8):
    """检测W双底形态"""
    n = len(df)
    if n < window * 2 + 1:
        return []

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)

    # 找局部低点
    lows = []
    for i in range(window, n - window):
        price = closes[i]
        bs = max(0, i - window)
        ae = min(n, i + window + 1)
        if all(closes[j] > price for j in range(bs, ae) if j != i):
            lows.append((i, price, volumes[i]))

    if len(lows) < 2:
        return []

    # 找局部高点（颈线候选）
    highs = []
    for i in range(window, n - window):
        price = closes[i]
        bs = max(0, i - window)
        ae = min(n, i + window + 1)
        if all(closes[j] < price for j in range(bs, ae) if j != i):
            highs.append((i, price))

    if not highs:
        return []

    results = []
    for i in range(len(lows) - 1):
        l1_idx, l1_price, l1_vol = lows[i]
        l2_idx, l2_price, l2_vol = lows[i + 1]

        # 形态跨度：15~150根K线
        gap = l2_idx - l1_idx
        if gap < 15 or gap > 150:
            continue

        # 两底价格差 < 5%
        if abs(l1_price - l2_price) / min(l1_price, l2_price) > 0.05:
            continue

        # 找两底之间的最高点作为颈线
        necks = [h for h in highs if l1_idx < h[0] < l2_idx]
        if not necks:
            continue
        n_idx, n_price = max(necks, key=lambda x: x[1])

        # 颈线至少高于底部5%
        if n_price / min(l1_price, l2_price) < 1.05:
            continue

        # 左底必须在双底起始日期之后
        if dates[l1_idx] < DB_START:
            continue

        # 找突破点：右底之后首次收盘超过颈线1%
        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:
                break_idx = j
                break
        if break_idx is None:
            continue

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


def score_pattern(df, pattern):
    """评分系统：满分100"""
    score = 0
    reasons = []
    current_price = float(df[-1]['close'])
    n = len(df)
    neck_price = pattern['neck_price']

    # 现价必须高于颈线，且不超过颈线5%（防止追高）
    if current_price <= neck_price:
        return -1, []
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05:
        return -1, []

    # 目标空间 >= 8%
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08:
        return -1, []

    # 1. 突破新鲜度（25分）
    break_idx = pattern['break_idx']
    days_since_break = n - 1 - break_idx
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
        reasons.append(f'突破已{days_since_break}天')

    # 2. 右底缩量（20分）
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

    # 3. 形态跨度（15分）
    gap = pattern['gap']
    if gap >= 30:
        score += 15
        reasons.append(f'形态跨度大({gap}根K线)')
    elif gap >= 20:
        score += 10
        reasons.append(f'形态跨度适中({gap}根K线)')

    # 4. MACD底背离（15分）
    if pattern['right_macd'] > pattern['left_macd'] and pattern['left_price'] >= pattern['right_price']:
        score += 15
        reasons.append('MACD底背离')
    elif pattern['right_macd'] > pattern['left_macd']:
        score += 10
        reasons.append('MACD改善')

    # 5. 右底高于左底（10分）
    if pattern['right_price'] > pattern['left_price']:
        score += 10
        reasons.append('右底高于左底')
    elif abs(pattern['right_price'] - pattern['left_price']) / pattern['left_price'] < 0.01:
        score += 8
        reasons.append('两底齐平')

    # 6. 振幅合理（10分）
    h = pattern['height_pct']
    if 0.10 <= h <= 0.25:
        score += 10
        reasons.append(f'振幅理想({h:.1%})')
    elif 0.08 <= h < 0.10:
        score += 7
        reasons.append(f'振幅合理({h:.1%})')

    # 7. RSI底背离（5分）
    if pattern['right_rsi'] > pattern['left_rsi'] and pattern['left_price'] >= pattern['right_price']:
        score += 5
        reasons.append('RSI底背离')

    return score, reasons


# ═══════════════════ CSV 擂台 ═══════════════════

CSV_COLS = ['排名', '代码', '名称', '行业', '评分',
            '左底日期', '左底价格', '右底日期', '右底价格',
            '颈线价格', '突破日期', '当前价格', '目标价格',
            '突破后涨幅%', '剩余空间%', '突破天数', '形态跨度']


def read_existing_top20(csv_path):
    """读取已有CSV中的top20记录"""
    if not os.path.exists(csv_path):
        return []
    rows = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
    if len(lines) < 2:
        return []
    for line in lines[1:]:
        parts = line.strip().split(',')
        if len(parts) < 17:
            continue
        try:
            rows.append({
                'code': parts[1],
                'name': parts[2],
                'industry': parts[3],
                'score': int(parts[4]),
                'left_date': parts[5],
                'left_price': float(parts[6]),
                'right_date': parts[7],
                'right_price': float(parts[8]),
                'neck_price': float(parts[9]),
                'break_date': parts[10],
                'current_price': float(parts[11]),
                'target_price': float(parts[12]),
                'post_breakout_pct': float(parts[13]),
                'upside_pct': float(parts[14]),
                'days_since_break': int(parts[15]),
                'gap': int(parts[16]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def write_top20_csv(records, csv_path):
    """写入top20 CSV（按评分降序，突破天数升序）"""
    sorted_records = sorted(records,
                            key=lambda x: (-x['score'], x['days_since_break']))
    top20 = sorted_records[:TOP_K]

    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write(','.join(CSV_COLS) + '\n')
        for i, r in enumerate(top20):
            f.write(f"{i + 1},{r['code']},{r['name']},{r.get('industry', '')},"
                    f"{r['score']},"
                    f"{r['left_date']},{r['left_price']},"
                    f"{r['right_date']},{r['right_price']},"
                    f"{r['neck_price']},{r['break_date']},"
                    f"{r['current_price']},{r['target_price']},"
                    f"{r['post_breakout_pct']},{r['upside_pct']},"
                    f"{r['days_since_break']},{r['gap']}\n")
    return top20


def merge_and_save(new_hits, csv_path, batch_label):
    """合并新旧结果，保留top20，写入CSV"""
    existing = read_existing_top20(csv_path)
    # 合并去重（按code+break_date）
    seen = set()
    merged = []
    for r in existing:
        key = (r['code'], r['break_date'])
        if key not in seen:
            seen.add(key)
            merged.append(r)
    for r in new_hits:
        key = (r['code'], r['break_date'])
        if key not in seen:
            seen.add(key)
            merged.append(r)
    top20 = write_top20_csv(merged, csv_path)
    print(f"  [擂台 {batch_label}] 旧{len(existing)} + 新{len(new_hits)} -> 合并{len(merged)} -> top20已写入")
    # 打印当前top5
    print(f"  --- 当前TOP5 ---")
    for i, r in enumerate(top20[:5]):
        print(f"  {i + 1}. {r['name']}({r['code']}) 评分{r['score']} "
              f"行业:{r.get('industry','?')} 剩余空间{r['upside_pct']}%")
    return top20


# ═══════════════════ SVG 图表 ═══════════════════

def fmt_date(ds):
    return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"


def draw_svg_chart(df, pattern, score, reasons, stock_name, stock_code, save_path):
    W, H = 1000, 720
    margin = {'top': 60, 'right': 80, 'bottom': 120, 'left': 80}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.60
    vol_h = chart_h * 0.22
    gap_h = chart_h * 0.06

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    n = len(df)

    neck_price = pattern['neck_price']
    current_price = closes[-1]
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    post_breakout_pct = (current_price - neck_price) / neck_price * 100
    upside_pct = (target - current_price) / current_price * 100

    min_p = min(closes) * 0.97
    max_p = max(closes) * 1.02
    max_v = max(volumes) * 1.2

    def px(i):
        return margin['left'] + (i / (n - 1)) * chart_w

    def py(price):
        return margin['top'] + (1 - (price - min_p) / (max_p - min_p)) * price_h

    def vy(vol):
        return margin['top'] + price_h + gap_h + (1 - vol / max_v) * vol_h

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    svg.append(f'<rect width="{W}" height="{H}" fill="#0d1117"/>')

    # 标题
    svg.append(f'<text x="{W / 2}" y="24" text-anchor="middle" font-size="17" fill="#58a6ff" font-weight="bold">'
               f'{stock_name} ({stock_code})  W双底突破</text>')
    svg.append(f'<text x="{W / 2}" y="44" text-anchor="middle" font-size="13" fill="#8b949e">'
               f'评分:{score}/100 | 突破后涨幅:{post_breakout_pct:.1f}% | 目标空间:{upside_pct:.1f}%</text>')

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        svg.append(
            f'<line x1="{margin["left"]}" y1="{yy}" x2="{W - margin["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
        svg.append(
            f'<text x="{margin["left"] - 8}" y="{yy + 4}" text-anchor="end" font-size="10" fill="#8b949e">{gp:.2f}</text>')

    # 日期标签
    step = max(1, n // 8)
    for i in range(0, n, step):
        svg.append(
            f'<text x="{px(i)}" y="{margin["top"] + price_h + gap_h + vol_h + 15}" text-anchor="middle" font-size="9" fill="#8b949e">{fmt_date(dates[i])}</text>')

    # 双底区域高亮
    hl_start = max(0, pattern['left_idx'] - 10)
    hl_end = min(n - 1, pattern['break_idx'] + 5)
    svg.append(f'<rect x="{px(hl_start)}" y="{margin["top"]}" width="{px(hl_end) - px(hl_start)}" '
               f'height="{price_h + vol_h + gap_h}" fill="#238636" opacity="0.08" rx="3"/>')
    svg.append(f'<text x="{(px(hl_start) + px(hl_end)) / 2}" y="{margin["top"] - 6}" text-anchor="middle" '
               f'font-size="11" fill="#3fb950" font-weight="bold">▼ 双底区域 ▼</text>')

    # 成交量柱
    for i in range(n):
        bar_w = max(1, chart_w / n * 0.6)
        x = px(i) - bar_w / 2
        y = vy(volumes[i])
        bh = margin['top'] + price_h + gap_h + vol_h - y
        color = '#3fb950' if closes[i] >= (closes[i - 1] if i > 0 else closes[i]) else '#f85149'
        svg.append(
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" opacity="0.45"/>')

    # 价格线
    pts = ' '.join(f'{px(i)},{py(closes[i])}' for i in range(n))
    svg.append(f'<polyline points="{pts}" stroke="#58a6ff" stroke-width="1.8" fill="none"/>')

    # 颈线
    ny = py(neck_price)
    svg.append(f'<line x1="{margin["left"]}" y1="{ny}" x2="{W - margin["right"]}" y2="{ny}" '
               f'stroke="#f0883e" stroke-width="2" stroke-dasharray="8,4"/>')
    svg.append(
        f'<text x="{W - margin["right"] + 5}" y="{ny + 5}" font-size="11" fill="#f0883e" font-weight="bold">'
        f'━ 颈线 {neck_price:.2f}</text>')

    # 目标线
    if target < max_p * 1.15:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W - margin["right"]}" y2="{ty}" '
                   f'stroke="#a371f7" stroke-width="1.5" stroke-dasharray="5,5"/>')
        svg.append(
            f'<text x="{W - margin["right"] + 5}" y="{ty + 5}" font-size="11" fill="#a371f7" font-weight="bold">'
            f'▼ 目标 {target:.2f} (+{upside_pct:.1f}%)</text>')

    # 左底
    svg.append(f'<circle cx="{px(pattern["left_idx"])}" cy="{py(pattern["left_price"])}" r="7" '
               f'fill="#238636" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["left_idx"])}" y="{py(pattern["left_price"]) + 20}" '
               f'text-anchor="middle" font-size="10" fill="#3fb950">左底 ¥{pattern["left_price"]:.2f}</text>')

    # 右底
    svg.append(f'<circle cx="{px(pattern["right_idx"])}" cy="{py(pattern["right_price"])}" r="7" '
               f'fill="#8957e5" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["right_idx"])}" y="{py(pattern["right_price"]) + 20}" '
               f'text-anchor="middle" font-size="10" fill="#bc8cff">右底 ¥{pattern["right_price"]:.2f}</text>')

    # 突破点
    svg.append(f'<circle cx="{px(pattern["break_idx"])}" cy="{ny}" r="8" '
               f'fill="#f0883e" stroke="#fff" stroke-width="2.5"/>')
    svg.append(f'<text x="{px(pattern["break_idx"])}" y="{ny - 14}" '
               f'text-anchor="middle" font-size="11" fill="#f0883e" font-weight="bold">★ 突破</text>')

    # 现价
    cpy_ = py(current_price)
    svg.append(f'<line x1="{px(n - 1)}" y1="{cpy_}" x2="{W - margin["right"]}" y2="{cpy_}" '
               f'stroke="#88ccff" stroke-width="1.5"/>')
    svg.append(
        f'<text x="{W - margin["right"] + 5}" y="{cpy_ + 5}" font-size="11" fill="#88ccff" font-weight="bold">'
        f'● 现价 {current_price:.2f}</text>')

    # 评分原因
    base_y = H - margin['bottom'] + 18
    svg.append(
        f'<text x="{margin["left"]}" y="{base_y}" font-size="13" fill="#58a6ff" font-weight="bold">评分原因 (总分: {score}):</text>')
    for i, r in enumerate(reasons[:6]):
        svg.append(
            f'<text x="{margin["left"] + 10}" y="{base_y + 18 + i * 16}" font-size="11" fill="#c9d1d9">{i + 1}. {r}</text>')

    # 信息栏
    info_x = W - margin['right'] + 8
    info_y = margin['top'] + 20
    svg.append(
        f'<text x="{info_x}" y="{info_y}" font-size="10" fill="#8b949e">突破日: {fmt_date(pattern["break_date"])}</text>')
    svg.append(
        f'<text x="{info_x}" y="{info_y + 16}" font-size="10" fill="#8b949e">突破后涨幅: {post_breakout_pct:.1f}%</text>')
    svg.append(
        f'<text x="{info_x}" y="{info_y + 32}" font-size="10" fill="#8b949e">目标空间: {upside_pct:.1f}%</text>')
    svg.append(
        f'<text x="{info_x}" y="{info_y + 48}" font-size="10" fill="#8b949e">形态跨度: {pattern["gap"]}根K线</text>')

    svg.append('</svg>')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg))


# ═══════════════════ 主流程 ═══════════════════

def scan_batch(codes, stock_map, industry_map, start_idx, total):
    """扫描一批股票，返回命中列表"""
    hits = []
    for j, code in enumerate(codes):
        idx = start_idx + j
        try:
            df = get_daily(code)
            if not df or len(df) < 60:
                continue

            patterns = detect_double_bottom(df, window=8)
            name = stock_map.get(code, code)
            industry = industry_map.get(code, '')

            for p in patterns:
                score, reasons = score_pattern(df, p)
                if score >= MIN_SCORE:
                    cp = float(df[-1]['close'])
                    min_b = min(p['left_price'], p['right_price'])
                    target = p['neck_price'] + (p['neck_price'] - min_b)
                    days_ago = len(df) - 1 - p['break_idx']
                    post_breakout = (cp - p['neck_price']) / p['neck_price'] * 100

                    hits.append({
                        'code': code,
                        'name': name,
                        'industry': industry,
                        'score': score,
                        'left_date': fmt_date(p['left_date']),
                        'left_price': round(p['left_price'], 2),
                        'right_date': fmt_date(p['right_date']),
                        'right_price': round(p['right_price'], 2),
                        'neck_price': round(p['neck_price'], 2),
                        'break_date': p['break_date'],
                        'current_price': round(cp, 2),
                        'target_price': round(target, 2),
                        'post_breakout_pct': round(post_breakout, 1),
                        'upside_pct': round((target - cp) / cp * 100, 1),
                        'days_since_break': days_ago,
                        'gap': p['gap'],
                        '_pattern': p,
                        '_reasons': reasons,
                    })
            time.sleep(API_SLEEP)
        except Exception:
            continue
    return hits


def main():
    print("=" * 65)
    print("  双底突破形态扫描器 v3 (干净版)")
    print(f"  日期: {TODAY}")
    print(f"  股票池: 全A股 (排除ST/退市)")
    print(f"  策略: 每{BATCH_SIZE}只打擂台，保留top{TOP_K}")
    print(f"  输出: {OUTPUT_DIR}")
    print("=" * 65)

    # [1] 获取股票列表
    print("\n[1/4] 获取全A股股票列表...")
    stocks, stock_map, industry_map = get_stock_list()
    if not stocks:
        print("  错误：无法获取股票列表！")
        return
    codes = [s['ts_code'] for s in stocks]

    # 板块统计
    sh = sum(1 for c in codes if c.endswith('.SH') and not c.startswith('688'))
    sz = sum(1 for c in codes if c.endswith('.SZ') and not c.startswith('300'))
    cyb = sum(1 for c in codes if c.startswith('300'))
    kcb = sum(1 for c in codes if c.startswith('688'))
    print(f"  共 {len(codes)} 只 | 沪市:{sh} 深市:{sz} 创业板:{cyb} 科创板:{kcb}")

    total_batches = (len(codes) + BATCH_SIZE - 1) // BATCH_SIZE
    csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_K}_双底突破_{TODAY}.csv')

    # [2] 分批扫描 + 打擂台
    print(f"\n[2/4] 分批扫描 (每批{BATCH_SIZE}只，共{total_batches}批)...")
    start_time = time.time()
    total_hits = 0

    for batch_no in range(total_batches):
        batch_start = batch_no * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(codes))
        batch_codes = codes[batch_start:batch_end]

        label = f"第{batch_no + 1}/{total_batches}批 ({batch_start + 1}-{batch_end})"
        print(f"\n{'─' * 50}")
        print(f"  {label}")

        batch_hits = scan_batch(batch_codes, stock_map, industry_map, batch_start, len(codes))
        total_hits += len(batch_hits)
        print(f"  本批命中: {len(batch_hits)} 个形态 (评分>={MIN_SCORE})")

        # 合并打擂台
        merge_and_save(batch_hits, csv_path, label)

        # ETA
        elapsed = time.time() - start_time
        done = batch_end
        remaining = len(codes) - done
        if done > 0:
            eta = (elapsed / done) * remaining
            print(f"  进度: {done}/{len(codes)} | 累计命中:{total_hits} | ETA: {eta / 60:.0f}分钟")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 50}")
    print(f"  扫描完成! 总耗时: {elapsed / 60:.1f}分钟")
    print(f"  累计命中: {total_hits}个形态")

    # 读取最终top20
    final_top20 = read_existing_top20(csv_path)
    if not final_top20:
        print("\n  未发现任何符合条件的双底形态，退出。")
        return

    # [3] 画top5 SVG图表
    print(f"\n[3/4] 为top5生成SVG图表...")
    top5 = final_top20[:TOP_CHART]

    for i, item in enumerate(top5):
        code = item['code']
        name = item['name']
        print(f"  [{i + 1}] {code} {name} (评分:{item['score']})")

        # 重新拉日线画图
        df_plot = get_daily_plot(code)
        if not df_plot or len(df_plot) < 60:
            print(f"      画图数据不足，跳过")
            continue

        # 重新检测形态（用画图数据）
        patterns = detect_double_bottom(df_plot, window=8)
        if not patterns:
            print(f"      未检测到形态，跳过")
            continue

        # 找最佳匹配的形态
        best_p = max(patterns, key=lambda p: p['neck_price'])
        score, reasons = score_pattern(df_plot, best_p)
        if score < 0:
            score = item['score']
            reasons = []

        svg_path = os.path.join(OUTPUT_DIR,
                                f'top{i + 1}_{code.split(".")[0]}_{name}_双底.svg')
        draw_svg_chart(df_plot, best_p, score, reasons, name, code, svg_path)
        print(f"      -> {os.path.basename(svg_path)}")
        time.sleep(API_SLEEP)

    # [4] 摘要
    print(f"\n[4/4] 最终结果")
    print("=" * 65)
    print(f"  {'排名':<5} {'代码':<12} {'名称':<10} {'评分':<5} {'行业':<12} {'突破日':<12} {'剩余空间':<8}")
    print("  " + "-" * 65)
    for i, item in enumerate(final_top20):
        code_short = item['code'].split('.')[0]
        print(f"  {i + 1:<5} {code_short:<12} {item['name']:<10} {item['score']:<5} "
              f"{item.get('industry', '')[:10]:<12} {item['break_date']:<12} {item['upside_pct']:<8.1f}%")

    svg_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.svg')]
    print(f"\n  输出目录: {OUTPUT_DIR}")
    print(f"  CSV: top{TOP_K}_双底突破_{TODAY}.csv ({len(final_top20)}条)")
    print(f"  SVG: {len(svg_files)}张图表")
    print(f"  耗时: {elapsed / 60:.1f}分钟")
    print("=" * 65)


if __name__ == '__main__':
    main()
