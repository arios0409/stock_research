"""
双底形态扫描器 - 近期突破版 (无第三方依赖)
条件:
- 双底形态形成于 2025年12月 ~ 2026年5月20日
- 首次突破颈线距离 2026-05-20 越近越好
- 拉升可能性高
- 距目标位剩余空间 >= 8%
"""

import urllib.request
import json
import os
import time
import math
import statistics

from wecom_notify import send_markdown, send_text, send_image_file, send_file, upload_file

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
END_DATE = '20260521'
START_DATE = '20241001'  # 往前多取一些数据用于计算指标
DOUBLE_BOTTOM_START = '20240601'  # 双底形态开始时间(回溯扫描需提前)
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

def calc_ma(data, period):
    """计算简单移动平均"""
    n = len(data)
    result = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(data[i - period + 1: i + 1]) / period
    return result

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

def detect_double_bottom(df, window_bottom=22, window_breakout=8):
    n = len(df)
    if n < window_bottom * 2 + 1: return []
    
    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    vol_ma20 = calc_ma(volumes, 20)
    
    # 找局部低点（大窗口，只抓主底）
    lows = []
    for i in range(window_bottom, n - window_bottom):
        price = closes[i]
        if all(closes[j] > price for j in range(max(0, i-window_bottom), min(n, i+window_bottom+1)) if j != i):
            lows.append((i, price, volumes[i]))
    
    # 找局部高点（小窗口，保持突破附近敏感度）
    highs = []
    for i in range(window_breakout, n - window_breakout):
        price = closes[i]
        if all(closes[j] < price for j in range(max(0, i-window_breakout), min(n, i+window_breakout+1)) if j != i):
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
        
        # 颈线高度必须 > 10%
        neck_height_pct = (n_price - min(l1_price, l2_price)) / min(l1_price, l2_price)
        if neck_height_pct < 0.10: continue
        
        # 颈线必须在左底之前被价格触及过（形成W底的左侧下降段）
        # 检查左底前100天内是否有High >= 颈线*0.95
        pre_left_high = max(closes[max(0, l1_idx-100):l1_idx]) if l1_idx > 0 else 0
        if pre_left_high < n_price * 0.95:
            continue  # 颈线太高，左底前价格根本没到过这里，不是真正的W底
        
# 双底必须在指定时间范围内开始形成
        if dates[l1_idx] < DOUBLE_BOTTOM_START: continue
        
        # 检查突破颈线的时间
        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:  # 突破1%算有效突破
                # 放量确认：突破日成交量 > 20日均量 × 1.5
                if vol_ma20[j] is None or volumes[j] < vol_ma20[j] * 1.5:
                    continue
                # 突破后3天内不回踩颈线×0.98以下
                fake_break = False
                for k in range(j + 1, min(j + 4, n)):
                    if closes[k] < n_price * 0.98:
                        fake_break = True
                        break
                if fake_break:
                    continue
                break_idx = j
                break
        
        if break_idx is None: continue  # 未突破或突破无效
        
        results.append({
            'left_idx': l1_idx, 'left_price': l1_price, 'left_date': dates[l1_idx], 'left_vol': l1_vol,
            'right_idx': l2_idx, 'right_price': l2_price, 'right_date': dates[l2_idx], 'right_vol': l2_vol,
            'neck_idx': n_idx, 'neck_price': n_price, 'neck_date': dates[n_idx],
            'break_idx': break_idx, 'break_date': dates[break_idx],
            'gap': gap,
            'price_diff_pct': abs(l1_price - l2_price) / min(l1_price, l2_price),
            'height_pct': neck_height_pct,
            'left_macd': macd[l1_idx], 'right_macd': macd[l2_idx],
            'left_rsi': rsi[l1_idx], 'right_rsi': rsi[l2_idx],
            'closes': closes, 'volumes': volumes, 'dates': dates,
            'break_vol_ratio': volumes[break_idx] / vol_ma20[break_idx] if vol_ma20[break_idx] and vol_ma20[break_idx] > 0 else 1.0,
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
    
    # 新增：检查突破后的走势，已经走完的形态大幅降低得分
    break_idx = pattern['break_idx']
    post_break_high = max(float(df[i]['high']) for i in range(break_idx, n))
    post_break_max_close = max(float(df[i]['close']) for i in range(break_idx, n))
    
    # 如果突破后最高价已经 >= 目标位，说明行情已经走完，降权
    if post_break_high >= target:
        score -= 30; reasons.append(f'已触及目标(最高{post_break_high:.2f})')
    elif post_break_high >= target * 0.8:
        score -= 10; reasons.append(f'已接近目标(最高{post_break_high:.2f}/{target:.2f})')
    
    # 如果现价从突破后高点回撤 > 15%，说明已经跌下来了，降权
    drawdown = (post_break_high - current_price) / post_break_high
    if drawdown > 0.15:
        score -= 25; reasons.append(f'突破后回撤{drawdown:.0%}(已走弱)')
    elif drawdown > 0.08:
        score -= 10; reasons.append(f'突破后回撤{drawdown:.0%}')
    
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
           '<defs><style>text { font-family: "Droid Sans Fallback", "Noto Sans SC", "WenQuanYi Micro Hei", "Microsoft YaHei", sans-serif; }</style></defs>',
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


def draw_png_chart(df, pattern, score, reasons, stock_name, stock_code, save_path):
    """用 Pillow 直接渲染 PNG 图表，中文字体可靠。"""
    from PIL import Image, ImageDraw, ImageFont
    import os as _os

    W, H = 900, 650
    margin = {'top': 50, 'right': 60, 'bottom': 100, 'left': 70}
    chart_w = W - margin['left'] - margin['right']
    chart_h = H - margin['top'] - margin['bottom']
    price_h = int(chart_h * 0.65); vol_h = int(chart_h * 0.25); gap_h = int(chart_h * 0.1)

    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    n = len(df)

    min_p = min(closes) * 0.97; max_p = max(closes) * 1.02
    max_v = max(volumes) * 1.2

    def px(i): return margin['left'] + int((i / max(1, n - 1)) * chart_w)
    def py(price): return margin['top'] + int((1 - (price - min_p) / (max_p - min_p)) * price_h)
    def vy(vol): return margin['top'] + price_h + gap_h + int((1 - vol / max_v) * vol_h)

    # 双字体: DejaVu Sans 处理 Latin/ASCII, Droid Sans Fallback 处理 CJK
    font_latin_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font_cjk_path = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'
    if not _os.path.exists(font_cjk_path):
        font_cjk_path = _os.path.expanduser('~/.local/share/fonts/NotoSansSC.ttf')

    def _make_fonts(size):
        return (
            ImageFont.truetype(font_latin_path, size),
            ImageFont.truetype(font_cjk_path, size),
        )

    f_title_l, f_title_c = _make_fonts(16)
    f_norm_l, f_norm_c = _make_fonts(10)
    f_small_l, f_small_c = _make_fonts(9)
    f_label_l, f_label_c = _make_fonts(12)
    f_reason_l, f_reason_c = _make_fonts(11)

    def _is_cjk(ch):
        cp = ord(ch)
        return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
                0x20000 <= cp <= 0x2A6DF or 0xF900 <= cp <= 0xFAFF or
                0x2F800 <= cp <= 0x2FA1F)

    def _draw_text(draw, xy, text, fill, font_latin: ImageFont.FreeTypeFont,
                   font_cjk: ImageFont.FreeTypeFont, anchor=None):
        """逐字符混合字体绘制，保证中西文都正确渲染。"""
        x, y = xy
        i = 0
        while i < len(text):
            ch = text[i]
            font = font_cjk if _is_cjk(ch) else font_latin
            bbox = font.getbbox(ch)
            ch_w = bbox[2] - bbox[0]
            draw.text((x, y), ch, fill=fill, font=font, anchor=anchor)
            x += ch_w
            i += 1

    img = Image.new('RGBA', (W, H), (26, 26, 46, 255))
    draw = ImageDraw.Draw(img)

    # 标题 (居中)
    title = f"{stock_name} ({stock_code})  双底突破  评分:{score}/100"
    _draw_text(draw, (W//2, 8), title, (224, 224, 224, 255), f_title_l, f_title_c, anchor='mt')

    # 网格 + 价格标签
    for i in range(6):
        gp = min_p + (max_p - min_p) / 5 * i
        yy = py(gp)
        draw.line([(margin['left'], yy), (W - margin['right'], yy)], fill=(42, 42, 74), width=1)
        _draw_text(draw, (margin['left'] - 5, yy), f"{gp:.2f}", (136, 136, 136, 255), f_small_l, f_small_c, anchor='rm')

    # 日期标签
    step = max(1, n // 8)
    for i in range(0, n, step):
        label = f"{dates[i][:4]}-{dates[i][4:6]}-{dates[i][6:]}"
        _draw_text(draw, (px(i), margin['top'] + price_h + 15), label, (136, 136, 136, 255), f_small_l, f_small_c, anchor='mt')

    # 双底区域高亮
    hl_start = max(0, pattern['left_idx'] - 10)
    hl_end = min(n - 1, pattern['right_idx'] + 10)
    draw.rectangle(
        [px(hl_start), margin['top'], px(hl_end), margin['top'] + price_h + gap_h + vol_h],
        fill=(76, 175, 80, 20)
    )

    # 成交量柱
    for i in range(n):
        bar_w = max(1, int(chart_w / n * 0.7))
        x = px(i) - bar_w // 2
        y = vy(volumes[i])
        bh = margin['top'] + price_h + gap_h + vol_h - y
        color = (76, 175, 80, 128) if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else (244, 67, 54, 128)
        draw.rectangle([x, y, x + bar_w, y + bh], fill=color)

    # 价格线
    pts = [(px(i), py(closes[i])) for i in range(n)]
    draw.line(pts, fill=(33, 150, 243, 255), width=2)

    # 颈线 & 目标
    neck_price = pattern['neck_price']
    current_price = closes[-1]
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)

    ny = py(neck_price)
    draw.line([(margin['left'], ny), (W - margin['right'], ny)], fill=(244, 67, 54, 255), width=2)
    _draw_text(draw, (W - margin['right'] + 5, ny), f"颈线 {neck_price:.2f}", (244, 67, 54, 255), f_small_l, f_small_c, anchor='lm')

    if target < max_p * 1.1:
        ty = py(target)
        for dx in range(margin['left'], W - margin['right'], 10):
            draw.line([(dx, ty), (dx + 5, ty)], fill=(255, 152, 0, 255), width=1)
        _draw_text(draw, (W - margin['right'] + 5, ty), f"目标 {target:.2f}", (255, 152, 0, 255), f_small_l, f_small_c, anchor='lm')

    # 左底标记
    lx, lpy = px(pattern['left_idx']), py(pattern['left_price'])
    draw.ellipse([lx-6, lpy-6, lx+6, lpy+6], fill=(76, 175, 80, 255), outline=(255, 255, 255), width=2)
    _draw_text(draw, (lx, lpy + 20), "左底", (76, 175, 80, 255), f_small_l, f_small_c, anchor='mt')

    # 右底标记
    rx, rpy = px(pattern['right_idx']), py(pattern['right_price'])
    draw.ellipse([rx-6, rpy-6, rx+6, rpy+6], fill=(156, 39, 176, 255), outline=(255, 255, 255), width=2)
    _draw_text(draw, (rx, rpy + 20), "右底", (156, 39, 176, 255), f_small_l, f_small_c, anchor='mt')

    # 突破点
    bx = px(pattern['break_idx'])
    draw.ellipse([bx-5, ny-5, bx+5, ny+5], fill=(255, 152, 0, 255), outline=(255, 255, 255, 255), width=2)

    # 现价
    cpy = py(current_price)
    draw.line([(px(n-1), cpy), (W - margin['right'], cpy)], fill=(255, 152, 0, 255), width=1)
    _draw_text(draw, (W - margin['right'] + 5, cpy), f"现价 {current_price:.2f}", (255, 152, 0, 255), f_small_l, f_small_c, anchor='lm')

    # 底部原因
    base_y = H - margin['bottom'] + 15
    _draw_text(draw, (margin['left'], base_y), "高分原因:", (224, 224, 224, 255), f_reason_l, f_reason_c)
    for i, r in enumerate(reasons[:6]):
        _draw_text(draw, (margin['left'], base_y + 18 + i * 18), f"{i+1}. {r}", (170, 170, 170, 255), f_label_l, f_label_c)

    img.save(save_path, 'PNG')

# ============ 主程序 ============

def main():
    print("=" * 60)
    print("双底突破形态扫描 (优化版)")
    print("颈线>10% | 突破放量>1.5xMA20 | 3天不回踩颈线×0.98")
    print("=" * 60)
    
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
            
            patterns = detect_double_bottom(df, window_bottom=22, window_breakout=8)
            name = stock_map.get(code, code)
            
            for p in patterns:
                score, reasons = score_pattern(df, p)
                if score >= 30:
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
    
    print(f"\n[4/4] 生成图表...")
    output_svg = os.path.expanduser('~/double_bottom_charts_20260521')
    output_png = os.path.expanduser('~/double_bottom_charts_20260521_png')
    os.makedirs(output_svg, exist_ok=True)
    os.makedirs(output_png, exist_ok=True)

    png_paths = []
    for i, item in enumerate(top5):
        svg_path = os.path.join(output_svg, f'top{i+1}_{item["code"]}.svg')
        png_path = os.path.join(output_png, f'top{i+1}_{item["code"]}.png')
        draw_svg_chart(item['df'], item['pattern'], item['score'], item['reasons'], item['name'], item['code'], svg_path)
        draw_png_chart(item['df'], item['pattern'], item['score'], item['reasons'], item['name'], item['code'], png_path)
        print(f"  SVG: {svg_path}")
        print(f"  PNG: {png_path}")
        png_paths.append(png_path)

    print(f"\n完成! PNG保存在: {output_png}")
    print("=" * 50)
    
    for i, item in enumerate(top5):
        p = item['pattern']
        cp = float(item['df'][-1]['close'])
        dist = (cp - p['neck_price']) / p['neck_price'] * 100
        min_b = min(p['left_price'], p['right_price'])
        target = p['neck_price'] + (p['neck_price'] - min_b)
        space = (target - cp) / cp * 100
        bvr = p.get('break_vol_ratio', 1.0)
        print(f"\n{'='*40}")
        print(f"第{i+1}名: {item['name']} ({item['code']})")
        print(f"  评分: {item['score']}/100")
        print(f"  突破日: {p['break_date']} (距今{len(item['df'])-1-p['break_idx']}天)")
        print(f"  左底: {format_date(p['left_date'])} @{p['left_price']:.2f}")
        print(f"  右底: {format_date(p['right_date'])} @{p['right_price']:.2f}")
        print(f"  颈线: @{p['neck_price']:.2f} | 现价: {cp:.2f} (突破{dist:.1f}%)")
        print(f"  目标: @{target:.2f} (剩余空间{space:.1f}%)")
        print(f"  颈线高度: {p['height_pct']:.1%} | 突破量比: {bvr:.1f}x")
        for r in item['reasons']: print(f"  + {r}")

    # ============ 推送企业微信 ============
    print(f"\n[推送] 发送到企业微信群...")
    try:
        _send_wecom_summary(top5, png_paths)
        print("  推送成功 ✅")
    except Exception as e:
        print(f"  推送失败: {e}")


def _send_wecom_summary(top5: list, png_paths: list | None = None):
    """将扫描结果汇总推送企业微信群（含图片）"""
    if not top5:
        send_text("📊 双底扫描完成，未发现符合条件的突破形态")
        return

    # 汇总消息
    lines = [
        "## 📊 双底突破扫描结果",
        f"扫描时间: {top5[0]['df'][-1]['trade_date'] if top5 else '--'}",
        "",
    ]

    for i, item in enumerate(top5):
        p = item['pattern']
        cp = float(item['df'][-1]['close'])
        min_b = min(p['left_price'], p['right_price'])
        target_price = p['neck_price'] + (p['neck_price'] - min_b)
        space = (target_price - cp) / cp * 100
        break_days = len(item['df']) - 1 - p['break_idx']
        dist_pct = (cp - p['neck_price']) / p['neck_price'] * 100

        emoji = "🔥" if i == 0 else "⭐" if i < 3 else "💡"
        lines.append(
            f"{emoji} **TOP{i+1} {item['name']}** ({item['code'].split('.')[0]})"
        )
        lines.append(f"> 评分: **{item['score']}/100**")
        lines.append(f"> 突破日: {p['break_date']} ({break_days}天前)")
        lines.append(f"> 颈线: {p['neck_price']:.2f} | 现价: {cp:.2f} (突破{dist_pct:+.1f}%)")
        lines.append(f"> 目标位: **{target_price:.2f}** (剩余空间 **{space:.1f}%**)")
        if i < 3:
            key_reason = item['reasons'][0] if item['reasons'] else ''
            lines.append(f"> {key_reason}")
        lines.append("")

    send_markdown("\n".join(lines))

    # 发送图表
    # 优先发 PNG，没有则发 SVG 文件
    if png_paths:
        import time as _time
        for png_path in png_paths:
            if os.path.exists(png_path):
                result = send_image_file(png_path)
                print(f"  图片 {os.path.basename(png_path)}: {result.get('errmsg', result)}")
                _time.sleep(0.3)
    else:
        # 没有 PNG，尝试发送 SVG 文件
        svg_dir = os.path.expanduser('~/double_bottom_charts_20260521')
        if os.path.isdir(svg_dir):
            import time as _time
            svg_files = sorted([f for f in os.listdir(svg_dir) if f.endswith('.svg')])
            for svg_file in svg_files:
                svg_path = os.path.join(svg_dir, svg_file)
                media_id = upload_file(svg_path)
                if media_id:
                    result = send_file(media_id)
                    print(f"  文件 {svg_file}: {result.get('errmsg', result)}")
                _time.sleep(0.3)

if __name__ == '__main__':
    main()
