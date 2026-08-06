"""Wrapper to run v3 scanner on first 100 stocks for testing"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

# Override for quick test
m.BATCH_SIZE = 50
m.TOP_K = 10
m.TOP_CHART = 3
m.MIN_SCORE = 40

print("=" * 65)
print("  TEST RUN - first 100 stocks, batch=50, top=10")
print("=" * 65)

stocks, stock_map, industry_map = m.get_stock_list()
codes = [s['ts_code'] for s in stocks][:100]
print(f"\nScanning {len(codes)} stocks in {len(codes)//m.BATCH_SIZE + 1} batches")

csv_path = os.path.join(m.OUTPUT_DIR, f'top10_test_{m.TODAY}.csv')

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
print(f"\nDone in {elapsed:.0f}s, {total_hits} total hits")

final = m.read_existing_top20(csv_path)
print(f"Final top{len(final)}:")
for i, r in enumerate(final[:5]):
    print(f"  {i+1}. {r['name']}({r['code']}) score={r['score']} industry={r['industry']}")

# Chart top3
print(f"\nCharting top {m.TOP_CHART}...")
for i, item in enumerate(final[:m.TOP_CHART]):
    code = item['code']
    df = m.get_daily_plot(code)
    if not df or len(df) < 60:
        print(f"  [{i+1}] {code} skip - no data")
        continue
    patterns = m.detect_double_bottom(df)
    if not patterns:
        print(f"  [{i+1}] {code} skip - no pattern")
        continue
    best_p = max(patterns, key=lambda p: p['neck_price'])
    score, reasons = m.score_pattern(df, best_p)
    if score < 0:
        score = item['score']
        reasons = []
    svg_path = os.path.join(m.OUTPUT_DIR, f'test_top{i+1}_{code.split(".")[0]}_{item["name"]}_双底.svg')
    m.draw_svg_chart(df, best_p, score, reasons, item['name'], code, svg_path)
    print(f"  [{i+1}] {os.path.basename(svg_path)}")
    time.sleep(m.API_SLEEP)

print(f"\nOutput: {m.OUTPUT_DIR}")
print(f"CSV: {csv_path}")
