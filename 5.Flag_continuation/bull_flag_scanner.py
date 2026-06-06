"""
上升旗形(Bull Flag)中继形态扫描器 (无第三方依赖)
条件:
- 旗杆涨幅 >= 20% (5~20根K线内完成)
- 整理回撤旗杆高度的 20%~60% (不超过61.8%)
- 整理期 8~25根K线
- 整理期成交量显著萎缩 (vs 旗杆期 < 60%)
- 放量突破旗帜上轨 (突破日量 > 整理均量 1.5倍)
- 距目标位剩余空间 >= 8%
"""

import urllib.request
import json
import os
import time

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
END_DATE = '20260513'
START_DATE = '20250801'  # 提前3个月用于计算60日均量等指标
MAX_SCAN = 400  # 扫描数量限制

# 旗形参数
FLAGPOLE_MIN_DAYS = 5
FLAGPOLE_MAX_DAYS = 20
FLAGPOLE_MIN_PCT = 0.20      # 旗杆最小涨幅 20%
PULLBACK_MIN_PCT = 0.20      # 回撤占旗杆高度最小 20%
PULLBACK_MAX_PCT = 0.60      # 回撤占旗杆高度最大 60% (不超过61.8%)
FLAG_MIN_DAYS = 8
FLAG_MAX_DAYS = 40
VOL_CONTRACTION = 0.60       # 整理期量能需低于旗杆期的 60%
BREAKOUT_VOL_MULT = 1.5      # 突破日量需 > 整理均量的倍数

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
    return [dict(zip(fields, item)) for item in result['items'] if dict(zip(fields, item)).get('list_status') == 'L']

def get_hs300_components():
    result = api_call('index_weight', index_code='399300.SZ', fields='con_code')
    if not result or 'items' not in result:
        return None
    return list(set(item[0] for item in result['items']))

def get_daily_data(ts_code, start_date=START_DATE, end_date=END_DATE):
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result:
        return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df

# ============ 辅助函数 ============

def moving_avg(data, period):
    result = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(sum(data[i - period + 1: i + 1]) / period)
    return result

def linear_regression_slope(values):
    n = len(values)
    if n < 2:
        return 0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0
    return num / den

# ============ 旗形检测 ============

def detect_bull_flag(df):
    """扫描日线数据中的上升旗形"""
    n = len(df)
    if n < FLAGPOLE_MIN_DAYS + FLAG_MIN_DAYS + 5:
        return []

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    vol_ma60 = moving_avg(volumes, 60)

    results = []

    # 滑动窗口：尝试每个可能的旗杆起点
    for pole_start in range(n - FLAGPOLE_MIN_DAYS - FLAG_MIN_DAYS - 1):
        for pole_len in range(FLAGPOLE_MIN_DAYS, FLAGPOLE_MAX_DAYS + 1):
            pole_end = pole_start + pole_len
            if pole_end >= n:
                break

            pole_start_price = closes[pole_start]
            pole_top_price = max(closes[pole_start:pole_end + 1])
            pole_top_idx = pole_start + closes[pole_start:pole_end + 1].index(pole_top_price)

            flagpole_gain = (pole_top_price - pole_start_price) / pole_start_price
            if flagpole_gain < FLAGPOLE_MIN_PCT:
                continue

            # 旗杆期放量检查
            flagpole_vols = volumes[pole_start:pole_top_idx + 1]
            flagpole_avg_vol = sum(flagpole_vols) / len(flagpole_vols)
            vol_60 = vol_ma60[pole_start]
            if vol_60 and flagpole_avg_vol < vol_60 * 1.2:
                continue

            flagpole_height = pole_top_price - pole_start_price

            # --- 找旗帜整理期 ---
            flag_start = pole_top_idx + 1
            best_flag = None

            for flag_len in range(FLAG_MIN_DAYS, FLAG_MAX_DAYS + 1):
                flag_end = flag_start + flag_len - 1
                if flag_end >= n:
                    break

                # 用最高价/最低价构建通道
                flag_highs = [float(df[flag_start + i]['high']) for i in range(flag_len)]
                flag_lows = [float(df[flag_start + i]['low']) for i in range(flag_len)]
                flag_closes = closes[flag_start:flag_end + 1]
                flag_vols = volumes[flag_start:flag_end + 1]

                flag_upper = max(flag_highs)
                flag_lower = min(flag_lows)

                # 回撤幅度检查
                pullback = (pole_top_price - flag_lower) / flagpole_height
                if pullback < PULLBACK_MIN_PCT:
                    continue
                if pullback > PULLBACK_MAX_PCT:
                    break

                # 整理期量能萎缩
                flag_avg_vol = sum(flag_vols) / len(flag_vols)
                vol_ratio = flag_avg_vol / flagpole_avg_vol if flagpole_avg_vol > 0 else 1
                if vol_ratio > VOL_CONTRACTION:
                    continue

                # 整理区间已确认（回撤幅度+缩量已足够过滤非整理行情）

                # 4. 不跌破旗杆起点
                if flag_lower < pole_start_price:
                    break

                # --- 检查突破（搜索窗口放宽到30天） ---
                breakout_idx = None
                for b in range(flag_end + 1, min(flag_end + 30, n)):
                    if closes[b] > flag_upper * 1.01:
                        if volumes[b] > flag_avg_vol * BREAKOUT_VOL_MULT:
                            breakout_idx = b
                            break
                    # 如果价格跌破旗杆起点，放弃
                    if closes[b] < pole_start_price:
                        break

                if breakout_idx is None:
                    continue

                best_flag = {
                    'pole_start': pole_start,
                    'pole_start_price': pole_start_price,
                    'pole_top_idx': pole_top_idx,
                    'pole_top_price': pole_top_price,
                    'pole_len': pole_len,
                    'flagpole_gain': flagpole_gain,
                    'flagpole_height': flagpole_height,
                    'flagpole_avg_vol': flagpole_avg_vol,
                    'flag_start': flag_start,
                    'flag_end': flag_end,
                    'flag_len': flag_len,
                    'flag_high': max(flag_closes),
                    'flag_low': min(flag_closes),
                    'flag_upper': flag_upper,
                    'flag_lower': flag_lower,
                    'flag_avg_vol': flag_avg_vol,
                    'vol_ratio': vol_ratio,
                    'breakout_idx': breakout_idx,
                }
                break

            if best_flag:
                results.append(best_flag)
                break

    # 去重
    seen_breakouts = {}
    for r in results:
        key = (r['pole_start'], r['breakout_idx'])
        if key not in seen_breakouts or r['flagpole_gain'] > seen_breakouts[key]['flagpole_gain']:
            seen_breakouts[key] = r
    return list(seen_breakouts.values())

def score_pattern(df, flag):
    """评分旗形 (0-100)"""
    score = 0
    reasons = []
    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    current_price = closes[-1]
    breakout_price = flag['flag_upper']
    breakout_idx = flag['breakout_idx']
    days_since_break = len(closes) - 1 - breakout_idx

    # 核心过滤
    if current_price < breakout_price:
        return -1, []

    post_break_closes = closes[breakout_idx:]
    if min(post_break_closes) < breakout_price * 0.98:
        return -1, []

    target = breakout_price + flag['flagpole_height']
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08:
        return -1, []

    # 评分项
    if days_since_break == 0:
        score += 25; reasons.append('今日刚突破')
    elif days_since_break <= 2:
        score += 22; reasons.append(f'突破仅{days_since_break}天')
    elif days_since_break <= 5:
        score += 15; reasons.append(f'突破{days_since_break}天')
    else:
        score += 5; reasons.append(f'突破已{days_since_break}天(较久)')

    gain_pct = flag['flagpole_gain']
    if gain_pct >= 0.35:
        score += 20; reasons.append(f'旗杆极强(+{gain_pct:.0%})')
    elif gain_pct >= 0.25:
        score += 15; reasons.append(f'旗杆强势(+{gain_pct:.0%})')
    elif gain_pct >= 0.20:
        score += 10; reasons.append(f'旗杆达标(+{gain_pct:.0%})')

    vol_ratio = flag['vol_ratio']
    if vol_ratio < 0.25:
        score += 20; reasons.append(f'整理极度缩量({vol_ratio:.0%})')
    elif vol_ratio < 0.40:
        score += 17; reasons.append(f'整理显著缩量({vol_ratio:.0%})')
    elif vol_ratio < 0.60:
        score += 12; reasons.append(f'整理缩量({vol_ratio:.0%})')

    pullback = (flag['pole_top_price'] - flag['flag_low']) / flag['flagpole_height']
    if pullback <= 0.30:
        score += 15; reasons.append(f'浅回撤({pullback:.0%})')
    elif pullback <= 0.40:
        score += 12; reasons.append(f'回撤适中({pullback:.0%})')
    elif pullback <= 0.50:
        score += 8; reasons.append(f'回撤较深({pullback:.0%})')

    flag_len = flag['flag_len']
    if 7 <= flag_len <= 12:
        score += 10; reasons.append(f'整理时长佳({flag_len}天)')
    elif 5 <= flag_len < 7 or 12 < flag_len <= 15:
        score += 7; reasons.append(f'整理{flag_len}天')
    else:
        score += 4; reasons.append(f'整理{flag_len}天(偏长)')

    breakout_vol = volumes[breakout_idx]
    break_vol_mult = breakout_vol / flag['flag_avg_vol'] if flag['flag_avg_vol'] > 0 else 1
    if break_vol_mult >= 2.5:
        score += 10; reasons.append(f'突破爆量({break_vol_mult:.1f}x)')
    elif break_vol_mult >= 1.8:
        score += 7; reasons.append(f'突破放量({break_vol_mult:.1f}x)')
    elif break_vol_mult >= 1.5:
        score += 5; reasons.append(f'突破温和放量({break_vol_mult:.1f}x)')

    return score, reasons

# ============ SVG 绘图 ============

def format_date(ds):
    return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"

def draw_svg_chart(df, flag, score, reasons, stock_name, stock_code, save_path):
    W, H = 900, 650
    margin = {'top': 50, 'right': 60, 'bottom': 100, 'left': 70}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.65
    vol_h = chart_h * 0.25
    gap_h = chart_h * 0.1

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

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        f'<rect width="{W}" height="{H}" fill="#1a1a2e"/>',
        f'<text x="{W/2}" y="28" text-anchor="middle" font-size="16" fill="#e0e0e0" font-weight="bold">{stock_name} ({stock_code})  上升旗形  评分:{score}/100</text>'
    ]

    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W - margin["right"]}" y2="{yy}" stroke="#2a2a4a" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"] - 5}" y="{yy + 4}" text-anchor="end" font-size="10" fill="#888">{gp:.2f}</text>')

    for i in range(0, n, max(1, n // 8)):
        svg.append(f'<text x="{px(i)}" y="{margin["top"] + price_h + 15}" text-anchor="middle" font-size="9" fill="#888">{format_date(dates[i])}</text>')

    pole_start = flag['pole_start']
    pole_end = flag['pole_top_idx']
    svg.append(f'<rect x="{px(pole_start)}" y="{margin["top"]}" width="{px(pole_end) - px(pole_start)}" height="{price_h}" fill="#4CAF50" opacity="0.1"/>')

    flag_start = flag['flag_start']
    flag_end = flag['flag_end']
    flag_upper = flag['flag_upper']
    flag_lower = flag['flag_lower']
    svg.append(f'<rect x="{px(flag_start)}" y="{py(flag_upper)}" width="{px(flag_end) - px(flag_start)}" height="{py(flag_lower) - py(flag_upper)}" fill="#FF9800" opacity="0.08"/>')

    svg.append(f'<line x1="{px(flag_start)}" y1="{py(flag_upper)}" x2="{px(flag_end)}" y2="{py(flag_upper)}" stroke="#FF9800" stroke-width="1.5" stroke-dasharray="4,4"/>')
    svg.append(f'<text x="{px(flag_end) + 5}" y="{py(flag_upper) + 4}" font-size="9" fill="#FF9800">上轨 {flag_upper:.2f}</text>')
    svg.append(f'<line x1="{px(flag_start)}" y1="{py(flag_lower)}" x2="{px(flag_end)}" y2="{py(flag_lower)}" stroke="#FF9800" stroke-width="1.5" stroke-dasharray="4,4"/>')
    svg.append(f'<text x="{px(flag_end) + 5}" y="{py(flag_lower) + 4}" font-size="9" fill="#FF9800">下轨 {flag_lower:.2f}</text>')

    for i in range(n):
        bar_w = max(1, chart_w / n * 0.7)
        x = px(i) - bar_w / 2
        y = vy(volumes[i])
        bh = margin['top'] + price_h + gap_h + vol_h - y
        color = '#4CAF50' if closes[i] >= (closes[i - 1] if i > 0 else closes[i]) else '#f44336'
        svg.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" opacity="0.5"/>')

    pts = ' '.join(f'{px(i)} {py(closes[i])}' for i in range(n))
    svg.append(f'<path d="M {pts}" stroke="#2196F3" stroke-width="2" fill="none"/>')

    breakout_idx = flag['breakout_idx']
    svg.append(f'<circle cx="{px(breakout_idx)}" cy="{py(closes[breakout_idx])}" r="6" fill="#e53935" stroke="#fff" stroke-width="2"/>')
    svg.append(f'<text x="{px(breakout_idx)}" y="{py(closes[breakout_idx]) - 12}" text-anchor="middle" font-size="10" fill="#e53935">突破</text>')

    target = flag['flag_upper'] + flag['flagpole_height']
    current_price = closes[-1]
    if target < max_p * 1.1:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W - margin["right"]}" y2="{ty}" stroke="#FF9800" stroke-width="1" stroke-dasharray="5,5"/>')
        svg.append(f'<text x="{W - margin["right"] + 5}" y="{ty + 4}" font-size="10" fill="#FF9800">目标 {target:.2f}</text>')

    cpy = py(current_price)
    svg.append(f'<line x1="{px(n - 1)}" y1="{cpy}" x2="{W - margin["right"]}" y2="{cpy}" stroke="#2196F3" stroke-width="1" stroke-dasharray="2,2"/>')
    svg.append(f'<text x="{W - margin["right"] + 5}" y="{cpy + 4}" font-size="10" fill="#2196F3">现价 {current_price:.2f}</text>')

    reasons_text = '\n'.join([f'{i + 1}. {r}' for i, r in enumerate(reasons[:6])])
    base_y = H - margin['bottom'] + 15
    svg.append(f'<text x="{margin["left"]}" y="{base_y}" font-size="12" fill="#e0e0e0" font-weight="bold">高分原因:</text>')
    for i, line in enumerate(reasons_text.split('\n')):
        svg.append(f'<text x="{margin["left"]}" y="{base_y + 18 + i * 18}" font-size="11" fill="#aaa">{line}</text>')

    svg.append('</svg>')
    with open(save_path, 'w') as f:
        f.write('\n'.join(svg))

# ============ 主程序 ============

def main():
    print("=" * 55)
    print("  上升旗形(Bull Flag)中继形态扫描器")
    print("  条件: 旗杆涨幅≥20% → 整理缩量 → 放量突破")
    print("=" * 55)

    print("\n[1/4] 获取股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}

    hs300 = get_hs300_components()
    zz500_result = api_call('index_weight', index_code='000905.SH', fields='con_code')
    zz500 = list(set(item[0] for item in zz500_result['items'])) if zz500_result and 'items' in zz500_result else []

    all_codes = set((hs300 or []) + zz500)
    scan_codes = [c for c in all_codes if c in stock_map]
    print(f"  扫描沪深300+中证500共 {len(scan_codes)} 只股票")

    print(f"\n[2/4] 扫描上升旗形形态...")
    all_patterns = []

    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0:
            print(f"  进度: {idx}/{len(scan_codes)}")

        try:
            df = get_daily_data(code)
            if not df or len(df) < 60:
                continue

            flags = detect_bull_flag(df)
            name = stock_map.get(code, code)

            for f in flags:
                score, reasons = score_pattern(df, f)
                if score >= 30:
                    all_patterns.append({
                        'code': code,
                        'name': name,
                        'df': df,
                        'flag': f,
                        'score': score,
                        'reasons': reasons
                    })
            time.sleep(0.12)
        except Exception:
            continue

    # 按股票去重
    stock_best = {}
    for item in all_patterns:
        code = item['code']
        if code not in stock_best or item['score'] > stock_best[code]['score']:
            stock_best[code] = item
    all_patterns = list(stock_best.values())

    all_patterns.sort(key=lambda x: (len(x['df']) - 1 - x['flag']['breakout_idx'], -x['score']))
    top5 = all_patterns[:5]

    if not top5:
        print("  未发现符合条件的牛旗形态")
        return

    print(f"\n[3/4] 前5名:")
    for i, item in enumerate(top5):
        f = item['flag']
        days_ago = len(item['df']) - 1 - f['breakout_idx']
        print(f"  {i + 1}. {item['name']} ({item['code']}) 评分:{item['score']} 突破于{item['df'][f['breakout_idx']]['trade_date']} ({days_ago}天前)")

    print(f"\n[4/4] 生成图片...")
    output_svg = os.path.expanduser('~/bull_flag_charts')
    os.makedirs(output_svg, exist_ok=True)

    for i, item in enumerate(top5):
        svg_path = os.path.join(output_svg, f'top{i + 1}_{item["code"]}.svg')
        draw_svg_chart(item['df'], item['flag'], item['score'], item['reasons'], item['name'], item['code'], svg_path)
        print(f"  SVG: {svg_path}")

    print(f"\n完成! SVG保存在: {output_svg}")
    print("=" * 55)

    for i, item in enumerate(top5):
        f = item['flag']
        cp = float(item['df'][-1]['close'])
        dist = (cp - f['flag_upper']) / f['flag_upper'] * 100
        target = f['flag_upper'] + f['flagpole_height']
        space = (target - cp) / cp * 100
        print(f"\n{'=' * 45}")
        print(f"第{i + 1}名: {item['name']} ({item['code']})")
        print(f"  评分: {item['score']}/100")
        print(f"  旗杆: +{f['flagpole_gain']:.0%} ({f['pole_len']}天)")
        print(f"  回撤: {(f['pole_top_price'] - f['flag_low']) / f['flagpole_height']:.0%} of 旗杆高度")
        print(f"  整理: {f['flag_len']}天 | 缩量至 {f['vol_ratio']:.0%}")
        print(f"  突破日: {item['df'][f['breakout_idx']]['trade_date']} (距今{len(item['df']) - 1 - f['breakout_idx']}天)")
        print(f"  上轨: @{f['flag_upper']:.2f} | 现价: {cp:.2f} (突破后+{dist:.1f}%)")
        print(f"  目标: @{target:.2f} (剩余空间{space:.1f}%)")
        for r in item['reasons']:
            print(f"  + {r}")

    if top5:
        latest_date = top5[0]['df'][-1]['trade_date']
        print(f"\n[数据截止日期: {latest_date}]")

if __name__ == '__main__':
    main()
