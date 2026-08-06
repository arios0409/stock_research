"""Quick test of double bottom scanner on 10 stocks"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Monkey-patch config before importing main module
import scan_double_bottom_v3 as m
m.BATCH_SIZE = 5
m.TOP_K = 5
m.TOP_CHART = 2
m.OUTPUT_DIR = os.path.join(m.SCRIPT_DIR, 'output', m.TODAY + '_test')
os.makedirs(m.OUTPUT_DIR, exist_ok=True)

# Run scan on first 10 stocks only
stocks, stock_map, industry_map = m.get_stock_list()
codes = [s['ts_code'] for s in stocks][:10]
print(f"Testing with {len(codes)} stocks: {codes}")

csv_path = os.path.join(m.OUTPUT_DIR, f'top5_test.csv')
batch_hits = m.scan_batch(codes, stock_map, industry_map, 0, len(codes))
print(f"Batch hits: {len(batch_hits)}")
for h in batch_hits:
    print(f"  {h['name']}({h['code']}) score={h['score']} industry={h['industry']}")

m.merge_and_save(batch_hits, csv_path, "test")
print(f"CSV at: {csv_path}")
