#!/usr/bin/env python3
"""双底V3 — 成功组 vs 失败组 特征对比"""
import os, re, numpy as np, tushare as ts, pandas as pd, time

BASE = "/mnt/d/Hermes_workspace/stock_research/4.Bottom_reversal/1.double_bottom/output"

with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    token = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read()).group(1)
pro = ts.pro_api(token)
today = pd.Timestamp.now().strftime('%Y%m%d')

# Collect predictions
preds = []; seen = set()
for d in sorted(os.listdir(BASE)):
    dpath = os.path.join(BASE, d)
    if not os.path.isdir(dpath) or '_data' in d or '_test' in d: continue
    for prefix in ['top30_双底突破_', 'top20_双底突破_']:
        p = os.path.join(dpath, f"{prefix}{d}.csv")
        if os.path.exists(p):
            df = pd.read_csv(p, encoding='utf-8-sig')
            for _, row in df.iterrows():
                code = str(row['代码']).strip()
                key = (code, str(row['突破日期']))
                if key in seen: continue
                seen.add(key)
                preds.append({
                    'code': code, 'name': str(row['名称']).strip(),
                    'score': float(row['评分']),
                    'left_price': float(row['左底价格']),
                    'right_price': float(row['右底价格']),
                    'neck_price': float(row['颈线价格']),
                    'target_price': float(row['目标价格']),
                    'break_date': str(row['突破日期']),
                    'days_since': int(row['突破天数']),
                    'gap': int(row['形态跨度']),
                    'post_pct': float(row['突破后涨幅%']),
                    'upside_pct': float(row['剩余空间%']),
                })
            break

print(f"共 {len(preds)} 条预测，拉取历史价格...")

# Fetch outcomes
reached = []; fell = []; done = 0
for p in preds:
    try:
        df = pro.daily(ts_code=p['code'], start_date=p['break_date'], end_date=today,
                       fields='trade_date,high,low')
    except: continue
    if df is None or df.empty: continue
    df = df.sort_values('trade_date')
    hit = float(df['high'].max()) >= p['target_price']
    drop = float(df['low'].min()) < p['right_price']
    if hit and not drop: reached.append(p)
    elif drop and not hit: fell.append(p)
    done += 1
    if done % 20 == 0: print(f"  {done}/{len(preds)}")
    time.sleep(0.05)

print(f"\n成功(触目标): {len(reached)} | 失败(破右底): {len(fell)}")

# Feature comparison
print(f"\n{'='*70}")
print(f"{'特征':<18} {'成功均值':>9} {'失败均值':>9} {'差值':>8} {'效应量':>7}")
print(f"{'-'*70}")

for fname, label in [
    ('days_since', '突破天数'),
    ('gap', '形态跨度(天)'),
    ('post_pct', '突破后涨幅%'),
    ('upside_pct', '剩余空间%'),
    ('score', 'V3总评分'),
]:
    rv = [p[fname] for p in reached]
    fv = [p[fname] for p in fell]
    rm, fm = np.mean(rv), np.mean(fv)
    diff = rm - fm
    pooled = np.sqrt((np.var(rv)+np.var(fv))/2)
    d = abs(diff)/pooled if pooled > 0 else 0
    bar = '█' * min(int(d*10), 30)
    print(f"{label:<18} {rm:>9.1f} {fm:>9.1f} {diff:>+8.1f} {d:>6.2f}  {bar}")

# Derived features
print()
for label, func in [
    ('价格距颈线%', lambda p: p['post_pct']),
    ('目标空间%', lambda p: (p['target_price']-p['neck_price'])/p['neck_price']*100),
    ('右底vs左底%', lambda p: (p['right_price']-p['left_price'])/p['left_price']*100),
    ('目标/颈线比', lambda p: p['target_price']/p['neck_price']),
]:
    rv = [func(p) for p in reached]
    fv = [func(p) for p in fell]
    rm, fm = np.mean(rv), np.mean(fv)
    diff = rm - fm
    pooled = np.sqrt((np.var(rv)+np.var(fv))/2)
    d = abs(diff)/pooled if pooled > 0 else 0
    bar = '█' * min(int(d*10), 30)
    print(f"{label:<18} {rm:>9.1f} {fm:>9.1f} {diff:>+8.1f} {d:>6.2f}  {bar}")

# Segmented hit rate for strongest features
print(f"\n{'='*70}")
print(f"突破天数分段 — 命中率:")
for lo, hi in [(0,3),(4,5),(6,10),(11,30)]:
    g = [p for p in preds if lo <= p['days_since'] <= hi]
    h = sum(1 for p in g if p in reached)
    f = sum(1 for p in g if p in fell)
    if g: print(f"  {lo}-{hi}天: {len(g)}条 命中{h}({h/len(g)*100:.0f}%) 失败{f}({f/len(g)*100:.0f}%)")

print(f"\n剩余空间分段 — 命中率:")
for lo, hi in [(8,12),(12,18),(18,25),(25,50)]:
    g = [p for p in preds if lo <= p['upside_pct'] <= hi]
    h = sum(1 for p in g if p in reached)
    f = sum(1 for p in g if p in fell)
    if g: print(f"  {lo}-{hi}%: {len(g)}条 命中{h}({h/len(g)*100:.0f}%) 失败{f}({f/len(g)*100:.0f}%)")

print(f"\n形态跨度分段 — 命中率:")
for lo, hi in [(10,19),(20,29),(30,39),(40,60)]:
    g = [p for p in preds if lo <= p['gap'] <= hi]
    h = sum(1 for p in g if p in reached)
    f = sum(1 for p in g if p in fell)
    if g: print(f"  {lo}-{hi}天: {len(g)}条 命中{h}({h/len(g)*100:.0f}%) 失败{f}({f/len(g)*100:.0f}%)")
