"""三角收敛扫描 v3 — 分批打擂台"""
import sys, os, time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "triangle_full",
    os.path.join(SCRIPT_DIR, "triangle_scanner_full.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Override config
m.SCAN_WINDOW_MONTHS = 4  # 4个月内
TODAY = datetime.now().strftime('%Y%m%d')
m.END_DATE = TODAY  
m.PLOT_END_DATE = TODAY

OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'output', TODAY)
os.makedirs(OUTPUT_DIR, exist_ok=True)

BATCH_SIZE = 500
TOP_K = 20
TOP_CHART = 5
MIN_SCORE = 40  # 三角收敛评分阈值

CSV_COLS = ['排名','代码','名称','行业','评分','三角开始','三角结束',
            '突破日期','当前价格','目标价格','突破后涨幅%','目标空间%','持续时间']

def read_csv(path):
    if not os.path.exists(path): return []
    rows = []
    with open(path, 'r', encoding='utf-8-sig') as f:
        for line in list(f.readlines())[1:]:
            p = line.strip().split(',')
            if len(p) < 12: continue
            try:
                rows.append({'code':p[1],'name':p[2],'industry':p[3],'score':float(p[4]),
                    'ts_date':p[5],'te_date':p[6],'bk_date':p[7],
                    'cp':float(p[8]),'tgt':float(p[9]),'ag':float(p[10]),'up':float(p[11])})
            except: continue
    return rows

def write_csv(recs, path):
    s = sorted(recs, key=lambda x:-x['score'])[:TOP_K]
    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write(','.join(CSV_COLS)+'\n')
        for i,r in enumerate(s):
            f.write(f"{i+1},{r['code']},{r['name']},{r.get('industry','')},{r['score']:.0f},"
                    f"{r['ts_date']},{r['te_date']},{r['bk_date']},{r['cp']},{r['tgt']},"
                    f"{r['ag']},{r['up']}\n")
    return s

def merge_save(new, path, label):
    old = read_csv(path)
    seen = set(); merged = []
    for r in old:
        k = (r['code'], r.get('ts_date',''))
        if k not in seen: seen.add(k); merged.append(r)
    for r in new:
        k = (r['code'], r.get('ts_date',''))
        if k not in seen: seen.add(k); merged.append(r)
    # 每只股票只保留最高分的形态
    best = {}
    for r in merged:
        c = r['code']
        if c not in best or r['score'] > best[c]['score']:
            best[c] = r
    merged = list(best.values())
    top = write_csv(merged, path)
    print(f"  [擂台] 旧{len(old)}+新{len(new)}->合并{len(merged)}->top20", flush=True)
    for i,r in enumerate(top[:5]):
        print(f"  {i+1}. {r['name']}({r['code']}) {r['score']:.0f}分 {r.get('industry','?')} 空间{r['up']:.1f}%", flush=True)
    return top

# ── Main ──
print("="*65, flush=True)
print("  三角收敛上涨中继扫描 v3", flush=True)
print(f"  {TODAY} | {OUTPUT_DIR}", flush=True)
print("="*65, flush=True)

print("\n[1/3] 股票列表...", flush=True)
stocks = m.get_stock_list()
imap = {s['ts_code']: s.get('industry','') for s in stocks}
nmap = {s['ts_code']: s.get('name', s['ts_code']) for s in stocks}
codes = [s['ts_code'] for s in stocks if 'ST' not in s.get('name','') and '退' not in s.get('name','')]
print(f"  {len(codes)} 只", flush=True)

# 最早允许的突破日期 (END_DATE - SCAN_WINDOW_MONTHS×30)
from datetime import timedelta
end_dt = datetime.strptime(TODAY, '%Y%m%d')
earliest_dt = end_dt - timedelta(days=m.SCAN_WINDOW_MONTHS * 30)
EARLIEST_DATE = earliest_dt.strftime('%Y%m%d')
print(f"  突破日最早: {EARLIEST_DATE} (距今{m.SCAN_WINDOW_MONTHS}个月)", flush=True)

nb = (len(codes)+BATCH_SIZE-1)//BATCH_SIZE
csv_path = os.path.join(OUTPUT_DIR, f'top{TOP_K}_三角收敛_{TODAY}.csv')

print(f"\n[2/3] 分批扫描 ({nb}批)...", flush=True)
t0 = time.time(); total = 0

for bn in range(nb):
    bs = bn*BATCH_SIZE; be = min(bs+BATCH_SIZE, len(codes))
    print(f"\n{'─'*50}\n  第{bn+1}/{nb}批 ({bs+1}-{be})", flush=True)
    
    hits = []
    for j, code in enumerate(codes[bs:be]):
        try:
            df = m.get_daily_data(code, start_date=m.START_DATE, end_date=TODAY)
            if not df or len(df)<60: continue
            pats = m.detect_triangle(df, len(df)-1)
            name = nmap.get(code, code); ind = imap.get(code,'')
            for p in pats:
                # 突破日必须在最近N个月内
                if p.get('bk_date', '') < EARLIEST_DATE:
                    continue
                score, reasons = m.score_and_filter(df, p)
                if score < MIN_SCORE: continue
                hits.append({'code':code,'name':name,'industry':ind,'score':score,
                    'ts_date':p['ts_date'],'te_date':p['te_date'],
                    'bk_date':p.get('bk_date',''),'cp':round(p['cp'],2),
                    'tgt':round(p['tgt'],2),'ag':round(p['ag'],1),'up':round(p['up'],1),
                    '_p':p,'_reasons':reasons})
            time.sleep(0.12)
        except: continue
    
    total += len(hits)
    print(f"  命中: {len(hits)} (累计{total})", flush=True)
    merge_save(hits, csv_path, f"第{bn+1}/{nb}批")
    
    et = time.time()-t0
    if be>0:
        eta = (et/be)*(len(codes)-be)
        print(f"  进度: {be}/{len(codes)} | ETA: {eta/60:.0f}分钟", flush=True)

et = time.time()-t0
print(f"\n  完成! {et/60:.1f}分钟, {total}命中", flush=True)

final = read_csv(csv_path)
if not final:
    print("  无结果", flush=True); sys.exit(0)

print(f"\n[3/3] top5 SVG...", flush=True)
for i, item in enumerate(final[:TOP_CHART]):
    code = item['code']
    print(f"  [{i+1}] {code} ({item['score']:.0f}分)", flush=True)
    df = m.get_daily_data(code, start_date='20240501', end_date=TODAY)
    if not df or len(df)<60:
        print("    数据不足", flush=True); continue
    pats = m.detect_triangle(df, len(df)-1)
    if pats:
        # 对所有形态评分，取4个月窗口内最高分的（而非第一个）
        best_pat, best_sc, best_rs = None, -999, []
        for p in pats:
            if p.get('bk_date', '') < EARLIEST_DATE:
                continue
            sc, rs = m.score_and_filter(df, p)
            if sc > best_sc:
                best_sc, best_pat, best_rs = sc, p, rs
        if best_pat:
            best, sc, rs = best_pat, best_sc, best_rs
        else:
            best = item.get('_p',{}); sc = item['score']; rs = item.get('_reasons',[])
    else:
        best = item.get('_p',{}); sc = item['score']; rs = item.get('_reasons',[])
    svg = os.path.join(OUTPUT_DIR, f'top{i+1}_{code.split(".")[0]}_{item["name"]}_三角收敛.svg')
    m.draw_svg_chart(df, best, sc, rs, item['name'], code, svg)
    print(f"    -> {os.path.basename(svg)}", flush=True)
    time.sleep(0.12)

print(f"\n  输出: {OUTPUT_DIR}", flush=True)
print(f"  CSV: {os.path.basename(csv_path)}", flush=True)
