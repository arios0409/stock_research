"""Debug: test first 30 stocks with timing"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import everything except main
import scan_double_bottom_v3 as m

stocks, sm, im = m.get_stock_list()
codes = [s['ts_code'] for s in stocks]
print(f'Total: {len(codes)} stocks, first 30:')

for i, code in enumerate(codes[:30]):
    t0 = time.time()
    try:
        df = m.get_daily(code)
        elapsed = time.time() - t0
        n = len(df) if df else 0
        name = sm.get(code, '?')
        if df and len(df) >= 60:
            patterns = m.detect_double_bottom(df)
            pat_count = len(patterns)
        else:
            pat_count = 0
        print(f'  [{i+1:3d}] {code} {name}: api={elapsed:.2f}s rows={n} patterns={pat_count}')
    except Exception as e:
        elapsed = time.time() - t0
        print(f'  [{i+1:3d}] {code}: ERROR after {elapsed:.2f}s: {e}')
    time.sleep(m.API_SLEEP)
print('Done')
