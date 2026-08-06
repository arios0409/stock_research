#!/usr/bin/env python3
"""双底V4 逐日回测 5/6-5/20 → 检查7/3前达标率"""
import sys, os, time, re
from datetime import datetime, timedelta
import numpy as np, tushare as ts, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_BASE = os.path.join(BASE, 'output', 'backtest_v5')
os.makedirs(OUTPUT_BASE, exist_ok=True)

with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    token = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read()).group(1)
pro = ts.pro_api(token)

CHECK_DATE = '20260705'

dates = []
d = datetime(2026, 6, 15)
while d <= datetime(2026, 6, 15):
    dates.append(d.strftime('%Y%m%d'))
    d += timedelta(days=1)
d = datetime(2026, 7, 2)
while d <= datetime(2026, 7, 2):
    dates.append(d.strftime('%Y%m%d'))
    d += timedelta(days=1)

print(f"日期范围: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")
print(f"达标检查日: {CHECK_DATE}")
print(f"输出: {OUTPUT_BASE}")
print()

all_results = []

for day_idx, scan_date in enumerate(dates):
    print(f"\n{'='*60}")
    print(f"[{day_idx+1}/{len(dates)}] 扫描日期: {scan_date}")
    print(f"{'='*60}")
    
    # Override dates so get_daily() only fetches up to scan date (no future leak)
    m.TODAY = scan_date
    m.END_DATE = scan_date
    m.BACKTEST_MODE = True  # 回测不扣已达标分
    day_dir = os.path.join(OUTPUT_BASE, scan_date)
    os.makedirs(day_dir, exist_ok=True)
    m.OUTPUT_DIR = day_dir
    csv_path = os.path.join(day_dir, f'top20_双底_{scan_date}.csv')
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    
    # Get stock list
    print("  [1/3] 股票列表...")
    stocks, stock_map, industry_map = m.get_stock_list()
    codes = [s['ts_code'] for s in stocks]
    print(f"  {len(codes)} 只")
    
    # Scan
    batch_hits_total = 0
    
    batches = (len(codes) + m.BATCH_SIZE - 1) // m.BATCH_SIZE
    for bn in range(batches):
        bs = bn * m.BATCH_SIZE
        be = min(bs + m.BATCH_SIZE, len(codes))
        batch = codes[bs:be]
        hits = m.scan_batch(batch, stock_map, industry_map, bs, len(codes))
        batch_hits_total += len(hits)
        m.merge_and_save(hits, csv_path, f"B{bn+1}")
        if (bn+1) % 3 == 0:
            print(f"  进度 {be}/{len(codes)} 命中{batch_hits_total}")
    
    # Read top20
    top = m.read_existing_top20(csv_path)
    print(f"  完成: {batch_hits_total}命中, top{len(top)}")
    
    # Check outcomes
    for p in top:
        try:
            # 从突破日开始查（非扫描日），避免漏掉扫描前已达标的情况
            df = pro.daily(ts_code=p['code'], start_date=p['break_date'], end_date=CHECK_DATE,
                          fields='trade_date,high,low')
            if df is None or df.empty: continue
            df = df.sort_values('trade_date')
            hit_target = float(df['high'].max()) >= p['target_price']
            fell_bottom = float(df['low'].min()) < p['right_price']
            p['hit_target'] = hit_target
            p['fell_bottom'] = fell_bottom
        except:
            p['hit_target'] = False
            p['fell_bottom'] = False
        time.sleep(0.03)
    
    # Stats — 触及目标即成功，不管后面是否回落
    n = len(top)
    n_hit = sum(1 for p in top if p.get('hit_target'))
    n_fell = sum(1 for p in top if p.get('fell_bottom') and not p.get('hit_target'))
    
    result = {
        'scan_date': scan_date,
        'total': n,
        'hit_target': n_hit,
        'hit_rate': n_hit/n*100 if n > 0 else 0,
        'fell_rate': n_fell/n*100 if n > 0 else 0,
    }
    all_results.append(result)
    
    print(f"  达标率: {n_hit}/{n} ({result['hit_rate']:.0f}%)  破底率: {n_fell}/{n} ({result['fell_rate']:.0f}%)")
    
    # Save per-day CSV with outcome info
    out_df = pd.DataFrame([{
        '代码': p['code'],
        '名称': p['name'],
        '评分': p['score'],
        '目标价': p['target_price'],
        '达目标': p.get('hit_target', False),
        '破右底': p.get('fell_bottom', False),
    } for p in top])
    out_df.to_csv(os.path.join(day_dir, f'outcome_{scan_date}.csv'), 
                  index=False, encoding='utf-8-sig')

# Summary
print(f"\n{'='*70}")
print(f"汇总: 5/6-5/20 逐日双底V4扫描")
print(f"{'='*70}")
print(f"{'日期':<12} {'总数':>5} {'达标':>5} {'达标率':>8} {'破底率':>8}")
print(f"{'-'*45}")
for r in all_results:
    print(f"{r['scan_date']:<12} {r['total']:>5} {r['hit_target']:>5} {r['hit_rate']:>7.0f}% {r['fell_rate']:>7.0f}%")

avg_hit = np.mean([r['hit_rate'] for r in all_results])
avg_fell = np.mean([r['fell_rate'] for r in all_results])
print(f"{'平均':<12} {'':>5} {'':>5} {avg_hit:>7.0f}% {avg_fell:>7.0f}%")

# Save summary
pd.DataFrame(all_results).to_csv(os.path.join(OUTPUT_BASE, 'summary.csv'), 
                                  index=False, encoding='utf-8-sig')
print(f"\n汇总保存: {OUTPUT_BASE}/summary.csv")
