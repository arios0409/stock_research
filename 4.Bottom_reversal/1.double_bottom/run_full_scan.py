"""Full wrapper for v3 scanner - 全A股扫描"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

print("=" * 65, flush=True)
print("  双底突破形态扫描器 v3 (全量运行)", flush=True)
print(f"  日期: {m.TODAY}", flush=True)
print(f"  输出: {m.OUTPUT_DIR}", flush=True)
print("=" * 65, flush=True)

# [1] Get stocks
print("\n[1/4] 获取全A股股票列表...", flush=True)
stocks, stock_map, industry_map = m.get_stock_list()
codes = [s['ts_code'] for s in stocks]

sh = sum(1 for c in codes if c.endswith('.SH') and not c.startswith('688'))
sz = sum(1 for c in codes if c.endswith('.SZ') and not c.startswith('300'))
cyb = sum(1 for c in codes if c.startswith('300'))
kcb = sum(1 for c in codes if c.startswith('688'))
print(f"  共 {len(codes)} 只 | 沪市:{sh} 深市:{sz} 创业板:{cyb} 科创板:{kcb}", flush=True)

total_batches = (len(codes) + m.BATCH_SIZE - 1) // m.BATCH_SIZE
csv_path = os.path.join(m.OUTPUT_DIR, f'top{m.TOP_K}_双底突破_{m.TODAY}.csv')

# [2] Batch scan
print(f"\n[2/4] 分批扫描 (每批{m.BATCH_SIZE}只，共{total_batches}批)...", flush=True)
start_time = time.time()
total_hits = 0

for batch_no in range(total_batches):
    batch_start = batch_no * m.BATCH_SIZE
    batch_end = min(batch_start + m.BATCH_SIZE, len(codes))
    batch_codes = codes[batch_start:batch_end]
    
    label = f"第{batch_no + 1}/{total_batches}批 ({batch_start + 1}-{batch_end})"
    print(f"\n{'─' * 50}", flush=True)
    print(f"  {label}", flush=True)
    
    batch_hits = m.scan_batch(batch_codes, stock_map, industry_map, batch_start, len(codes))
    total_hits += len(batch_hits)
    print(f"  本批命中: {len(batch_hits)} 个形态 (评分>={m.MIN_SCORE})", flush=True)
    
    m.merge_and_save(batch_hits, csv_path, label)
    
    elapsed = time.time() - start_time
    done = batch_end
    remaining = len(codes) - done
    if done > 0:
        eta = (elapsed / done) * remaining
        print(f"  进度: {done}/{len(codes)} | 累计命中:{total_hits} | ETA: {eta / 60:.0f}分钟", flush=True)

elapsed = time.time() - start_time
print(f"\n{'=' * 50}", flush=True)
print(f"  扫描完成! 总耗时: {elapsed / 60:.1f}分钟", flush=True)
print(f"  累计命中: {total_hits}个形态", flush=True)

# Read final top20
final_top20 = m.read_existing_top20(csv_path)
if not final_top20:
    print("\n  未发现任何符合条件的双底形态，退出。", flush=True)
    sys.exit(0)

# [3] Chart top5
print(f"\n[3/4] 为top5生成SVG图表...", flush=True)
top5 = final_top20[:m.TOP_CHART]

for i, item in enumerate(top5):
    code = item['code']
    name = item['name']
    print(f"  [{i + 1}] {code} {name} (评分:{item['score']})", flush=True)
    
    df_plot = m.get_daily_plot(code)
    if not df_plot or len(df_plot) < 60:
        print(f"      画图数据不足，跳过", flush=True)
        continue
    
    patterns = m.detect_double_bottom(df_plot)
    if not patterns:
        print(f"      未检测到形态，跳过", flush=True)
        continue
    
    best_p = max(patterns, key=lambda p: p['neck_price'])
    score, reasons = m.score_pattern(df_plot, best_p)
    if score < 0:
        score = item['score']
        reasons = []
    
    svg_path = os.path.join(m.OUTPUT_DIR,
                            f'top{i + 1}_{code.split(".")[0]}_{name}_双底.svg')
    m.draw_svg_chart(df_plot, best_p, score, reasons, name, code, svg_path)
    print(f"      -> {os.path.basename(svg_path)}", flush=True)
    time.sleep(m.API_SLEEP)

# [4] Summary
print(f"\n[4/4] 最终结果", flush=True)
print("=" * 65, flush=True)
print(f"  {'排名':<5} {'代码':<12} {'名称':<10} {'评分':<5} {'行业':<12} {'突破日':<12} {'剩余空间':<8}", flush=True)
print("  " + "-" * 65, flush=True)
for i, item in enumerate(final_top20):
    code_short = item['code'].split('.')[0]
    print(f"  {i + 1:<5} {code_short:<12} {item['name']:<10} {item['score']:<5} "
          f"{item.get('industry', '')[:10]:<12} {item['break_date']:<12} {item['upside_pct']:<8.1f}%", flush=True)

svg_files = [f for f in os.listdir(m.OUTPUT_DIR) if f.endswith('.svg') and not f.startswith('test_')]
print(f"\n  输出目录: {m.OUTPUT_DIR}", flush=True)
print(f"  CSV: top{m.TOP_K}_双底突破_{m.TODAY}.csv ({len(final_top20)}条)", flush=True)
print(f"  SVG: {len(svg_files)}张图表", flush=True)
print(f"  耗时: {elapsed / 60:.1f}分钟", flush=True)
print("=" * 65, flush=True)
