"""Wrapper: run V3 scanner, filter results by break_date range"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

# Override for date range scan
m.TODAY = '20260708'
m.END_DATE = '20260708'
m.DB_START = '20250501'   # 放宽左底范围
m.MIN_SCORE = 30           # 放宽评分门槛
m.TOP_K = 50
m.TOP_CHART = 20

BREAK_START = '20260706'
BREAK_END = '20260708'

print("=" * 65)
print(f"  双底V3 - 突破日期筛选: {BREAK_START} ~ {BREAK_END}")
print("=" * 65)

m.OUTPUT_DIR = os.path.join(m.SCRIPT_DIR, 'output', f'{m.TODAY}_range')
os.makedirs(m.OUTPUT_DIR, exist_ok=True)

stocks, stock_map, industry_map = m.get_stock_list()
codes = [s['ts_code'] for s in stocks]
print(f"\n全A股: {len(codes)} 只")

csv_path = os.path.join(m.OUTPUT_DIR, f'top{m.TOP_K}_双底突破_{m.TODAY}_range.csv')

t0 = time.time()
total_hits = 0
for batch_no in range(0, len(codes), m.BATCH_SIZE):
    batch_codes = codes[batch_no:batch_no + m.BATCH_SIZE]
    label = f"batch {batch_no//m.BATCH_SIZE + 1}"
    print(f"\n--- {label}: {len(batch_codes)} stocks ---")
    hits = m.scan_batch(batch_codes, stock_map, industry_map, batch_no, len(codes))
    total_hits += len(hits)
    print(f"  Hits: {len(hits)} (total: {total_hits})")
    m.merge_and_save(hits, csv_path, label)

elapsed = time.time() - t0
print(f"\n扫描完成: {elapsed/60:.1f}分钟, {total_hits} 总命中")

# 按突破日期筛选
final = m.read_existing_top20(csv_path)
filtered = [r for r in final if BREAK_START <= r['break_date'] <= BREAK_END]
filtered.sort(key=lambda x: x['score'], reverse=True)

print(f"\n突破日期 {BREAK_START}~{BREAK_END} 筛选后: {len(filtered)} 只")
print("-" * 65)
for i, r in enumerate(filtered[:20]):
    print(f"  {i+1}. {r['name']}({r['code']}) 评分{r['score']} 突破日{r['break_date']} 行业{r.get('industry','')}")

# 写筛选后的CSV
import csv
filtered_csv = os.path.join(m.OUTPUT_DIR, f'双底_突破{BREAK_START}_{BREAK_END}_{len(filtered)}只.csv')
with open(filtered_csv, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f)
    writer.writerow(['排名','代码','名称','评分','行业','左底日期','右底日期','颈线价','突破日期','突破价','剩余空间','上榜理由'])
    for i, r in enumerate(filtered):
        writer.writerow([
            i+1, r['code'], r['name'], r['score'], r.get('industry',''),
            r['left_date'], r['right_date'], f"{r['neck_price']:.2f}",
            r['break_date'], f"{r.get('break_price',''):.2f}" if r.get('break_price') else '',
            f"{r.get('upside_pct',''):.1f}%" if r.get('upside_pct') else '',
            '; '.join(r.get('_reasons', []))
        ])

# 画图
print(f"\n生成PNG图表...")
for i, r in enumerate(filtered[:m.TOP_CHART]):
    code = r['code']
    name = r['name']
    df = m.get_daily(code, m.PLOT_START, m.END_DATE)
    if df is None:
        print(f"  [{i+1}] {code} {name}: 无日线数据")
        continue
    patterns = m.detect_double_bottom(df)
    if not patterns:
        print(f"  [{i+1}] {code} {name}: 未检测到形态")
        continue

    # 找匹配突破日期的形态
    matched = [p for p in patterns if BREAK_START <= p['break_date'] <= BREAK_END]
    if not matched:
        matched = patterns  # fallback: 用评分最高的
        best_p = max(matched, key=lambda p: m.score_pattern(df, p)[0])
    else:
        best_p = max(matched, key=lambda p: m.score_pattern(df, p)[0])
    
    score, reasons = m.score_pattern(df, best_p)
    if score < 0:
        score = r['score']
        reasons = []

    svg_path = os.path.join(m.OUTPUT_DIR, f'top{i+1}_{code.split(".")[0]}_{name}_双底.svg')
    m.draw_svg_chart(df, best_p, score, reasons, name, code, svg_path)
    print(f"  [{i+1}] {code} {name}: {os.path.basename(svg_path)}")
    time.sleep(m.API_SLEEP)

# 转PNG
print(f"\nSVG -> PNG...")
svg_files = sorted([f for f in os.listdir(m.OUTPUT_DIR) if f.endswith('.svg')])
venv_py = os.path.join(m.SCRIPT_DIR, '.venv/bin/python3')

import subprocess
for svg_file in svg_files:
    svg_path = os.path.join(m.OUTPUT_DIR, svg_file)
    png_path = svg_path.replace('.svg', '.png')
    script = f"import cairosvg; cairosvg.svg2png(url=r'{svg_path}', write_to=r'{png_path}', output_width=1200, output_height=864)"
    subprocess.run([venv_py, '-c', script], capture_output=True, timeout=30)
    print(f"  -> {os.path.basename(png_path)}")

print(f"\n输出: {m.OUTPUT_DIR}")
print(f"CSV: {os.path.basename(filtered_csv)}")
