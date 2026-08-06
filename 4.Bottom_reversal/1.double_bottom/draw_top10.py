#!/usr/bin/env python3
"""纯画图 — 从扫描结果画top10，无回测判断"""
import os, sys, re, time
import numpy as np, pandas as pd, tushare as ts
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

BASE = os.path.dirname(os.path.abspath(__file__))
SCAN_DIR = os.path.join(BASE, 'output', 'backtest_v5')
CHART_DIR = os.path.join(BASE, 'output', 'charts_0701_0703_top10')
os.makedirs(CHART_DIR, exist_ok=True)

with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    token = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read()).group(1)
pro = ts.pro_api(token)

# Patch SVG to add bottom line
orig = m.draw_svg_chart
def draw_svg_ext(df, pattern, score, reasons, name, code, path):
    orig(df, pattern, score, reasons, name, code, path)
    with open(path, 'r') as f: svg = f.read()
    closes = [float(d['close']) for d in df]
    min_p = min(closes)*0.97; max_p = max(closes)*1.02
    W,H=1000,720; margin={'top':60,'right':80,'bottom':120,'left':80}
    price_h = (H-margin['top']-margin['bottom'])*0.60
    def py(p): return margin['top']+(1-(p-min_p)/(max_p-min_p))*price_h
    bottom = min(pattern['left_price'],pattern['right_price'])
    by_=py(bottom)
    extra = (
        f'<line x1="{margin["left"]}" y1="{by_:.1f}" x2="{W-margin["right"]}" y2="{by_:.1f}" stroke="#f85149" stroke-width="1.5" stroke-dasharray="6,3"/>'
        f'<text x="{W-margin["right"]+5}" y="{by_+5:.1f}" font-size="11" fill="#f85149" font-weight="bold">━ 底线 {bottom:.2f}</text>'
    )
    svg = svg.replace('</svg>', extra+'\n</svg>')
    with open(path, 'w') as f: f.write(svg)
m.draw_svg_chart = draw_svg_ext

for d in ['20260701','20260702','20260703']:
    tc = os.path.join(SCAN_DIR, d, f'top20_双底_{d}.csv')
    if not os.path.exists(tc): continue
    df = pd.read_csv(tc, encoding='utf-8-sig')
    day_dir = os.path.join(CHART_DIR, d)
    os.makedirs(day_dir, exist_ok=True)
    
    print(f'{d}: {len(df)}只, 画top10...')
    for i, (_, row) in enumerate(df.head(10).iterrows()):
        code = str(row['代码']).strip(); name = str(row['名称']).strip()
        score = float(row['评分'])
        try:
            df_plot = m.get_daily_plot(code)
            if not df_plot or len(df_plot)<60: continue
            pats = m.detect_double_bottom(df_plot)
            if not pats: continue
            best = pats[0]
            sc, rs = m.score_pattern(df_plot, best)
            if sc<0: sc=score
            fname = f'top{i+1}_{code.split(".")[0]}_{name}.svg'
            path = os.path.join(day_dir, fname)
            draw_svg_ext(df_plot, best, sc, rs, name, code, path)
        except Exception as e:
            print(f'  {code} 失败: {e}')
        time.sleep(0.12)
    print(f'  {d}完成')

print(f'\n全部: {CHART_DIR}')
