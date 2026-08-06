#!/usr/bin/env python3
"""双底V3评分回测 — 查历史是否触及目标/跌破双底"""
import os, re, numpy as np, tushare as ts, pandas as pd, time
from datetime import datetime

BASE = "/mnt/d/Hermes_workspace/stock_research/4.Bottom_reversal/1.double_bottom/output"

with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    m = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read())
token = m.group(1)
pro = ts.pro_api(token)

# Collect predictions
csv_files = []
for d in sorted(os.listdir(BASE)):
    dpath = os.path.join(BASE, d)
    if not os.path.isdir(dpath): continue
    if '_data' in d or '_test' in d: continue
    for prefix in ['top30_双底突破_', 'top20_双底突破_']:
        csv_path = os.path.join(dpath, f"{prefix}{d}.csv")
        if os.path.exists(csv_path):
            csv_files.append((d, csv_path))
            break

print(f"找到 {len(csv_files)} 个V3扫描: {[d for d,_ in csv_files]}")

all_preds = []
seen = set()
for scan_date, csv_path in csv_files:
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
        for _, row in df.iterrows():
            code = str(row['代码']).strip()
            key = (code, str(row['突破日期']))
            if key in seen: continue
            seen.add(key)
            all_preds.append({
                'scan_date': scan_date, 'code': code,
                'name': str(row['名称']).strip(),
                'score': float(row['评分']),
                'right_price': float(row['右底价格']),
                'target_price': float(row['目标价格']),
                'break_date': str(row['突破日期']),
            })
    except Exception as e:
        print(f"  读取 {csv_path} 失败: {e}")

print(f"共 {len(all_preds)} 条独立预测")

# Fetch history for each stock and check outcomes
today = datetime.now().strftime('%Y%m%d')
reached = []; fell_bottom = []; both = []; neither = []
done = 0

for p in all_preds:
    code = p['code']
    try:
        df = pro.daily(ts_code=code, start_date=p['break_date'], end_date=today,
                       fields='trade_date,high,low,close')
    except:
        continue
    if df is None or df.empty:
        continue
    
    df = df.sort_values('trade_date')
    max_high = float(df['high'].max())
    min_low = float(df['low'].min())
    
    hit_target = max_high >= p['target_price']
    hit_bottom = min_low < p['right_price']
    
    p['hit_target'] = hit_target
    p['hit_bottom'] = hit_bottom
    
    if hit_target and hit_bottom:
        both.append(p)
    elif hit_target:
        reached.append(p)
    elif hit_bottom:
        fell_bottom.append(p)
    else:
        neither.append(p)
    
    done += 1
    if done % 20 == 0:
        print(f"  进度 {done}/{len(all_preds)}")
    time.sleep(0.05)

# Combine reached+both as "ever reached target"
reached_all = reached + both
fell_all = fell_bottom + both

print(f"\n{'='*60}")
print(f"  分类结果 ({len(all_preds)}条预测):")
print(f"  曾触及目标位:      {len(reached_all)} ({len(reached_all)/max(len(all_preds),1)*100:.1f}%)")
print(f"  曾跌破右底:        {len(fell_all)} ({len(fell_all)/max(len(all_preds),1)*100:.1f}%)")
print(f"  两者都发生过:      {len(both)}")
print(f"  都没发生:          {len(neither)}")
print(f"{'='*60}")

# Score analysis
for label, group in [
    ('✅曾触及目标', reached_all),
    ('❌曾跌破右底', fell_all),
    ('➡都没发生', neither),
]:
    if not group: continue
    scores = [p['score'] for p in group]
    print(f"\n{label} ({len(group)}条):")
    print(f"  评分: 均值{np.mean(scores):.0f} 中位{np.median(scores):.0f} 最高{np.max(scores):.0f} 最低{np.min(scores):.0f}")
    bins = [40, 45, 50, 55, 60, 65, 70, 75, 80, 100]
    hist, _ = np.histogram(scores, bins=bins)
    parts = []
    for i, h in enumerate(hist):
        if h > 0:
            parts.append(f"{bins[i]}-{bins[i+1]}:{h}")
    print(f"  分布: {' | '.join(parts)}")

# Score decile analysis
print(f"\n{'='*60}")
print(f"  评分分位命中率:")
for lo in [40, 50, 55, 60, 65, 70, 75]:
    hi = 100
    group = [p for p in all_preds if p['score'] >= lo]
    if not group: continue
    hit = sum(1 for p in group if p['hit_target'])
    print(f"  评分≥{lo}: {len(group)}条, 命中{hit}条 ({hit/len(group)*100:.0f}%)")

# Show best/worst examples
print(f"\n{'='*60}")
print(f"  高分但失败的样本 (评分≥70却跌破右底):")
bad = sorted([p for p in fell_all if p['score'] >= 70], key=lambda x: -x['score'])[:5]
for p in bad:
    print(f"  {p['name']}({p['code']}) 评分{p['score']:.0f} 右底¥{p['right_price']:.1f} 目标¥{p['target_price']:.1f}")

print(f"\n  低分但成功的样本 (评分≤55却触及目标):")
good = sorted([p for p in reached_all if p['score'] <= 55], key=lambda x: x['score'])[:5]
for p in good:
    print(f"  {p['name']}({p['code']}) 评分{p['score']:.0f} 目标¥{p['target_price']:.1f}")
