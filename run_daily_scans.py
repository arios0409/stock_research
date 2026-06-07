"""
驱动脚本：调原始扫描器，逐日扫描 2026-04-15 ~ 2026-05-10
每天三个扫描器并行跑，完成后汇总去重 + 胜率统计
"""
import os, sys, time, csv, json, urllib.request
from datetime import datetime, timedelta
from collections import defaultdict

BASE = '/mnt/d/Hermes_workspace/stock_research'
SCANNERS = {
    '双底': os.path.join(BASE, '4.Bottom_reversal/1.double_bottom/double_bottom_scanner.py'),
    '三角收敛': os.path.join(BASE, '3.Rising_continuation/1.Triangle_oscillation/triangle_scanner.py'),
    '牛旗': os.path.join(BASE, '3.Rising_continuation/2.Flag_continuation/bull_flag_scanner.py'),
}

TUSHARE_TOKEN='026586...ad60'
API_URL = 'http://api.tushare.pro'
TARGET_DEADLINE = datetime.now().strftime('%Y%m%d')
SCAN_START = '20260401'
SCAN_END = '20260510'

date_range = []
d = datetime(2026, 4, 15)
while d <= datetime(2026, 5, 10):
    date_range.append(d.strftime('%Y%m%d'))
    d += timedelta(days=1)

print(f"扫描日期: {date_range[0]} ~ {date_range[-1]} ({len(date_range)} 天)")
print(f"目标截止: {TARGET_DEADLINE} (今天)")
print(f"扫描器: {list(SCANNERS.keys())}")
print()

# ============================================================
# Step 1: Run scanners for each date
# ============================================================
def set_end_date(script_path, end_date):
    """Modify END_DATE in a scanner script"""
    with open(script_path, 'r') as f:
        content = f.read()
    # Find and replace END_DATE
    import re
    content = re.sub(r"END_DATE\s*=\s*'[^']*'", f"END_DATE = '{end_date}'", content)
    with open(script_path, 'w') as f:
        f.write(content)

def run_scanner(scanner_path, workdir, timeout=600):
    """Run a scanner and return (success, output)"""
    import subprocess
    try:
        result = subprocess.run(
            ['python3', scanner_path],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)

import concurrent.futures

total = len(date_range)
for di, end_date in enumerate(date_range):
    print(f"\n{'='*60}")
    print(f"[{di+1}/{total}] END_DATE={end_date}")
    print(f"{'='*60}")
    
    # Set END_DATE in all scanners
    for name, path in SCANNERS.items():
        set_end_date(path, end_date)
        print(f"  {name}: END_DATE={end_date} ✓")
    
    # Run all 3 scanners in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for name, path in SCANNERS.items():
            workdir = os.path.dirname(path)
            futures[executor.submit(run_scanner, path, workdir)] = name
        
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            success, output = future.result()
            status = "✓" if success else "✗"
            # Print last few lines
            lines = output.strip().split('\n')
            summary = '\n'.join(lines[-5:]) if lines else '(no output)'
            print(f"  [{status}] {name}")
            print(f"      {summary[:200]}")

print(f"\n{'='*60}")
print("全部扫描完成!")

# ============================================================
# Step 2: Collect all patterns from CSVs
# ============================================================
print(f"\n[汇总] 收集所有扫描结果...")

patterns = []

for end_date in date_range:
    # Double bottom CSV
    db_csv = os.path.join(BASE, f'4.Bottom_reversal/1.double_bottom/{end_date}_data/results_{end_date}.csv')
    if os.path.exists(db_csv):
        with open(db_csv, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                bd = row['break_date']
                if SCAN_START <= bd <= SCAN_END:
                    patterns.append({
                        'scanner': '双底', 'code': row['code'], 'name': row['name'],
                        'break_date': bd, 'target': float(row['target']),
                        'score': int(row.get('score', 0)),
                    })
    
    # Triangle CSV
    tri_csv = os.path.join(BASE, f'3.Rising_continuation/1.Triangle_oscillation/{end_date}_data/top30_三角收敛上涨中继.csv')
    if os.path.exists(tri_csv):
        with open(tri_csv, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                bd = row['突破日期']
                if SCAN_START <= bd <= SCAN_END:
                    patterns.append({
                        'scanner': '三角收敛', 'code': row['代码'], 'name': row['名称'],
                        'break_date': bd, 'target': float(row['量度目标价']),
                        'score': int(float(row.get('综合得分', 0))),
                    })
    
    # Bull flag CSV
    flag_csv = os.path.join(BASE, f'3.Rising_continuation/2.Flag_continuation/{end_date}_data/results_{end_date}.csv')
    if os.path.exists(flag_csv):
        with open(flag_csv, 'r', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                bd = row['break_date']
                if SCAN_START <= bd <= SCAN_END:
                    patterns.append({
                        'scanner': '牛旗', 'code': row['code'], 'name': row['name'],
                        'break_date': bd, 'target': float(row['target']),
                        'score': int(row.get('score', 0)),
                    })

# Global dedup
code_best = {}
priority = {'双底': 3, '三角收敛': 2, '牛旗': 1}
for p in patterns:
    k = p['code']
    pp = priority.get(p['scanner'], 0)
    if k not in code_best or pp > priority.get(code_best[k]['scanner'], 0) or \
       (pp == priority.get(code_best[k]['scanner'], 0) and p['score'] > code_best[k]['score']):
        code_best[k] = p

patterns = list(code_best.values())
print(f"去重后: {len(patterns)} 只")
by_s = defaultdict(int)
for p in patterns: by_s[p['scanner']] += 1
for s, c in sorted(by_s.items()): print(f"  {s}: {c} 只")

# ============================================================
# Step 3: Backtest — check target reached by today
# ============================================================
print(f"\n[回测] 检查目标达成 (截止{TARGET_DEADLINE})...")

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields: payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        return result.get('data', {}) if result.get('code') == 0 else None
    except: return None

results = []
for i, p in enumerate(patterns):
    code, bd, target = p['code'], p['break_date'], p['target']
    result = api_call('daily', ts_code=code, start_date=bd, end_date=TARGET_DEADLINE)
    
    max_high, max_date, reached, status = 0, '', False, 'no_data'
    if result and 'items' in result and result['items']:
        fields = result['fields']
        for row_data in result['items']:
            d = dict(zip(fields, row_data))
            high = float(d.get('high', 0))
            if high > max_high: max_high = high; max_date = d['trade_date']
        reached = max_high >= target
        status = 'hit' if reached else 'miss'
    
    icon = '✅' if reached else ('❌' if status == 'miss' else '⚠')
    pct = (max_high - target) / target * 100 if max_high else 0
    print(f"[{i+1}/{len(patterns)}] {icon} {p['scanner']} {p['name']}({code}) "
          f"突破:{bd} 目标:{target:.2f} 最高:{max_high:.2f} {max_date} {pct:+.1f}%")
    
    p['reached'] = reached; p['max_price'] = max_high
    p['max_date'] = max_date; p['status'] = status
    results.append(p)
    time.sleep(0.13)

# ============================================================
# Step 4: Statistics
# ============================================================
print(f"\n{'='*65}")
valid = [r for r in results if r['status'] != 'no_data']
hit = [r for r in valid if r['reached']]
miss = [r for r in valid if not r['reached']]

if valid:
    wr = len(hit) / len(valid) * 100
    print(f"  ╔══════════════════════════════════════╗")
    print(f"  ║  总样本: {len(valid):>4}  达成: {len(hit):>3}  未达成: {len(miss):>3}  胜率: {wr:>5.1f}%  ║")
    print(f"  ╚══════════════════════════════════════╝")

for sn in ['双底', '三角收敛', '牛旗']:
    sv = [r for r in results if r['scanner'] == sn and r['status'] != 'no_data']
    sh = [r for r in sv if r['reached']]
    if sv: print(f"\n  【{sn}】{len(sv)}样本 | 达成{len(sh)} | 胜率{len(sh)/len(sv)*100:.1f}%")

rising = [r for r in results if r['scanner'] in ('三角收敛', '牛旗') and r['status'] != 'no_data']
rising_hit = [r for r in rising if r['reached']]
if rising: print(f"  【上升中继合计】{len(rising)}样本 | 达成{len(rising_hit)} | 胜率{len(rising_hit)/len(rising)*100:.1f}%")

print(f"\n达成 ✅ :")
for r in sorted(hit, key=lambda x: x.get('max_price',0)/x['target'], reverse=True):
    pct = (r['max_price']-r['target'])/r['target']*100
    print(f"  {r['scanner']} {r['name']}({r['code']}) 突破:{r['break_date']} "
          f"目标:{r['target']:.2f} 最高:{r['max_price']:.2f}({r['max_date']}) +{pct:.1f}%")

print(f"\n未达成 ❌ :")
for r in sorted(miss, key=lambda x: (x.get('max_price',0)-x['target'])/x['target'], reverse=True):
    pct = (r['max_price']-r['target'])/r['target']*100
    print(f"  {r['scanner']} {r['name']}({r['code']}) 突破:{r['break_date']} "
          f"目标:{r['target']:.2f} 最高:{r['max_price']:.2f}({r['max_date']}) {pct:+.1f}%")

# Save
out_dir = os.path.join(BASE, 'backtest_results')
os.makedirs(out_dir, exist_ok=True)
detail_csv = os.path.join(out_dir, f'winrate_{datetime.now().strftime("%Y%m%d")}.csv')
with open(detail_csv, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['scanner','code','name','break_date','target','score','reached','max_price','max_date','gap_pct'])
    for r in results:
        gap = (r.get('max_price',0)-r['target'])/r['target']*100 if r.get('max_price') else 0
        w.writerow([r['scanner'],r['code'],r['name'],r['break_date'],f"{r['target']:.2f}",
                    r['score'],'YES' if r.get('reached') else 'NO',
                    f"{r.get('max_price',0):.2f}" if r.get('max_price') else '',
                    r.get('max_date',''),f"{gap:.1f}"])
print(f"\n详细结果: {detail_csv}")
print("="*65)
