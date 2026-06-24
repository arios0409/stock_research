"""
三角收敛上涨中继形态扫描器 - 增强版 v2
新增: 断点续扫 — 每500只自动保存进度，崩溃/终止后可从断点恢复
股票池: 全A股 (沪市主板+深市主板+创业板+科创板, 排除ST/退市)
输出: CSV(top20) + SVG图表(top5) -> output/YYYYMMDD/
"""
# ═══════════════════════════════════════════════════════════════
# v2 与 v1 的区别:
#   1. 每500只保存 checkpoint.json (当前索引 + 已累积的 all_patterns)
#   2. 启动时检测 checkpoint.json，存在则从断点恢复
#   3. 扫描完成后自动删除 checkpoint.json
#   4. 原 v1 脚本原封不动保留
# ═══════════════════════════════════════════════════════════════

import urllib.request
import json
import os
import sys
import time
import math
from datetime import datetime, timedelta

# 双输出：同时写stdout和日志文件
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', f'{datetime.now().strftime("%Y%m%d")}', 'scan.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
LOG_FP = open(LOG_PATH, 'a' if os.path.exists(LOG_PATH) else 'w', buffering=1)  # v2: 追加模式，支持断点续写

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
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
TODAY = datetime.now().strftime('%Y%m%d')
END_DATE = TODAY
START_DATE = '20241001'
PLOT_START = '20240501'   # 画图用2年数据
PLOT_END_DATE = TODAY

# 三角参数
TRIANGLE_MIN_DAYS = 15
TRIANGLE_MAX_DAYS = 100
TRIANGLE_MIN_HEIGHT_PCT = 0.03
TRIANGLE_MAX_HEIGHT_PCT = 0.35
SWING_ORDER = 3
BREAKOUT_LOOKAHEAD = 15
PRE_TREND_BARS = 25
PRE_TREND_MIN = -0.03

# 评分权重
TIME_WEIGHT = 0.35
WIN_WEIGHT = 0.30
UPSIDE_WEIGHT = 0.35

# 输出
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_BASE = os.path.join(SCRIPT_DIR, 'output')
OUTPUT_DIR = os.path.join(OUTPUT_BASE, TODAY)
os.makedirs(OUTPUT_DIR, exist_ok=True)

TOP_N_CSV = 20
TOP_N_CHART = 5

# v2: checkpoint 文件
CHECKPOINT_PATH = os.path.join(OUTPUT_DIR, 'checkpoint_triangle.json')


# ============ Checkpoint 断点续扫 ============

def save_checkpoint(idx, all_patterns):
    """保存断点：当前扫描到的索引 + 已累积的所有形态（不含plot_df，只存元数据）"""
    # 不存 plot_df — 每只股票500+根日线，存进去会让checkpoint膨胀到GB级
    light = []
    for item in all_patterns:
        light.append({
            'code': item['code'],
            'name': item['name'],
            'industry': item.get('industry', ''),
            'pattern': item['pattern'],
            'score': item['score'],
            'reasons': item['reasons'],
        })
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
    """加载断点，返回 (start_idx, all_patterns, total_stocks_saved) 或 (0, [], 0)"""
    if not os.path.exists(CHECKPOINT_PATH):
        return 0, [], 0
    try:
        with open(CHECKPOINT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        last_idx = data.get('last_idx', 0)
        all_patterns = data.get('all_patterns', [])
        total_saved = data.get('total_stocks', 0)
        print(f"  [断点恢复] 上次扫描到第 {last_idx+1} 只，已命中 {len(all_patterns)} 个形态")
        return last_idx + 1, all_patterns, total_saved  # +1 表示从下一只开始
    except Exception as e:
        print(f"  [警告] checkpoint 损坏: {e}，从头扫描")
        return 0, [], 0


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
    return [dict(zip(fields, item)) for item in result['items']
            if dict(zip(fields, item)).get('list_status') == 'L']

def get_index_components(index_code):
    """获取指数成分股"""
    result = api_call('index_weight', index_code=index_code, fields='con_code')
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

def detect_triangle(df):
    """在全量数据中检测三角收敛形态"""
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

            if abs(h1i - l1i) > 10:
                continue

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

            h_slope = (hv[-1] - hv[0]) / max(hi[-1] - hi[0], 1)
            l_slope = (lv[-1] - lv[0]) / max(li[-1] - li[0], 1)

            # 高点下移，低点上移 = 收敛
            if h_slope >= 0 or l_slope <= 0:
                continue

            tri_s = min(hi[0], li[0])
            tri_e = max(hi[-1], li[-1])
            dur = tri_e - tri_s

            if dur < TRIANGLE_MIN_DAYS or dur > TRIANGLE_MAX_DAYS:
                continue

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
                upper_line = hv[0] + h_slope * (i - hi[0])
                if closes[i] > upper_line:
                    bk_i, bk_p = i, closes[i]
                    break

            if bk_i is None:
                li_end = n - 1
                upper_end = hv[0] + h_slope * (li_end - hi[0])
                if closes[li_end] > upper_end * 0.985:
                    bk_i, bk_p = li_end, closes[li_end]

            if bk_i is None:
                continue

            # 前期趋势
            ps = max(0, tri_s - PRE_TREND_BARS)
            pre_closes = closes[ps:tri_s]
            if len(pre_closes) < 10:
                continue
            pre_trend = (pre_closes[-1] - pre_closes[0]) / pre_closes[0]
            if pre_trend < PRE_TREND_MIN:
                continue

            # 计算指标
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

            # 距当前天数
            dtr = (datetime.strptime(df[-1]['trade_date'], '%Y%m%d') -
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

# ============ 评分过滤 ============

def score_and_filter(df, pattern):
    closes = [float(d['close']) for d in df]
    cp = closes[-1]
    up = pattern['up']

    if up < 8.0:
        return -1, []

    reasons = []
    dtr = pattern['dtr']
    if dtr <= 3:
        reasons.append(f"形态刚收敛完成（距今仅{dtr}天），突破信号最新鲜")
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
    W, H = 1000, 720
    margin = {'top': 55, 'right': 85, 'bottom': 115, 'left': 80}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = chart_h * 0.58
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
        f'<rect width="{W}" height="{H}" fill="#0d1117"/>',
        f'<text x="{W/2}" y="24" text-anchor="middle" font-size="17" fill="#58a6ff" font-weight="bold">'
        f'{stock_name} ({stock_code})  三角收敛上涨中继  评分:{score}/100</text>'
    ]

    # 网格
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W - margin["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"] - 8}" y="{yy + 4}" text-anchor="end" font-size="10" fill="#8b949e">{gp:.2f}</text>')

    # 日期
    for i in range(0, n, max(1, n // 8)):
        svg.append(f'<text x="{px(i)}" y="{margin["top"] + price_h + gap_h + vol_h + 15}" text-anchor="middle" font-size="9" fill="#8b949e">{format_date(dates[i])}</text>')

    # 三角区域高亮
    tri_s, tri_e = pattern['tri_s'], pattern['tri_e']
    svg.append(f'<rect x="{px(tri_s)}" y="{margin["top"]}" width="{px(tri_e) - px(tri_s)}" height="{price_h + vol_h + gap_h}" fill="#FFD700" opacity="0.06" rx="2"/>')

    # 成交量柱
    for i in range(n):
        bar_w = max(1, chart_w / n * 0.7)
        x = px(i) - bar_w / 2
        y = vy(volumes[i])
        bh = margin['top'] + price_h + gap_h + vol_h - y
        color = '#3fb950' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#f85149'
        svg.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bh}" fill="{color}" opacity="0.5"/>')

    # 上轨（阻力线）延长
    h_slope = pattern['h_slope']
    l_slope = pattern['l_slope']
    hi_base = pattern['hp'][0][0]
    hv_base = pattern['hp'][0][1]
    li_base = pattern['lp'][0][0]
    lv_base = pattern['lp'][0][1]

    # 阻力线
    ul_pts = []
    for i in range(tri_s, min(tri_e + int(BREAKOUT_LOOKAHEAD * 0.5), n)):
        up_y = py(hv_base + h_slope * (i - hi_base))
        ul_pts.append(f'{px(i)},{up_y}')
    svg.append(f'<polyline points="{" ".join(ul_pts)}" stroke="#f85149" stroke-width="2.8" fill="none"/>')

    # 支撑线
    ll_pts = []
    for i in range(tri_s, min(tri_e + int(BREAKOUT_LOOKAHEAD * 0.5), n)):
        lp_y = py(lv_base + l_slope * (i - li_base))
        ll_pts.append(f'{px(i)},{lp_y}')
    svg.append(f'<polyline points="{" ".join(ll_pts)}" stroke="#3fb950" stroke-width="2.8" fill="none"/>')

    # 三角区域填充
    fill_pts = []
    for i in range(tri_s, tri_e + 1):
        uy = py(hv_base + h_slope * (i - hi_base))
        fill_pts.append(f'{px(i)},{uy}')
    for i in range(tri_e, tri_s - 1, -1):
        ly = py(lv_base + l_slope * (i - li_base))
        fill_pts.append(f'{px(i)},{ly}')
    svg.append(f'<polygon points="{" ".join(fill_pts)}" fill="#FFD700" opacity="0.10"/>')

    # Swing点标注
    for idx, pv in pattern['hp']:
        if idx < n:
            svg.append(f'<polygon points="{px(idx)-7},{py(pv)-9} {px(idx)+7},{py(pv)-9} {px(idx)},{py(pv)+1}" fill="#f85149" stroke="#fff" stroke-width="1.5"/>')
            svg.append(f'<text x="{px(idx)}" y="{py(pv)-13}" text-anchor="middle" font-size="9" fill="#f85149">¥{pv:.2f}</text>')
    for idx, pv in pattern['lp']:
        if idx < n:
            svg.append(f'<polygon points="{px(idx)-7},{py(pv)+9} {px(idx)+7},{py(pv)+9} {px(idx)},{py(pv)-1}" fill="#3fb950" stroke="#fff" stroke-width="1.5"/>')
            svg.append(f'<text x="{px(idx)}" y="{py(pv)+18}" text-anchor="middle" font-size="9" fill="#3fb950">¥{pv:.2f}</text>')

    # 突破点
    bk_i = pattern['bk_i']
    if bk_i < n:
        bk_y = py(closes[bk_i])
        svg.append(f'<circle cx="{px(bk_i)}" cy="{bk_y}" r="8" fill="#f0883e" stroke="#fff" stroke-width="2.5"/>')
        svg.append(f'<text x="{px(bk_i)}" y="{bk_y - 14}" text-anchor="middle" font-size="11" fill="#f0883e" font-weight="bold">★ 突破 ¥{closes[bk_i]:.2f}</text>')

    # K线（收盘价线）
    pts = ' '.join(f'{px(i)},{py(closes[i])}' for i in range(n))
    svg.append(f'<polyline points="{pts}" stroke="#58a6ff" stroke-width="1.8" fill="none"/>')

    # 目标价线
    target = pattern['tgt']
    if target < max_p * 1.1:
        ty = py(target)
        svg.append(f'<line x1="{margin["left"]}" y1="{ty}" x2="{W - margin["right"]}" y2="{ty}" stroke="#FFD700" stroke-width="1.5" stroke-dasharray="6,4"/>')
        svg.append(f'<text x="{W - margin["right"] + 5}" y="{ty + 5}" font-size="11" fill="#FFD700" font-weight="bold">▼ 目标 {target:.2f}</text>')

    # 突破价线
    bky = py(pattern['bk_p'])
    svg.append(f'<line x1="{margin["left"]}" y1="{bky}" x2="{W - margin["right"]}" y2="{bky}" stroke="#3fb950" stroke-width="1" stroke-dasharray="3,3"/>')
    svg.append(f'<text x="{W - margin["right"] + 5}" y="{bky + 5}" font-size="11" fill="#3fb950">突破价 {pattern["bk_p"]:.2f}</text>')

    # 现价
    cp = closes[-1]
    cpy = py(cp)
    svg.append(f'<line x1="{px(n-1)}" y1="{cpy}" x2="{W - margin["right"]}" y2="{cpy}" stroke="#88ccff" stroke-width="1.5"/>')
    svg.append(f'<text x="{W - margin["right"] + 5}" y="{cpy + 5}" font-size="11" fill="#88ccff" font-weight="bold">● 现价 {cp:.2f}</text>')

    # 底部说明
    base_y = H - margin['bottom'] + 18
    svg.append(f'<text x="{margin["left"]}" y="{base_y}" font-size="13" fill="#58a6ff" font-weight="bold">上榜理由 (综合得分: {score}):</text>')
    for i, line in enumerate(reasons[:7]):
        svg.append(f'<text x="{margin["left"] + 10}" y="{base_y + 18 + i * 16}" font-size="11" fill="#c9d1d9">{i+1}. {line}</text>')

    svg.append('</svg>')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(svg))


# ============ 主程序 ============

def write_incremental_csv(all_patterns, csv_path, label=""):
    """增量写入top20 CSV（去重+排序）"""
    if not all_patterns:
        return 0
    # 每只股票只保留得分最高
    stock_best = {}
    for item in all_patterns:
        code = item['code']
        if code not in stock_best or item['score'] > stock_best[code]['score']:
            stock_best[code] = item
    deduped = list(stock_best.values())
    deduped.sort(key=lambda x: x['score'], reverse=True)
    top20 = deduped[:TOP_N_CSV]

    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write('排名,代码,名称,行业,综合得分,三角开始日期,三角结束日期,三角持续天数,'
                '突破日期,突破价格,当前价格,当前已涨跌幅_pct,三角前涨幅_pct,'
                '预计目标涨幅_pct,量度目标价,胜率_pct,对称度_pct\n')
        for i, item in enumerate(top20):
            p = item['pattern']
            # 用pattern里存好的cp，不再依赖plot_df
            cp = p['cp']
            f.write(f'{i+1},{item["code"]},{item["name"]},{item.get("industry","")},{p["total"]:.1f},'
                    f'{p["ts_date"]},{p["te_date"]},{p["dur"]},'
                    f'{p["bk_date"]},{p["bk_p"]:.2f},{cp:.2f},{p["ag"]:.1f},'
                    f'{p["pre_trend"]*100:.1f},{p["up"]:.1f},{p["tgt"]:.2f},'
                    f'{p["wr"]*100:.0f},{p["sym"]*100:.0f}\n')
    if label:
        print(f"  [增量CSV] {label}: {len(deduped)}只股票入池, top{TOP_N_CSV}已写入")
    return len(deduped)


def main():
    print("=" * 65)
    print("  三角收敛上涨中继形态扫描器 - 增强版 v2 (断点续扫)")
    print(f"  扫描日期: {TODAY}")
    print(f"  股票池: 全A股 (沪市主板+深市主板+创业板+科创板, 排除ST/退市)")
    print(f"  输出: top20 CSV + top5 SVG → {OUTPUT_DIR}")
    print(f"  断点: {CHECKPOINT_PATH}")
    print("=" * 65)

    # 1. 获取全A股列表
    print("\n[1/5] 获取全A股股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks if 'ST' not in s.get('name', '') and '退' not in s.get('name', '')}
    industry_map = {s['ts_code']: s.get('industry', '') for s in stocks}

    scan_codes = list(stock_map.keys())

    # 统计板块分布
    sh = sum(1 for c in scan_codes if c.endswith('.SH') and not c.startswith('688'))
    sz_main = sum(1 for c in scan_codes if c.endswith('.SZ') and not c.startswith('300'))
    cyb = sum(1 for c in scan_codes if c.startswith('300'))
    kcb = sum(1 for c in scan_codes if c.startswith('688'))
    print(f"  沪市主板:{sh}  深市主板:{sz_main}  创业板:{cyb}  科创板:{kcb}")
    print(f"  总计: {len(scan_codes)} 只")

    # 2. v2: 加载断点
    print(f"\n[1.5/5] 检查断点...")
    start_idx, all_patterns, _ = load_checkpoint()
    if start_idx > 0:
        print(f"  从第 {start_idx+1} 只开始继续扫描（共 {len(scan_codes)} 只）")
        # 恢复时立即写一次 CSV，保证 checkpoint 里的数据反映到文件
        csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_N_CSV}_三角收敛上涨中继_{TODAY}.csv')
        write_incremental_csv(all_patterns, csv_path, f"恢复 @ {start_idx}/{len(scan_codes)}")
    else:
        print(f"  无断点，从头开始扫描 {len(scan_codes)} 只")

    # 3. 扫描三角收敛
    print(f"\n[2/5] 扫描三角收敛形态...")
    csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_N_CSV}_三角收敛上涨中继_{TODAY}.csv')
    start_time = time.time()

    for idx in range(start_idx, len(scan_codes)):
        code = scan_codes[idx]

        if idx % 50 == 0 and idx > start_idx:
            elapsed = time.time() - start_time
            scanned = idx - start_idx
            remaining = len(scan_codes) - idx
            if scanned > 0:
                eta = (elapsed / scanned) * remaining
                print(f"  进度: {idx}/{len(scan_codes)} | 命中: {len(all_patterns)} | ETA: {eta/60:.0f}分钟")

        try:
            plot_df = get_daily_data(code, start_date=PLOT_START)
            if not plot_df or len(plot_df) < 60:
                continue

            triangles = detect_triangle(plot_df)
            name = stock_map.get(code, code)
            industry = industry_map.get(code, '')

            for t in triangles:
                score, reasons = score_and_filter(plot_df, t)
                if score >= 0:
                    all_patterns.append({
                        'code': code, 'name': name, 'industry': industry, 'plot_df': plot_df,
                        'pattern': t, 'score': score, 'reasons': reasons
                    })
            time.sleep(0.12)

            # v2: 每500只保存断点 + 增量CSV
            if (idx + 1) % 500 == 0:
                save_checkpoint(idx, all_patterns)
                write_incremental_csv(all_patterns, csv_path, f"{idx+1}/{len(scan_codes)}")
        except Exception:
            continue

    elapsed = time.time() - start_time
    print(f"  扫描完成: {len(scan_codes)}只, 命中{len(all_patterns)}个形态, 耗时{elapsed/60:.1f}分钟")

    if not all_patterns:
        print("\n  未发现符合条件的三角收敛形态，退出。")
        clear_checkpoint()
        return

    # 每只股票只保留得分最高
    stock_best = {}
    for item in all_patterns:
        code = item['code']
        if code not in stock_best or item['score'] > stock_best[code]['score']:
            stock_best[code] = item
    all_patterns = list(stock_best.values())
    print(f"  去重后: {len(all_patterns)}只股票")

    # 按综合得分降序
    all_patterns.sort(key=lambda x: x['score'], reverse=True)
    top5_chart = all_patterns[:TOP_N_CHART]
    top20_csv = all_patterns[:TOP_N_CSV]

    # 3. 输出CSV
    print(f"\n[3/5] 生成top20 CSV...")
    csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_N_CSV}_三角收敛上涨中继_{TODAY}.csv')
    with open(csv_path, 'w', encoding='utf-8-sig') as f:
        f.write('排名,代码,名称,行业,综合得分,三角开始日期,三角结束日期,三角持续天数,'
                '突破日期,突破价格,当前价格,当前已涨跌幅_pct,三角前涨幅_pct,'
                '预计目标涨幅_pct,量度目标价,胜率_pct,对称度_pct\n')
        for i, item in enumerate(top20_csv):
            p = item['pattern']
            # 用pattern里存好的cp，不再依赖plot_df
            cp = p['cp']
            f.write(f'{i+1},{item["code"]},{item["name"]},{item.get("industry","")},{p["total"]:.1f},'
                    f'{p["ts_date"]},{p["te_date"]},{p["dur"]},'
                    f'{p["bk_date"]},{p["bk_p"]:.2f},{cp:.2f},{p["ag"]:.1f},'
                    f'{p["pre_trend"]*100:.1f},{p["up"]:.1f},{p["tgt"]:.2f},'
                    f'{p["wr"]*100:.0f},{p["sym"]*100:.0f}\n')
    print(f"  CSV: {csv_path}")

    # 4. 生成top5图表 — 只为top5单独拉日线，不再依赖checkpoint里的plot_df
    print(f"\n[4/5] 为top5拉取日线并生成K线图(SVG)...")
    for i, item in enumerate(top5_chart):
        code = item['code']
        print(f"  [{i+1}] 拉取 {code} {item['name']} 日线...")
        plot_df = get_daily_data(code, start_date=PLOT_START)
        if not plot_df or len(plot_df) < 60:
            print(f"      数据不足，跳过")
            continue
        # 用最新日线刷新cp（扫描时存的cp可能过时）
        fresh_cp = float(plot_df[-1]['close'])
        p = item['pattern']
        p['cp'] = fresh_cp
        p['ag'] = (fresh_cp - p['bk_p']) / p['bk_p'] * 100
        svg_path = os.path.join(OUTPUT_DIR,
            f'top{i+1}_{item["code"].split(".")[0]}_{item["name"]}_三角收敛.svg')
        draw_svg_chart(plot_df, item['pattern'], item['score'],
                       item['reasons'], item['name'], item['code'], svg_path)
        print(f"      图表: {os.path.basename(svg_path)}")
        time.sleep(0.12)

    # 5. 输出摘要
    print(f"\n[5/5] 结果摘要")
    print("=" * 65)
    print(f"  {'排名':<5} {'代码':<12} {'名称':<8} {'得分':<6} {'目标涨幅':<8} {'突破日':<12} {'现价':<8}")
    print("  " + "-" * 60)
    for i, item in enumerate(top20_csv):
        p = item['pattern']
        cp = p['cp']
        print(f"  {i+1:<5} {item['code'].split('.')[0]:<12} {item['name']:<8} {p['total']:<6.0f} "
              f"{p['up']:<8.1f}% {format_date(p['bk_date']):<12} ¥{cp:<7.2f}")

    print(f"\n  输出目录: {OUTPUT_DIR}")
    print(f"  CSV: {os.path.basename(csv_path)} ({len(top20_csv)}条)")
    print(f"  SVG: {TOP_N_CHART}张图表")
    print("=" * 65)

    # v2: 扫描完成，清除断点
    clear_checkpoint()


if __name__ == '__main__':
    main()
