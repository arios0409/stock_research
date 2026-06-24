#!/usr/bin/env python3
"""Draw triangle convergence chart for 300852 四会富仕 and convert to PNG"""
import urllib.request, json, os, math, sys
from datetime import datetime

TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'

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
    except Exception as e:
        print(f"API error: {e}")
        return None

code = '300852.SZ'
name = '四会富仕'
plot_start = '20240501'
end_date = '20260622'

print(f"Fetching daily data for {code} ({name})...")
result = api_call('daily', ts_code=code, start_date=plot_start, end_date=end_date)
if not result:
    print("ERROR: No data returned from API")
    sys.exit(1)

fields = result['fields']
df = [dict(zip(fields, item)) for item in result['items']]
df.sort(key=lambda x: x['trade_date'])
print(f"Got {len(df)} days, {df[0]['trade_date']} - {df[-1]['trade_date']}")

closes = [float(d['close']) for d in df]
highs = [float(d['high']) for d in df]
lows = [float(d['low']) for d in df]
volumes = [float(d['vol']) for d in df]
dates = [d['trade_date'] for d in df]
n = len(df)

# Find swings
SWING_ORDER = 3
swing_highs, swing_lows = [], []
for i in range(SWING_ORDER, n - SWING_ORDER):
    h, l = highs[i], lows[i]
    if all(highs[j] <= h for j in range(i - SWING_ORDER, i + SWING_ORDER + 1) if j != i):
        swing_highs.append((i, h))
    if all(lows[j] >= l for j in range(i - SWING_ORDER, i + SWING_ORDER + 1) if j != i):
        swing_lows.append((i, l))
print(f"Swings: {len(swing_highs)} highs, {len(swing_lows)} lows")

# Detect triangles
TRI_MIN, TRI_MAX = 15, 100
HGT_MIN, HGT_MAX = 0.03, 0.35
BREAKOUT_LA = 15
PRE_N, PRE_MIN = 25, -0.03

seen = set()
best = None
best_score = -1

for h0 in range(len(swing_highs)):
    for l0 in range(len(swing_lows)):
        h1i, h1v = swing_highs[h0]
        l1i, l1v = swing_lows[l0]
        if abs(h1i - l1i) > 10: continue
        hp, lp = [(h1i, h1v)], [(l1i, l1v)]
        for h in swing_highs[h0 + 1:]:
            if h[0] > lp[-1][0]: hp.append(h); break
        for l in swing_lows[l0 + 1:]:
            if l[0] > hp[-1][0]: lp.append(l); break
        if len(hp) < 2 or len(lp) < 2: continue
        hi, hv = [p[0] for p in hp], [p[1] for p in hp]
        li, lv = [p[0] for p in lp], [p[1] for p in lp]
        h_s = (hv[-1] - hv[0]) / max(hi[-1] - hi[0], 1)
        l_s = (lv[-1] - lv[0]) / max(li[-1] - li[0], 1)
        if h_s >= 0 or l_s <= 0: continue
        ts, te = min(hi[0], li[0]), max(hi[-1], li[-1])
        dur = te - ts
        if dur < TRI_MIN or dur > TRI_MAX: continue
        hgt = hv[0] - lv[0]
        avg = sum(closes[ts:te + 1]) / (te - ts + 1)
        if hgt / avg < HGT_MIN or hgt / avg > HGT_MAX: continue
        key = (ts, te)
        if key in seen: continue
        seen.add(key)
        bi, bp = None, None
        for i in range(te + 1, min(te + BREAKOUT_LA + 1, n)):
            ul = hv[0] + h_s * (i - hi[0])
            if closes[i] > ul: bi, bp = i, closes[i]; break
        if bi is None:
            le = n - 1; ue = hv[0] + h_s * (le - hi[0])
            if closes[le] > ue * 0.985: bi, bp = le, closes[le]
        if bi is None: continue
        ps = max(0, ts - PRE_N)
        pc = closes[ps:ts]
        if len(pc) < 10: continue
        pt = (pc[-1] - pc[0]) / pc[0]
        if pt < PRE_MIN: continue
        tgt = bp + hgt; cp = closes[-1]
        up = (tgt - bp) / bp * 100
        ag = (cp - bp) / bp * 100
        pst = closes[bi:]
        if len(pst) > 1:
            pr = [(pst[j] - pst[j - 1]) / pst[j - 1] for j in range(1, len(pst))]
            wr = sum(1 for r in pr if r > 0) / len(pr)
        else: wr = 0.5
        wr = min(max(wr, 0.3), 0.95)
        sym = 1 - abs(abs(h_s) - abs(l_s)) / (abs(h_s) + abs(l_s) + 1e-10)
        dtr = (datetime.strptime(dates[-1], '%Y%m%d') - datetime.strptime(dates[te], '%Y%m%d')).days
        if dtr <= 3: tsc = 100
        elif dtr <= 7: tsc = 90
        elif dtr <= 14: tsc = 75
        elif dtr <= 21: tsc = 60
        elif dtr <= 30: tsc = 50
        else: tsc = max(0, 40 - (dtr - 30))
        total = tsc * 0.35 + wr * 100 * 0.30 + min(100, up * 5) * 0.35
        if total > best_score:
            best_score = total
            best = {'hp': hp, 'lp': lp, 'h_slope': h_s, 'l_slope': l_s, 'hgt': hgt,
                'bk_i': bi, 'bk_p': bp, 'tgt': tgt, 'cp': cp, 'up': up, 'ag': ag,
                'wr': wr, 'sym': sym, 'pre_trend': pt, 'dtr': dtr, 'dur': dur,
                'tri_s': ts, 'tri_e': te,
                'ts_date': dates[ts], 'te_date': dates[te], 'bk_date': dates[bi]}

if not best:
    print("No triangle pattern found!")
    sys.exit(1)

p = best
print(f"Pattern: {p['ts_date']}-{p['te_date']}, breakout {p['bk_date']}, score {best_score:.1f}")

# ==== Generate SVG ====
def fmt_date(ds):
    return f"{ds[:4]}-{ds[4:6]}-{ds[6:]}"

W, H = 1000, 720
M = {'top': 55, 'right': 85, 'bottom': 115, 'left': 80}
cw, ch = W - M['left'] - M['right'], H - M['top'] - M['bottom']
ph, vh, gh = ch * 0.58, ch * 0.22, ch * 0.08

min_p = min(lows) * 0.97
max_p = max(highs) * 1.03
max_v = max(volumes) * 1.2 if volumes else 1

def _px(i):
    return M['left'] + (i / (n - 1)) * cw if n > 1 else M['left']
def _py(pr):
    return M['top'] + (1 - (pr - min_p) / (max_p - min_p)) * ph if max_p > min_p else M['top']
def _vy(vl):
    return M['top'] + ph + gh + (1 - vl / max_v) * vh if max_v > 0 else M['top'] + ph + gh

svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
       f'<rect width="{W}" height="{H}" fill="#0d1117"/>',
       f'<text x="{W/2}" y="24" text-anchor="middle" font-size="17" fill="#58a6ff" font-weight="bold">'
       f'{name} ({code})  三角收敛上涨中继  评分:{int(best_score)}/100</text>']

for i in range(6):
    gp = min_p + (max_p - min_p) / 5 * i
    yy = _py(gp)
    svg.append(f'<line x1="{M["left"]}" y1="{yy}" x2="{W - M["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
    svg.append(f'<text x="{M["left"] - 8}" y="{yy + 4}" text-anchor="end" font-size="10" fill="#8b949e">{gp:.2f}</text>')

for i in range(0, n, max(1, n // 8)):
    svg.append(f'<text x="{_px(i)}" y="{M["top"] + ph + gh + vh + 15}" text-anchor="middle" font-size="9" fill="#8b949e">{fmt_date(dates[i])}</text>')

# Triangle highlight
svg.append(f'<rect x="{_px(p["tri_s"])}" y="{M["top"]}" width="{_px(p["tri_e"]) - _px(p["tri_s"])}" height="{ph + vh + gh}" fill="#FFD700" opacity="0.06" rx="2"/>')

# Volume
for i in range(n):
    bw = max(1, cw / n * 0.7)
    xv = _px(i) - bw / 2
    yv = _vy(volumes[i])
    bh = M['top'] + ph + gh + vh - yv
    color = '#3fb950' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#f85149'
    svg.append(f'<rect x="{xv}" y="{yv}" width="{bw}" height="{bh}" fill="{color}" opacity="0.5"/>')

# Lines
hs, ls = p['h_slope'], p['l_slope']
hib, hvb = p['hp'][0][0], p['hp'][0][1]
lib, lvb = p['lp'][0][0], p['lp'][0][1]

ul = ' '.join(f'{_px(i)},{_py(hvb + hs * (i - hib))}' for i in range(p['tri_s'], min(p['tri_e'] + int(BREAKOUT_LA * 0.5), n)))
svg.append(f'<polyline points="{ul}" stroke="#f85149" stroke-width="2.8" fill="none"/>')

ll = ' '.join(f'{_px(i)},{_py(lvb + ls * (i - lib))}' for i in range(p['tri_s'], min(p['tri_e'] + int(BREAKOUT_LA * 0.5), n)))
svg.append(f'<polyline points="{ll}" stroke="#3fb950" stroke-width="2.8" fill="none"/>')

# Triangle fill
fp = [f'{_px(i)},{_py(hvb + hs * (i - hib))}' for i in range(p['tri_s'], p['tri_e'] + 1)] + \
     [f'{_px(i)},{_py(lvb + ls * (i - lib))}' for i in range(p['tri_e'], p['tri_s'] - 1, -1)]
svg.append(f'<polygon points="{" ".join(fp)}" fill="#FFD700" opacity="0.10"/>')

# Swing markers
for idx, pv in p['hp']:
    if idx < n:
        svg.append(f'<polygon points="{_px(idx)-7},{_py(pv)-9} {_px(idx)+7},{_py(pv)-9} {_px(idx)},{_py(pv)+1}" fill="#f85149" stroke="#fff" stroke-width="1.5"/>')
        svg.append(f'<text x="{_px(idx)}" y="{_py(pv)-13}" text-anchor="middle" font-size="9" fill="#f85149">¥{pv:.2f}</text>')
for idx, pv in p['lp']:
    if idx < n:
        svg.append(f'<polygon points="{_px(idx)-7},{_py(pv)+9} {_px(idx)+7},{_py(pv)+9} {_px(idx)},{_py(pv)-1}" fill="#3fb950" stroke="#fff" stroke-width="1.5"/>')
        svg.append(f'<text x="{_px(idx)}" y="{_py(pv)+18}" text-anchor="middle" font-size="9" fill="#3fb950">¥{pv:.2f}</text>')

# Breakout
bi = p['bk_i']
if bi < n:
    svg.append(f'<circle cx="{_px(bi)}" cy="{_py(closes[bi])}" r="8" fill="#f0883e" stroke="#fff" stroke-width="2.5"/>')
    svg.append(f'<text x="{_px(bi)}" y="{_py(closes[bi]) - 14}" text-anchor="middle" font-size="11" fill="#f0883e" font-weight="bold">★ Break ¥{closes[bi]:.2f}</text>')

# Price line
pts = ' '.join(f'{_px(i)},{_py(closes[i])}' for i in range(n))
svg.append(f'<polyline points="{pts}" stroke="#58a6ff" stroke-width="1.8" fill="none"/>')

# Target
tgt = p['tgt']
if tgt < max_p * 1.1:
    ty = _py(tgt)
    svg.append(f'<line x1="{M["left"]}" y1="{ty}" x2="{W - M["right"]}" y2="{ty}" stroke="#FFD700" stroke-width="1.5" stroke-dasharray="6,4"/>')
    svg.append(f'<text x="{W - M["right"] + 5}" y="{ty + 5}" font-size="11" fill="#FFD700" font-weight="bold">▼ Target {tgt:.2f}</text>')

# Break price
bky = _py(p['bk_p'])
svg.append(f'<line x1="{M["left"]}" y1="{bky}" x2="{W - M["right"]}" y2="{bky}" stroke="#3fb950" stroke-width="1" stroke-dasharray="3,3"/>')
svg.append(f'<text x="{W - M["right"] + 5}" y="{bky + 5}" font-size="11" fill="#3fb950">Break ¥{p["bk_p"]:.2f}</text>')

# Current
cpy = _py(closes[-1])
svg.append(f'<line x1="{_px(n-1)}" y1="{cpy}" x2="{W - M["right"]}" y2="{cpy}" stroke="#88ccff" stroke-width="1.5"/>')
svg.append(f'<text x="{W - M["right"] + 5}" y="{cpy + 5}" font-size="11" fill="#88ccff" font-weight="bold">● Now ¥{closes[-1]:.2f}</text>')

# Reasons
by = H - M['bottom'] + 18
reasons = [
    f"形态于{p['dtr']}天前收敛完成（{fmt_date(p['te_date'])}），突破信号有效",
    f"突破后日线胜率{p['wr']*100:.0f}%，表现优秀",
    f"量度目标涨幅{p['up']:.1f}%（目标¥{p['tgt']:.2f} / 突破¥{p['bk_p']:.2f}）",
    f"三角收敛对称度{p['sym']*100:.0f}%，形态标准",
    f"当前价格¥{closes[-1]:.2f}，相比突破价已涨{((closes[-1]-p['bk_p'])/p['bk_p']*100):.1f}%",
    f"三角持续{p['dur']}个交易日，整理充分",
]
svg.append(f'<text x="{M["left"]}" y="{by}" font-size="13" fill="#58a6ff" font-weight="bold">上榜理由 (综合得分: {int(best_score)}):</text>')
for i, line in enumerate(reasons[:7]):
    svg.append(f'<text x="{M["left"] + 10}" y="{by + 18 + i * 16}" font-size="11" fill="#c9d1d9">{i+1}. {line}</text>')

svg.append('</svg>')
svg_content = '\n'.join(svg)

# Save SVG to scanner output
svg_dir = os.path.dirname(os.path.abspath(__file__))
svg_path = os.path.join(svg_dir, '300852_四会富仕_三角收敛.svg')
with open(svg_path, 'w', encoding='utf-8') as f:
    f.write(svg_content)
print(f"SVG: {svg_path}")

# Convert to PNG via cairosvg
import cairosvg
png_dir = '/data/data/com.termux/files/home/storage/shared/Hermes_output/20260622_三角收敛'
os.makedirs(png_dir, exist_ok=True)
png_path = os.path.join(png_dir, '300852_四会富仕_三角收敛.png')
cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=1000, output_height=720)
print(f"PNG: {png_path} ({os.path.getsize(png_path)/1024:.0f} KB)")
