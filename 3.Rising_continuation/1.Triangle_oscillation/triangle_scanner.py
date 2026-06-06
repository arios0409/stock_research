"""
三角收敛上涨中继形态扫描器 (纯Python + SVG)
条件:
- 三角收敛形态：高点下移 + 低点上移
- 收敛区域 15~100 个交易日
- 收敛幅度 3%~35%
- 突破上轨（阻力线）
- 前期趋势非下跌（前25天 > -3%）
- 量度目标涨幅 >= 8%
"""

import urllib.request
import json
import os
import time
import math
from datetime import datetime

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
END_DATE = '20260415'              # 形态筛选截止日
START_DATE = '20241001'            # 数据起始（往前多取用于趋势判断）
PLOT_END_DATE = datetime.now().strftime('%Y%m%d')
SCAN_WINDOW_MONTHS = 3            # 只保留END_DATE前N个月内的形态

# 三角参数
TRIANGLE_MIN_DAYS = 15
TRIANGLE_MAX_DAYS = 100
TRIANGLE_MIN_HEIGHT_PCT = 0.03
TRIANGLE_MAX_HEIGHT_PCT = 0.35
SWING_ORDER = 3                   # 局部极值窗口
BREAKOUT_LOOKAHEAD = 15           # 突破搜索窗口
PRE_TREND_BARS = 25               # 前期趋势判断窗口
PRE_TREND_MIN = -0.03             # 前期趋势不能跌超3%

# 评分权重
TIME_WEIGHT = 0.35
WIN_WEIGHT = 0.30
UPSIDE_WEIGHT = 0.35

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

def get_daily_data(ts_code, start_date=START_DATE, end_date=None):
    if end_date is None:
        end_date = PLOT_END_DATE
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result:
        return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df

# ============ 三角收敛检测 ============

def find_swings(closes, highs, lows, order=SWING_ORDER):
    """找局部极值点"""
    n = len(closes)
    swing_highs = []
    swing_lows = []
    for i in range(order, n - order):
        h = highs[i]
        l = lows[i]
        is_high = all(highs[j] <= h for j in range(i - order, i + order + 1) if j != i)
        is_low = all(lows[j] >= l for j in range(i - order, i + order + 1) if j != i)
        if is_high:
            swing_highs.append((i, h))
        if is_low:
            swing_lows.append((i, l))
    return swing_highs, swing_lows

def detect_triangle(df, scan_end_idx):
    """在扫描范围内检测三角收敛形态
    df: 行情数据 (closes, highs, lows, dates, volumes 提取后的列表)
    scan_end_idx: 扫描截止索引 (对应END_DATE)
    """
    n = len(df)
    closes = [float(d['close']) for d in df]
    highs = [float(d['high']) for d in df]
    lows = [float(d['low']) for d in df]

    swing_highs, swing_lows = find_swings(closes, highs, lows)
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return []

    results = []
    seen = set()

    for h0 in range(len(swing_highs)):
        for l0 in range(len(swing_lows)):
            h1i, h1v = swing_highs[h0]
            l1i, l1v = swing_lows[l0]

            # 第一对高低点不能太远
            if abs(h1i - l1i) > 10:
                continue

            # 找后续点
            hp = [(h1i, h1v)]
            lp = [(l1i, l1v)]
            for h in swing_highs[h0 + 1:]:
                if h[0] > lp[-1][0]:
                    hp.append(h)
                    break
            for l in swing_lows[l0 + 1:]:
                if l[0] > hp[-1][0]:
                    lp.append(l)
                    break

            if len(hp) < 2 or len(lp) < 2:
                continue

            hi = [p[0] for p in hp]
            hv = [p[1] for p in hp]
            li = [p[0] for p in lp]
            lv = [p[1] for p in lp]

            # 计算斜率
            h_slope = (hv[-1] - hv[0]) / max(hi[-1] - hi[0], 1)
            l_slope = (lv[-1] - lv[0]) / max(li[-1] - li[0], 1)

            # 高点必须下移，低点必须上移（收敛）
            if h_slope >= 0 or l_slope <= 0:
                continue

            tri_s = min(hi[0], li[0])
            tri_e = max(hi[-1], li[-1])
            dur = tri_e - tri_s

            # 三角必须在扫描范围内
            if tri_e > scan_end_idx:
                continue
            if dur < TRIANGLE_MIN_DAYS or dur > TRIANGLE_MAX_DAYS:
                continue

            # 高度检查
            hgt = hv[0] - lv[0]
            avg = sum(closes[tri_s:tri_e + 1]) / (tri_e - tri_s + 1)
            if hgt / avg < TRIANGLE_MIN_HEIGHT_PCT or hgt / avg > TRIANGLE_MAX_HEIGHT_PCT:
                continue

            key = (tri_s, tri_e)
            if key in seen:
                continue
            seen.add(key)

            # 找突破
            bk_i, bk_p = None, None
            for i in range(tri_e + 1, min(tri_e + BREAKOUT_LOOKAHEAD + 1, n)):
                # 突破上轨延长线
                upper_line = hv[0] + h_slope * (i - hi[0])
                if closes[i] > upper_line:
                    bk_i, bk_p = i, closes[i]
                    break

            # 如果没有明确突破，检查是否已靠近上轨（近似突破）
            if bk_i is None:
                li_end = n - 1
                upper_end = hv[0] + h_slope * (li_end - hi[0])
                if closes[li_end] > upper_end * 0.985:
                    bk_i, bk_p = li_end, closes[li_end]

            if bk_i is None:
                continue

            # 前期趋势（三角开始前）
            ps = max(0, tri_s - PRE_TREND_BARS)
            pre_closes = closes[ps:tri_s]
            if len(pre_closes) < 10:
                continue
            pre_trend = (pre_closes[-1] - pre_closes[0]) / pre_closes[0]
            if pre_trend < PRE_TREND_MIN:
                continue

            # 计算各项指标
            tgt = bk_p + hgt
            cp = closes[-1]
            up = (tgt - bk_p) / bk_p * 100
            ag = (cp - bk_p) / bk_p * 100

            # 突破后胜率
            post_closes = closes[bk_i:]
            if len(post_closes) > 1:
                post_ret = [(post_closes[j] - post_closes[j - 1]) / post_closes[j - 1]
                            for j in range(1, len(post_closes))]
                wr = sum(1 for r in post_ret if r > 0) / len(post_ret)
            else:
                wr = 0.5
            wr = min(max(wr, 0.3), 0.95)

            # 对称度
            sym = 1 - abs(abs(h_slope) - abs(l_slope)) / (abs(h_slope) + abs(l_slope) + 1e-10)

            # 距截止日天数
            dtr = (datetime.strptime(df[min(scan_end_idx, n-1)]['trade_date'], '%Y%m%d') -
                   datetime.strptime(df[tri_e]['trade_date'], '%Y%m%d')).days

            # 评分
            if dtr <= 3:
                time_score = 100
            elif dtr <= 7:
                time_score = 90
            elif dtr <= 14:
                time_score = 75
            elif dtr <= 21:
                time_score = 60
            elif dtr <= 30:
                time_score = 50
            else:
                time_score = max(0, 40 - (dtr - 30))

            win_score = wr * 100
            upside_score = min(100, up * 5)
            total = time_score * TIME_WEIGHT + win_score * WIN_WEIGHT + upside_score * UPSIDE_WEIGHT

            results.append(dict(
                hp=hp, lp=lp, h_slope=h_slope, l_slope=l_slope, hgt=hgt,
                bk_i=bk_i, bk_p=bk_p, tgt=tgt, cp=cp, up=up, ag=ag,
                wr=wr, sym=sym, pre_trend=pre_trend, dtr=dtr, dur=dur,
                tri_s=tri_s, tri_e=tri_e,
                ts_date=df[tri_s]['trade_date'],
                te_date=df[tri_e]['trade_date'],
                bk_date=df[bk_i]['trade_date'],
                time_score=time_score, win_score=win_score, upside_score=upside_score, total=total
            ))
    return results

# ============ 评分与过滤 ============

def score_and_filter(df, pattern):
    """后处理过滤和生成理由"""
    closes = [float(d['close']) for d in df]
    cp = closes[-1]
    up = pattern['up']

    # 预计目标涨幅 >= 8%
    if up < 8.0:
        return -1, []

    reasons = []
    dtr = pattern['dtr']
    if dtr <= 3:
        reasons.append(f"形态刚收敛完成（距截止日仅{dtr}天），突破信号最新鲜")
    elif dtr <= 7:
        reasons.append(f"形态于{dtr}天前完成收敛，突破时间窗口理想")
    elif dtr <= 14:
        reasons.append(f"形态于{dtr}天前收敛，突破信号有效")
    else:
        reasons.append(f"形态于{dtr}天前收敛")

    wr = pattern['wr'] * 100
    if wr > 70:
        reasons.append(f"突破后日线胜率{wr:.0f}%，表现优秀")
    elif wr > 55:
        reasons.append(f"突破后日线胜率{wr:.0f}%，表现较好")
    else:
        reasons.append(f"突破后日线胜率{wr:.0f}%")

    reasons.append(f"量度目标涨幅{up:.1f}%（目标¥{pattern['tgt']:.2f} / 突破¥{pattern['bk_p']:.2f}）")

    sym = pattern['sym']
    if sym > 0.8:
        reasons.append(f"三角收敛对称度{sym:.0%}，形态标准")
    elif sym > 0.5:
        reasons.append(f"三角收敛对称度{sym:.0%}，形态较好")

    pt = pattern['pre_trend']
    if pt > 0.1:
        reasons.append(f"收敛前强上涨趋势+{pt*100:.1f}%，典型上涨中继")
    elif pt > 0:
        reasons.append(f"收敛前上涨趋势+{pt*100:.1f}%，确认中继属性")

    reasons.append(f"三角持续{pattern['dur']}个交易日，整理充分")
    return int(pattern['total']), reasons

# ============ SVG 绘图 ============

def format_date(ds):
    return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"

def draw_svg_chart(df, pattern, score, reasons, stock_name, stock_code, save_path):
    W, H = 900, 700
    margin = {'top': 50, 'right': 60, 'bottom': 110, 'left': 70}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.60
    vol_h = chart_h * 0.22
    gap_h = chart_h * 0.08

    closes = [float(d['close']) for d in df]
    highs = [float(d['high']) for d in df]
    lows = [float(d['low']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    n = len(df)

    min_p = min(lows) * 0.97
    max_p = max(highs) * 1.03
    max_v = max(volumes) * 1.2 if volumes else 1

    def px(i):
        return margin['left'] + (i / (n - 1)) * chart_w if n > 1 else margin['left']

    def py(price):
        return margin['top'] + (1 - (price - min_p) / (max_p - min_p)) * price_h if max_p > min_p else margin['top']

    def vy(vol):
        return margin['top'] + price_h + gap_h + (1 - vol / max_v) * vol_h if max_v > 0 else margin['top'] + price_h + gap_h

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        f'<rect width="{W}" height="{H}" fill="#1a1a2e"/>',
        f'<text x="{W/2}" y="28" text-anchor="middle" font-size="16" fill="#e0e0e0" font-weight="bold">{stock_name} ({stock_code})  三角收敛上涨中继  评分:{score}/100</text>'
    ]

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W - margin["right"]}" y2="{yy}" stroke="#2a2a4a" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"] - 5}" y="{yy + 4}" text-anchor="end" font-size="10" fill="#888">{gp:.2f}</text>')

    # 日期
    for i in range(0, n, max(1, n // 8)):
        svg.append(f'<text x="{px(i)}" y="{margin["top"] + price_h + gap_h + vol_h + 15}" text-anchor="middle" font-size="9" fill="#888">{format_date(dates[i])}</text>')

    # 三角区域高亮
    tri_s, tri_e = pattern['tri_s'], pattern['tri_e']
    svg.append(f'<rect x="{px(tri_s)}" y="{margin["top"]}" width="{px(tri_e) - px(tri_s)}" height="{price_h + vol_h + gap_h}" fill="#FFD700" opacity="0.06"/>')

    # 成交量柱
    for i in range(n):
        bar_w = max(1, chart_w / n * 0.7)
        x = px(i) - bar_w / 2
        y = vy(volumes[i])
        bh = margin['top'] + price_h + gap_h + vol_h - y
        color = '#4CAF50' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#f44336'
        svg.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" opacity="0.5"/>')

    # 三角收敛区域填充
    tri_pts_upper = []
    tri_pts_lower = []
    for i in range(tri_s, tri_e + 1):
        if i < n:
            tri_pts_upper.append((px(i), py(closes[min(i, n-1)])))
    # 用趋势线画三角区域
    h_slope = pattern['h_slope']
    l_slope = pattern['l_slope']
    hi_base = pattern['hp'][0][0]
    hv_base = pattern['hp'][0][1]
    li_base = pattern['lp'][0][0]
    lv_base = pattern['lp'][0][1]

    # 阻力线 (上轨)
    ul_pts = []
    for i in range(tri_s, min(tri_e + int(BREAKOUT_LOOKAHEAD * 0.5), n)):
        up_y = py(hv_base + h_slope * (i - hi_base))
        ul_pts.append(f'{px(i)},{up_y}')
    svg.append(f'<polyline points="{" ".join(ul_pts)}" stroke="#f85149" stroke-width="2.5" fill="none"/>')

    # 支撑线 (下轨)
    ll_pts = []
    for i in range(tri_s, min(tri_e + int(BREAKOUT_LOOKAHEAD * 0.5), n)):
        lp_y = py(lv_base + l_slope * (i - li_base))
        ll_pts.append(f'{px(i)},{lp_y}')
    svg.append(f'<polyline points="{" ".join(ll_pts)}" stroke="#3fb950" stroke-width="2.5" fill="none"/>')

    # 三角区域填充
    fill_pts = []
    for i in range(tri_s, tri_e + 1):
        uy = py(hv_base + h_slope * (i - hi_base))
        fill_pts.append(f'{px(i)},{uy}')
    for i in range(tri_e, tri_s - 1, -1):
        ly = py(lv_base + l_slope * (i - li_base))
        fill_pts.append(f'{px(i)},{ly}')
    svg.append(f'<polygon points="{" ".join(fill_pts)}" fill="#FFD700" opacity="0.12"/>')

    # Swing点
    for idx, pv in pattern['hp']:
        if idx < n:
            svg.append(f'<polygon points="{px(idx)-6},{py(pv)-8} {px(idx)+6},{py(pv)-8} {px(idx)},{py(pv)+2}" fill="#f85149" stroke="#fff" stroke-width="1"/>')
    for idx, pv in pattern['lp']:
        if idx < n:
            svg.append(f'<polygon points="{px(idx)-6},{py(pv)+8} {px(idx)+6},{py(pv)+8} {px(idx)},{py(pv)-2}" fill="#3fb950" stroke="#fff" stroke-width="1"/>')

    # 突破点
    bk_i = pattern['bk_i']
    if bk_i < n:
        bk_y = py(closes[bk_i])
        svg.append(f'<circle cx="{px(bk_i)}" cy="{bk_y}" r="6" fill="#e53935" stroke="#fff" stroke-width="2"/>')
        svg.append(f'<text x="{px(bk_i)}" y="{bk_y - 12}" text-anchor="middle" font-size="10" fill="#e53935">突破</text>')

    # 价格线
    pts = ' '.join(f'{px(i)},{py(closes[i])}' for i in range(n))
    svg.append(f'<polyline points="{pts}" stroke="#2196F3" stroke-width="1.8" fill="none"/>')

    # 目标价 & 突破价线
    target = pattern['tgt']
    bk_p = pattern['bk_p']
    if target < max_p * 1.1:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W - margin["right"]}" y2="{ty}" stroke="#FFD700" stroke-width="1" stroke-dasharray="5,5"/>')
        svg.append(f'<text x="{W - margin["right"] + 5}" y="{ty + 4}" font-size="10" fill="#FFD700">目标 {target:.2f}</text>')

    bky = py(bk_p)
    svg.append(f'<line x1="{margin["left"]}" y1="{bky}" x2="{W - margin["right"]}" y2="{bky}" stroke="#3fb950" stroke-width="1" stroke-dasharray="2,2"/>')
    svg.append(f'<text x="{W - margin["right"] + 5}" y="{bky + 4}" font-size="10" fill="#3fb950">突破价 {bk_p:.2f}</text>')

    # 现价
    cp = closes[-1]
    cpy = py(cp)
    svg.append(f'<line x1="{px(n-1)}" y1="{cpy}" x2="{W - margin["right"]}" y2="{cpy}" stroke="#88ccff" stroke-width="1"/>')
    svg.append(f'<text x="{W - margin["right"] + 5}" y="{cpy + 4}" font-size="10" fill="#88ccff">现价 {cp:.2f}</text>')

    # 底部说明
    reasons_text = '\n'.join([f'{i+1}. {r}' for i, r in enumerate(reasons[:7])])
    base_y = H - margin['bottom'] + 15
    svg.append(f'<text x="{margin["left"]}" y="{base_y}" font-size="12" fill="#e0e0e0" font-weight="bold">上榜理由 (综合得分: {score}):</text>')
    for i, line in enumerate(reasons_text.split('\n')):
        svg.append(f'<text x="{margin["left"]}" y="{base_y + 18 + i * 18}" font-size="11" fill="#aaa">{line}</text>')

    svg.append('</svg>')
    with open(save_path, 'w') as f:
        f.write('\n'.join(svg))

# ============ 主程序 ============

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, f'{END_DATE}_data')
    os.makedirs(output_dir, exist_ok=True)

    # 计算最早允许的突破日期 (END_DATE - SCAN_WINDOW_MONTHS×30天)
    from datetime import timedelta
    end_dt = datetime.strptime(END_DATE, '%Y%m%d')
    earliest_dt = end_dt - timedelta(days=SCAN_WINDOW_MONTHS * 30)
    earliest_date = earliest_dt.strftime('%Y%m%d')

    print("=" * 60)
    print("  三角收敛上涨中继形态扫描器")
    print(f"  筛选截止: {END_DATE}  图表截止: {PLOT_END_DATE}")
    print("=" * 60)

    print("\n[1/4] 获取股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}

    hs300 = get_hs300_components()
    zz500 = get_zz500_components()
    all_codes = set((hs300 or []) + zz500)
    scan_codes = [c for c in all_codes if c in stock_map]
    print(f"  扫描沪深300+中证500共 {len(scan_codes)} 只股票")

    print(f"\n[2/4] 扫描三角收敛形态...")
    all_patterns = []

    for idx, code in enumerate(scan_codes):
        if idx % 30 == 0 and idx > 0:
            print(f"  进度: {idx}/{len(scan_codes)}")

        try:
            plot_df = get_daily_data(code)  # 拉到当前日期，用于画图
            if not plot_df or len(plot_df) < 60:
                continue

            # 截取到END_DATE用于形态检测
            scan_df = [d for d in plot_df if d['trade_date'] <= END_DATE]
            if len(scan_df) < 60:
                continue

            scan_end_idx = len(scan_df) - 1
            triangles = detect_triangle(scan_df, scan_end_idx)
            name = stock_map.get(code, code)

            for t in triangles:
                score, reasons = score_and_filter(scan_df, t)
                if score >= 0:
                    if t['bk_date'] < earliest_date:
                        continue
                    all_patterns.append({
                        'code': code, 'name': name, 'plot_df': plot_df, 'scan_df': scan_df,
                        'pattern': t, 'score': score, 'reasons': reasons
                    })
            time.sleep(0.12)
        except Exception:
            continue

    if not all_patterns:
        print("  未发现符合条件的三角收敛形态")
        return

    # 按股票去重：每只股票只保留得分最高的形态
    stock_best = {}
    for item in all_patterns:
        code = item['code']
        if code not in stock_best or item['score'] > stock_best[code]['score']:
            stock_best[code] = item
    all_patterns = list(stock_best.values())

    # 按胜率排序（与原版scan_v3一致）
    all_patterns.sort(key=lambda x: x['pattern']['wr'], reverse=True)
    top5 = all_patterns[:5]

    print(f"\n[3/4] 前5名:")
    for i, item in enumerate(top5):
        p = item['pattern']
        print(f"  {i+1}. {item['name']} ({item['code']}) 评分:{item['score']} "
              f"三角结束于{p['te_date']} 突破于{p['bk_date']}")

    print(f"\n[4/4] 生成图表...")
    for i, item in enumerate(top5):
        svg_path = os.path.join(output_dir, f'top{i+1}_{item["code"].split(".")[0]}_{item["name"]}.svg')
        draw_svg_chart(item['plot_df'], item['pattern'], item['score'], item['reasons'],
                       item['name'], item['code'], svg_path)
        print(f"  SVG: {os.path.basename(svg_path)}")

    # 导出CSV (全部符合条件的结果)
    csv_path = os.path.join(output_dir, f'top30_三角收敛上涨中继.csv')
    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write('排名,代码,名称,综合得分,三角开始日期,三角结束日期,三角持续天数,'
                '突破日期,突破价格,当前价格,当前已涨跌幅_pct,三角前涨幅_pct,'
                '预计目标涨幅_pct,量度目标价,胜率_pct,对称度_pct\n')
        top30 = all_patterns[:30]
        for i, item in enumerate(top30):
            p = item['pattern']
            cp = float(item['plot_df'][-1]['close'])
            f.write(f'{i+1},{item["code"]},{item["name"]},{p["total"]:.1f},'
                    f'{p["ts_date"]},{p["te_date"]},{p["dur"]},'
                    f'{p["bk_date"]},{p["bk_p"]:.2f},{cp:.2f},{p["ag"]:.1f},'
                    f'{p["pre_trend"]*100:.1f},{p["up"]:.1f},{p["tgt"]:.2f},'
                    f'{p["wr"]*100:.0f},{p["sym"]*100:.0f}\n')
    print(f"  CSV: {os.path.basename(csv_path)}")

    print(f"\n完成! 图表保存在: {output_dir}")
    print("=" * 60)

    # 详细输出
    for i, item in enumerate(top5):
        p = item['pattern']
        cp = float(item['plot_df'][-1]['close'])
        print(f"\n{'='*45}")
        print(f"第{i+1}名: {item['name']} ({item['code']})")
        print(f"  综合得分: {p['total']:.1f} | 时间:{p['time_score']:.0f} 胜率:{p['win_score']:.0f} 空间:{p['upside_score']:.0f}")
        print(f"  三角区间: {format_date(p['ts_date'])} ~ {format_date(p['te_date'])} ({p['dur']}天)")
        print(f"  突破日期: {format_date(p['bk_date'])} @ ¥{p['bk_p']:.2f}")
        print(f"  量度目标: ¥{p['tgt']:.2f} (空间 {p['up']:.1f}%)")
        print(f"  当前价格: ¥{cp:.2f} (已涨 {p['ag']:+.1f}%)")
        print(f"  上榜理由:")
        for r in item['reasons']:
            print(f"    + {r}")

if __name__ == '__main__':
    main()
