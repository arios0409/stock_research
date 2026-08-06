"""V3双底扫描 — 按指定日期依次扫描"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for scan_date in ['20260706', '20260707']:
    # 重新加载模块（刷新日期参数）
    import importlib
    if 'scan_double_bottom_v3' in sys.modules:
        del sys.modules['scan_double_bottom_v3']
    
    import scan_double_bottom_v3 as m
    
    # 覆盖日期
    m.TODAY = scan_date
    m.END_DATE = scan_date
    # DB_START 往前推1年
    from datetime import datetime, timedelta
    dt = datetime.strptime(scan_date, '%Y%m%d')
    m.DB_START = (dt - timedelta(days=365)).strftime('%Y%m%d')
    m.OUTPUT_DIR = os.path.join(m.SCRIPT_DIR, 'output', scan_date)
    os.makedirs(m.OUTPUT_DIR, exist_ok=True)
    
    print("=" * 65)
    print(f"  V3双底扫描 - {scan_date}")
    print(f"  DB_START={m.DB_START} END_DATE={m.END_DATE}")
    print("=" * 65)
    
    t0 = time.time()
    stocks, stock_map, industry_map = m.get_stock_list()
    codes = [s['ts_code'] for s in stocks]
    print(f"全A股: {len(codes)} 只\n")
    
    csv_path = os.path.join(m.OUTPUT_DIR, f'top{m.TOP_K}_双底突破_{scan_date}.csv')
    
    total_hits = 0
    for batch_no in range(0, len(codes), m.BATCH_SIZE):
        batch_codes = codes[batch_no:batch_no + m.BATCH_SIZE]
        label = f"batch {batch_no//m.BATCH_SIZE + 1}"
        hits = m.scan_batch(batch_codes, stock_map, industry_map, batch_no, len(codes))
        total_hits += len(hits)
        m.merge_and_save(hits, csv_path, label)
    
    elapsed = time.time() - t0
    final = m.read_existing_top20(csv_path)
    print(f"\n{scan_date} 完成: {elapsed/60:.1f}分钟, {len(final)} 只")
    for i, r in enumerate(final):
        print(f"  {i+1}. {r['name']}({r['code']}) 评分{r['score']} 突破日{r['break_date']} 行业{r.get('industry','')}")
    print()
