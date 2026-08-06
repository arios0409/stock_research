#!/usr/bin/env python3
"""6/12-6/15回测图表 — 用扫描器SVG画法"""
import os, sys, re, time, numpy as np, pandas as pd, tushare as ts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

BASE = os.path.dirname(os.path.abspath(__file__))
BACKTEST_DIR = os.path.join(BASE, 'output', 'backtest_v5')
CHART_DIR = os.path.join(BASE, 'output', 'charts_0701_0703')
HIT_DIR = os.path.join(CHART_DIR, 'reached_target')
FELL_DIR = os.path.join(CHART_DIR, 'fell_bottom')
os.makedirs(HIT_DIR, exist_ok=True)
os.makedirs(FELL_DIR, exist_ok=True)

with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    token = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read()).group(1)
pro = ts.pro_api(token)
PLOT_END = '20260703'

# Collect stocks
all_stocks = []; seen = set()
for d in ['20260701','20260702','20260703']:
    oc = os.path.join(BACKTEST_DIR, d, f'outcome_{d}.csv')
    if not os.path.exists(oc): continue
    odf = pd.read_csv(oc, encoding='utf-8-sig')
    for _, row in odf.iterrows():
        code = str(row['代码']).strip()
        if code in seen: continue
        seen.add(code)
        all_stocks.append({
            'code': code, 'name': str(row['名称']).strip(),
            'score': float(row['评分']),
            'hit': bool(row['达目标']), 'fell': bool(row['破右底']),
            'target_price': float(row['目标价']),
        })

hit_s = [s for s in all_stocks if s['hit']]  # 触及目标即成功
fell_s = [s for s in all_stocks if s['fell'] and not s['hit']]  # 仅跌破且未达标
print(f"达标: {len(hit_s)}, 破底: {len(fell_s)}")

# Patch draw_svg to add bottom line
orig_draw = m.draw_svg_chart

def draw_with_bottom(df, pattern, score, reasons, stock_name, stock_code, save_path, outcome=''):
    """调用原始SVG画法 + 底线 + 结果标注"""
    orig_draw(df, pattern, score, reasons, stock_name, stock_code, save_path)
    
    # Post-process: add bottom line after the fact
    # We rewrite the SVG file to add bottom line
    with open(save_path, 'r', encoding='utf-8') as f:
        svg = f.read()
    
    # Calculate positions
    closes = [float(d['close']) for d in df]
    min_p = min(closes) * 0.97; max_p = max(closes) * 1.02
    W, H = 1000, 720
    margin = {'top': 60, 'right': 80, 'bottom': 120, 'left': 80}
    chart_w = W - margin['left'] - margin['right']
    price_h = (H - margin['top'] - margin['bottom']) * 0.60
    
    def py(price):
        return margin['top'] + (1 - (price - min_p) / (max_p - min_p)) * price_h
    
    bottom_price = min(pattern['left_price'], pattern['right_price'])
    by_ = py(bottom_price)
    
    # Add bottom line before </svg>
    bottom_line = (
        f'<line x1="{margin["left"]}" y1="{by_:.1f}" x2="{W - margin["right"]}" y2="{by_:.1f}" '
        f'stroke="#f85149" stroke-width="1.5" stroke-dasharray="6,3"/>'
        f'<text x="{W - margin["right"] + 5}" y="{by_ + 5:.1f}" font-size="11" fill="#f85149" font-weight="bold">'
        f'━ 底线 {bottom_price:.2f}</text>'
    )
    
    # Modify title to show outcome
    outcome_tag = '✅达标' if outcome == 'hit' else '❌破底'
    svg = svg.replace('W双底突破</text>', f'W双底突破 {outcome_tag}</text>')
    
    svg = svg.replace('</svg>', bottom_line + '\n</svg>')
    
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(svg)

m.draw_svg_chart = draw_with_bottom

# Draw charts
for label, stocks, out_dir in [
    ('达标', hit_s, HIT_DIR),
    ('破底', fell_s, FELL_DIR),
]:
    print(f"\n{label}组 ({len(stocks)}张)...")
    for i, s in enumerate(stocks):
        try:
            # Fetch data
            df = m.get_daily_plot(s['code'])
            if not df or len(df) < 60: continue
            
            # Find pattern
            pats = m.detect_double_bottom(df)
            if not pats: continue
            best = pats[0]
            score, reasons = m.score_pattern(df, best)
            if score < 0: score = s['score']
            
            fname = f"{s['code'].split('.')[0]}_{s['name']}.svg"
            path = os.path.join(out_dir, fname)
            outcome = 'hit' if s['hit'] else 'fell'
            draw_with_bottom(df, best, score, reasons, s['name'], s['code'], path, outcome)
            
            if (i+1) % 10 == 0: print(f"  {i+1}/{len(stocks)}")
        except Exception as e:
            print(f"  {s['code']} 失败: {e}")
        time.sleep(0.12)
    print(f"  {label}组完成: {out_dir}")

print(f"\n全部完成")
print(f"  达标: {HIT_DIR}")
print(f"  破底: {FELL_DIR}")
