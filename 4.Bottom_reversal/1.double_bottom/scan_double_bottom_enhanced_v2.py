"""
双底形态扫描器 - 增强版 v2
新增: 断点续扫 — 每500只自动保存进度，崩溃/终止后可从断点恢复
股票池: 全A股 (沪深+创业板+科创板, 排除ST/退市)
输出: CSV(top20) + SVG图表(top5) -> output/YYYYMMDD/
"""
# ═══════════════════════════════════════════════════════════════
# v2 与 v1 的区别:
#   1. 每500只保存 checkpoint_double_bottom.json (当前索引 + 已累积的 all_patterns)
#   2. 启动时检测 checkpoint，存在则从断点恢复
#   3. 扫描完成后自动删除 checkpoint
#   4. 原 v1 脚本原封不动保留
# ═══════════════════════════════════════════════════════════════

import urllib.request
import json
import os
import sys
import time
import math
from datetime import datetime

# 双输出：同时写stdout和日志文件
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', f'{datetime.now().strftime("%Y%m%d")}', 'scan.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
LOG_FP = open(LOG_PATH, 'a' if os.path.exists(LOG_PATH) else 'w', buffering=1)  # v2: 追加模式

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, data):
        for f in self.files:
            f.write(data)
            f.flush()
    def flush(self):
        for f in self.files:
            f.flush()

sys.stdout = Tee(sys.stdout, LOG_FP)
sys.stderr = sys.stdout

# ============ 配置 ============
TUSHARE_TOKEN = '026586...ad60'
API_URL = 'http://api.tushare.pro'
TODAY = datetime.now().strftime('%Y%m%d')
END_DATE = TODAY
START_DATE = '20241001'
PLOT_START = '20240501'   # 2年画图数据
DOUBLE_BOTTOM_START = '20251201'  # 双底起始日期
API_SLEEP = 0.12
TOP_N_CSV = 20
TOP_N_CHART = 5

# 输出目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_BASE = os.path.join(SCRIPT_DIR, 'output')
OUTPUT_DIR = os.path.join(OUTPUT_BASE, TODAY)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# v2: checkpoint 文件
CHECKPOINT_PATH = os.path.join(OUTPUT_DIR, 'checkpoint_double_bottom.json')


# ============ Checkpoint 断点续扫 ============

def save_checkpoint(idx, all_patterns):
    """保存断点：当前扫描到的索引 + 已累积的所有形态（不含df，只存元数据）"""
    # 不存 df — 每只股票500+根日线，存进去会让checkpoint膨胀到GB级
    light = []
    for item in all_patterns:
        light.append({k: v for k, v in item.items() if k != 'df'})
    data = {
        'last_idx': idx,
        'all_patterns': light,
        'saved_at': datetime.now().isoformat()
    }
    tmp_path = CHECKPOINT_PATH + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, CHECKPOINT_PATH)


def load_checkpoint():
    """加载断点，返回 (start_idx, all_patterns) 或 (0, [])"""
    if not os.path.exists(CHECKPOINT_PATH):
        return 0, []
    try:
        with open(CHECKPOINT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        last_idx = data.get('last_idx', 0)
        all_patterns = data.get('all_patterns', [])
        print(f"  [断点恢复] 上次扫描到第 {last_idx+1} 只，已命中 {len(all_patterns)} 个形态")
        return last_idx + 1, all_patterns
    except Exception as e:
        print(f"  [警告] checkpoint 损坏: {e}，从头扫描")
        return 0, []


def clear_checkpoint():
    """扫描完成，删除断点文件"""
    if os.path.exists(CHECKPOINT_PATH):
        os.remove(CHECKPOINT_PATH)
        print(f"  [断点] checkpoint 已清除（扫描完成）")


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

    if current_price <= neck_price:
        return -1, []
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05:
        return -1, []

    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08:
        return -1, []

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
    W, H = 1000, 720
    margin = {'top': 60, 'right': 85, 'bottom': 115, 'left': 80}
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
    svg.append(f'<text x="{W/2}" y="24" text-anchor="middle" font-size="17" fill="#58a6ff" font-weight="bold">'
               f'{stock_name} ({stock_code})  W双底突破</text>')
    svg.append(f'<text x="{W/2}" y="44" text-anchor="middle" font-size="13" fill="#8b949e">'
               f'评分:{score}/100 | 突破后涨幅:{post_breakout_pct:.1f}% | 目标空间:{upside_pct:.1f}%</text>')

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-8}" y="{yy+4}" text-anchor="end" font-size="10" fill="#8b949e">{gp:.2f}</text>')

    # 日期标签
    step = max(1, n // 8)
    for i in range(0, n, step):
        svg.append(f'<text x="{px(i)}" y="{margin["top"]+price_h+gap_h+vol_h+15}" text-anchor="middle" font-size="9" fill="#8b949e">{format_date(dates[i])}</text>')

    # 双底区域高亮
    hl_start = max(0, pattern['left_idx'] - 10)
    hl_end = min(n - 1, pattern['break_idx'] + 5)
    svg.append(f'<rect x="{px(hl_start)}" y="{margin["top"]}" width="{px(hl_end)-px(hl_start)}" '
               f'height="{price_h+vol_h+gap_h}" fill="#238636" opacity="0.08" rx="3"/>')
    svg.append(f'<text x="{(px(hl_start)+px(hl_end))/2}" y="{margin["top"]-6}" text-anchor="middle" '
               f'font-size="11" fill="#3fb950" font-weight="bold">▼ 双底区域 ▼</text>')

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
               f'stroke="#f0883e" stroke-width="2" stroke-dasharray="8,4"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{ny+5}" font-size="11" fill="#f0883e" font-weight="bold">'
               f'━ 颈线 {neck_price:.2f}</text>')

    # 目标线
    if target < max_p * 1.15:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W-margin["right"]}" y2="{ty}" '
                   f'stroke="#a371f7" stroke-width="1.5" stroke-dasharray="5,5"/>')
        svg.append(f'<text x="{W-margin["right"]+5}" y="{ty+5}" font-size="11" fill="#a371f7" font-weight="bold">'
                   f'▼ 目标 {target:.2f} (+{upside_pct:.1f}%)</text>')

    # 左底标记
    svg.append(f'<circle cx="{px(pattern["left_idx"])}" cy="{py(pattern["left_price"])}" r="7" '
               f'fill="#238636" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["left_idx"])}" y="{py(pattern["left_price"])+20}" '
               f'text-anchor="middle" font-size="10" fill="#3fb950">左底 ¥{pattern["left_price"]:.2f}</text>')

    # 右底标记
    svg.append(f'<circle cx="{px(pattern["right_idx"])}" cy="{py(pattern["right_price"])}" r="7" '
               f'fill="#8957e5" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(pattern["right_idx"])}" y="{py(pattern["right_price"])+20}" '
               f'text-anchor="middle" font-size="10" fill="#bc8cff">右底 ¥{pattern["right_price"]:.2f}</text>')

    # 突破点
    svg.append(f'<circle cx="{px(pattern["break_idx"])}" cy="{ny}" r="8" '
               f'fill="#f0883e" stroke="#fff" stroke-width="2.5"/>')
    svg.append(f'<text x="{px(pattern["break_idx"])}" y="{ny-14}" '
               f'text-anchor="middle" font-size="11" fill="#f0883e" font-weight="bold">★ 突破</text>')

    # 现价标记
    cpy = py(current_price)
    svg.append(f'<line x1="{px(n-1)}" y1="{cpy}" x2="{W-margin["right"]}" y2="{cpy}" '
               f'stroke="#88ccff" stroke-width="1.5"/>')
    svg.append(f'<text x="{W-margin["right"]+5}" y="{cpy+5}" font-size="11" fill="#88ccff" font-weight="bold">'
               f'● 现价 {current_price:.2f}</text>')

    # 底部说明
    base_y = H - margin['bottom'] + 18
    svg.append(f'<text x="{margin["left"]}" y="{base_y}" font-size="13" fill="#58a6ff" font-weight="bold">筛选高分原因 (评分: {score}):</text>')
    for i, r in enumerate(reasons[:6]):
        svg.append(f'<text x="{margin["left"]+10}" y="{base_y+18+i*16}" font-size="11" fill="#c9d1d9">{i+1}. {r}</text>')

    # 右侧信息栏
    info_x = W - margin['right'] + 8
    info_y = margin['top'] + 20
    svg.append(f'<text x="{info_x}" y="{info_y}" font-size="10" fill="#8b949e">突破日: {format_date(pattern["break_date"])}</text>')
    svg.append(f'<text x="{info_x}" y="{info_y+16}" font-size="10" fill="#8b949e">突破后涨幅: {post_breakout_pct:.1f}%</text>')
    svg.append(f'<text x="{info_x}" y="{info_y+32}" font-size="10" fill="#8b949e">目标空间: {upside_pct:.1f}%</text>')
    svg.append(f'<text x="{info_x}" y="{info_y+48}" font-size="10" fill="#8b949e">形态跨度: {pattern["gap"]}根K线</text>')

    svg.append('</svg>')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg))


# ============ 主程序 ============

def write_incremental_csv(all_patterns, csv_path, label=""):
    """增量写入top20 CSV（排序）"""
    if not all_patterns:
        return 0
    sorted_patterns = sorted(all_patterns, key=lambda x: (-x['score'], x['days_since_break']))
    top20 = sorted_patterns[:TOP_N_CSV]

    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write('排名,代码,名称,行业,评分,左底日期,左底价格,右底日期,右底价格,'
                '颈线价格,突破日期,当前价格,目标价格,突破后涨幅_pct,剩余空间_pct,突破天数,形态跨度\n')
        for i, item in enumerate(top20):
            f.write(f'{i+1},{item["code"]},{item["name"]},{item.get("industry","")},{item["score"]},'
                    f'{item["left_date"]},{item["left_price"]},{item["right_date"]},{item["right_price"]},'
                    f'{item["neck_price"]},{item["break_date"]},{item["current_price"]},'
                    f'{item["target_price"]},{item["post_breakout_pct"]},{item["upside_pct"]},'
                    f'{item["days_since_break"]},{item["pattern"]["gap"]}\n')
    if label:
        print(f"  [增量CSV] {label}: {len(all_patterns)}个形态入池, top{TOP_N_CSV}已写入")
    return len(all_patterns)


def main():
    print("=" * 65)
    print("  双底突破形态扫描 - 增强版 v2 (断点续扫)")
    print(f"  扫描日期: {TODAY}")
    print(f"  股票池: 全A股 (含创业板+科创板, 排除ST/退市)")
    print(f"  输出: top20 CSV + top5 SVG → {OUTPUT_DIR}")
    print(f"  断点: {CHECKPOINT_PATH}")
    print("=" * 65)

    print("\n[1/5] 获取全A股股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}
    industry_map = {s['ts_code']: s.get('industry', '') for s in stocks}
    print(f"  共 {len(stocks)} 只正常上市A股")

    scan_codes = list(stock_map.keys())
    # 统计板块分布
    sh = sum(1 for c in scan_codes if c.endswith('.SH') and not c.startswith('688'))
    sz_main = sum(1 for c in scan_codes if c.endswith('.SZ') and not c.startswith('300'))
    cyb = sum(1 for c in scan_codes if c.startswith('300'))
    kcb = sum(1 for c in scan_codes if c.startswith('688'))
    print(f"  沪市主板:{sh}  深市主板:{sz_main}  创业板:{cyb}  科创板:{kcb}")
    print(f"  准备扫描 {len(scan_codes)} 只...")

    # v2: 加载断点
    print(f"\n[1.5/5] 检查断点...")
    start_idx, all_patterns = load_checkpoint()
    if start_idx > 0:
        print(f"  从第 {start_idx+1} 只开始继续扫描（共 {len(scan_codes)} 只）")
        csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_N_CSV}_双底突破_{TODAY}.csv')
        write_incremental_csv(all_patterns, csv_path, f"恢复 @ {start_idx}/{len(scan_codes)}")
    else:
        print(f"  无断点，从头开始扫描 {len(scan_codes)} 只")

    print(f"\n[2/5] 扫描双底形态...")
    csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_N_CSV}_双底突破_{TODAY}.csv')
    start_time = time.time()

    for idx in range(start_idx, len(scan_codes)):
        code = scan_codes[idx]

        if idx % 100 == 0 and idx > start_idx:
            elapsed = time.time() - start_time
            scanned = idx - start_idx
            remaining = len(scan_codes) - idx
            if scanned > 0:
                eta = (elapsed / scanned) * remaining
                print(f"  进度: {idx}/{len(scan_codes)} | 命中: {len(all_patterns)} | ETA: {eta/60:.0f}分钟")

        try:
            df = get_daily_data(code, start_date=PLOT_START)
            if not df or len(df) < 60:
                continue

            patterns = detect_double_bottom(df, window=8)
            name = stock_map.get(code, code)
            industry = industry_map.get(code, '')

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
                        'industry': industry,
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
            time.sleep(API_SLEEP)

            # v2: 每500只保存断点 + 增量CSV
            if (idx + 1) % 500 == 0:
                save_checkpoint(idx, all_patterns)
                write_incremental_csv(all_patterns, csv_path, f"{idx+1}/{len(scan_codes)}")
        except Exception:
            continue

    all_patterns.sort(key=lambda x: (-x['score'], x['days_since_break']))
    elapsed = time.time() - start_time

    print(f"  扫描完成: 命中{len(all_patterns)}个, 耗时{elapsed/60:.1f}分钟")

    if not all_patterns:
        print("\n  未发现符合条件的双底形态，退出。")
        clear_checkpoint()
        return

    top5_chart = all_patterns[:TOP_N_CHART]
    top20_csv = all_patterns[:TOP_N_CSV]

    # 3. CSV
    print(f"\n[3/5] 生成top20 CSV...")
    csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_N_CSV}_双底突破_{TODAY}.csv')
    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write('排名,代码,名称,行业,评分,左底日期,左底价格,右底日期,右底价格,'
                '颈线价格,突破日期,当前价格,目标价格,突破后涨幅_pct,剩余空间_pct,突破天数,形态跨度\n')
        for i, item in enumerate(top20_csv):
            f.write(f'{i+1},{item["code"]},{item["name"]},{item.get("industry","")},{item["score"]},'
                    f'{item["left_date"]},{item["left_price"]},{item["right_date"]},{item["right_price"]},'
                    f'{item["neck_price"]},{item["break_date"]},{item["current_price"]},'
                    f'{item["target_price"]},{item["post_breakout_pct"]},{item["upside_pct"]},'
                    f'{item["days_since_break"]},{item["pattern"]["gap"]}\n')
    print(f"  CSV: {csv_path}")

    # 4. SVG图表 — 只为top5单独拉日线，不再依赖checkpoint里的df
    print(f"\n[4/5] 为top5拉取日线并生成K线图(SVG)...")
    for i, item in enumerate(top5_chart):
        code = item['code']
        print(f"  [{i+1}] 拉取 {code} {item['name']} 日线...")
        df = get_daily_data(code, start_date=PLOT_START)
        if not df or len(df) < 60:
            print(f"      数据不足，跳过")
            continue
        # 用最新日线刷新当前价
        fresh_cp = float(df[-1]['close'])
        item['current_price'] = round(fresh_cp, 2)
        min_b = min(item['pattern']['left_price'], item['pattern']['right_price'])
        target = item['pattern']['neck_price'] + (item['pattern']['neck_price'] - min_b)
        item['target_price'] = round(target, 2)
        item['upside_pct'] = round((target - fresh_cp) / fresh_cp * 100, 1)
        item['post_breakout_pct'] = round((fresh_cp - item['pattern']['neck_price']) / item['pattern']['neck_price'] * 100, 1)
        svg_path = os.path.join(OUTPUT_DIR,
            f'top{i+1}_{item["code"].split(".")[0]}_{item["name"]}_双底.svg')
        draw_svg_chart(df, item['pattern'], item['score'],
                       item['reasons'], item['name'], item['code'], svg_path)
        print(f"      图表: {os.path.basename(svg_path)}")
        time.sleep(API_SLEEP)

    # 5. 摘要
    print(f"\n[5/5] 结果摘要")
    print("=" * 65)
    print(f"  {'排名':<5} {'代码':<12} {'名称':<8} {'评分':<5} {'突破日':<12} {'现价':<8} {'目标':<8} {'空间':<6}")
    print("  " + "-" * 60)
    for i, item in enumerate(top20_csv):
        print(f"  {i+1:<5} {item['code'].split('.')[0]:<12} {item['name']:<8} {item['score']:<5} "
              f"{item['break_date']:<12} ¥{item['current_price']:<7.2f} ¥{item['target_price']:<7.2f} {item['upside_pct']:<6.1f}%")

    print(f"\n  输出目录: {OUTPUT_DIR}")
    print(f"  CSV: {os.path.basename(csv_path)} ({len(top20_csv)}条)")
    print(f"  SVG: {TOP_N_CHART}张图表")
    print("=" * 65)

    # v2: 扫描完成，清除断点
    clear_checkpoint()


if __name__ == '__main__':
    main()
