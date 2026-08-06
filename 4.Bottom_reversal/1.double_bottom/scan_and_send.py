#!/usr/bin/env python3
"""扫描7/4 + 画图转PNG + 发企业微信"""
import sys, os, time, re, json, urllib.request, cairosvg
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m
import tushare as ts, pandas as pd

m.REVENUE_CACHE = {}
m.TODAY = '20260717'
m.END_DATE = '20260717'
m.OUTPUT_DIR = 'output/scan_0717'
os.makedirs(m.OUTPUT_DIR, exist_ok=True)

with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    token = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read()).group(1)
pro = ts.pro_api(token)

# === Scan ===
print('V5扫描 2026-07-17')
stocks, stock_map, industry_map = m.get_stock_list()
codes = [s['ts_code'] for s in stocks]
csv_path = os.path.join(m.OUTPUT_DIR, 'top30_双底_20260717.csv')
total = 0
for bn in range((len(codes)+m.BATCH_SIZE-1)//m.BATCH_SIZE):
    bs = bn*m.BATCH_SIZE; be = min(bs+m.BATCH_SIZE, len(codes))
    hits = m.scan_batch(codes[bs:be], stock_map, industry_map, bs, len(codes))
    total += len(hits)
    m.merge_and_save(hits, csv_path, f'B{bn+1}')
    if (bn+1) % 3 == 0: print(f'进度 {be}/{len(codes)} 命中{total}')

final = m.read_existing_top20(csv_path)
print(f'\n扫描完成: top{len(final)}')
for i, r in enumerate(final[:20]):
    print(f'  {i+1}. {r["name"]}({r["code"]}) {r["score"]}分 空间{r["upside_pct"]}%')

# === Draw charts + PNG ===
orig = m.draw_svg_chart
def draw_ext(df, p, sc, rs, nm, cd, path):
    orig(df, p, sc, rs, nm, cd, path)
    with open(path, 'r') as f: svg = f.read()
    closes = [float(d['close']) for d in df]
    mp = min(closes)*0.97; xp = max(closes)*1.02
    W,H=1000,720; MM={'top':60,'right':80,'bottom':120,'left':80}
    ph = (H-MM['top']-MM['bottom'])*0.60
    def py(v): return MM['top']+(1-(v-mp)/(xp-mp))*ph
    bottom = min(p['left_price'],p['right_price']); by_=py(bottom)
    extra = (f'<line x1="{MM["left"]}" y1="{by_:.1f}" x2="{W-MM["right"]}" y2="{by_:.1f}" stroke="#f85149" stroke-width="1.5" stroke-dasharray="6,3"/>'
             f'<text x="{W-MM["right"]+5}" y="{by_+5:.1f}" font-size="11" fill="#f85149" font-weight="bold">━ 底线 {bottom:.2f}</text>')
    svg = svg.replace('</svg>', extra+'\n</svg>')
    with open(path, 'w') as f: f.write(svg)
m.draw_svg_chart = draw_ext

svg_dir = os.path.join(m.OUTPUT_DIR, 'charts')
png_dir = os.path.join(m.OUTPUT_DIR, 'charts_png')
os.makedirs(svg_dir, exist_ok=True)
os.makedirs(png_dir, exist_ok=True)
png_files = []

print(f'\n画图+转PNG...')
for i, r in enumerate(final[:20]):
    code = r['code']; name = r['name']; score = r['score']
    try:
        df_plot = m.get_daily_plot(code)
        if not df_plot or len(df_plot)<60: continue
        pats = m.detect_double_bottom(df_plot)
        if not pats: continue
        best = pats[0]
        sc, rs = m.score_pattern(df_plot, best)
        if sc<0: sc=score
        fname = f'top{i+1}_{code.split(".")[0]}_{name}'
        svg_path = os.path.join(svg_dir, fname+'.svg')
        png_path = os.path.join(png_dir, fname+'.png')
        draw_ext(df_plot, best, sc, rs, name, code, svg_path)
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=800, output_height=576)
        png_files.append(png_path)
        print(f'  {i+1}. {name} done')
    except Exception as e:
        print(f'  {code} 失败: {e}')
    time.sleep(0.12)

# === Send to WeChat ===
WEBHOOK_KEY = '62d8c6d6-df0a-410b-915d-bd8bbdd145a8'

def upload_file(key, path):
    """Send image via base64 inline (webhook upload_media has size issues)"""
    import base64, hashlib
    with open(path, 'rb') as f: raw = f.read()
    b64 = base64.b64encode(raw).decode()
    md5 = hashlib.md5(raw).hexdigest()
    payload = {'msgtype': 'image', 'image': {'base64': b64, 'md5': md5}}
    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}'
    data = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read().decode())
        return 'sent' if result.get('errcode') == 0 else ''
    except Exception as e:
        print(f'上传异常: {e}')
        return ''

def post(key, payload):
    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}'
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except Exception as e:
        return {'errcode':-1,'errmsg':str(e)}

# Text message
msg_lines = ['【双底突破 V5】2026-07-17']
for i, r in enumerate(final[:20]):
    msg_lines.append(f'{i+1}. {r["name"]} {r["score"]}分 空间{r["upside_pct"]}% {r.get("industry","")}')
msg = '\n'.join(msg_lines)
post(WEBHOOK_KEY, {'msgtype':'text','text':{'content':msg}})
print(f'\n文字已发送')

# Images - send first 10 via base64 (upload_file now sends directly)
for i, png in enumerate(png_files[:20]):
    r = upload_file(WEBHOOK_KEY, png)
    print(f'  图{i+1}: {r}')
    time.sleep(1)

print(f'\n完成: {png_dir}')
