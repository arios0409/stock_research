#!/usr/bin/env python3
"""V3 vs V4 评分回测对比 — 6月历史数据"""
import os, re, numpy as np, tushare as ts, pandas as pd, time, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_double_bottom_v3 as m

BASE = "/mnt/d/Hermes_workspace/stock_research/4.Bottom_reversal/1.double_bottom/output"
with open("/mnt/d/Hermes_workspace/stock_research/dapan_scan_auto.py") as f:
    token = re.search(r'TUSHARE_TOKEN\s*=\s*"(.+?)"', f.read()).group(1)
pro = ts.pro_api(token)
today = pd.Timestamp.now().strftime('%Y%m%d')

# Collect June predictions
preds = []; seen = set()
for d in sorted(os.listdir(BASE)):
    if not d.startswith('202606'): continue  # June only
    dpath = os.path.join(BASE, d)
    if not os.path.isdir(dpath) or '_test' in d: continue
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
                    'scan_date': d, 'code': code,
                    'name': str(row['名称']).strip(),
                    'score_v3': float(row['评分']),
                    'left_price': float(row['左底价格']),
                    'right_price': float(row['右底价格']),
                    'neck_price': float(row['颈线价格']),
                    'target_price': float(row['目标价格']),
                    'break_date': str(row['突破日期']),
                    'gap': int(row['形态跨度']),
                    'days_since': int(row['突破天数']),
                })
            break

print(f"6月共 {len(preds)} 条预测")

# Fetch outcomes + V4 scores
reached_v4 = []; fell_v4 = []
v3_scores_reached = []; v3_scores_fell = []
v4_scores_reached = []; v4_scores_fell = []
done = 0

for p in preds:
    code = p['code']
    try:
        df_hist = pro.daily(ts_code=code, start_date=p['break_date'], end_date=today,
                            fields='trade_date,high,low')
    except: continue
    if df_hist is None or df_hist.empty: continue
    
    df_hist = df_hist.sort_values('trade_date')
    hit = float(df_hist['high'].max()) >= p['target_price']
    drop = float(df_hist['low'].min()) < p['right_price']
    
    # Get V4 score by re-running detection
    try:
        df_full = m.get_daily_plot(code)
        if df_full and len(df_full) >= 60:
            pats = m.detect_double_bottom(df_full)
            score_v4 = -1
            for pat in pats:
                if pat.get('break_date', '') == p['break_date']:
                    sc, _ = m.score_pattern(df_full, pat)
                    score_v4 = sc
                    break
            p['score_v4'] = max(score_v4, 0)
    except:
        p['score_v4'] = p['score_v3']  # fallback
    
    if hit and not drop:
        reached_v4.append(p)
        v3_scores_reached.append(p['score_v3'])
        v4_scores_reached.append(p['score_v4'])
    elif drop and not hit:
        fell_v4.append(p)
        v3_scores_fell.append(p['score_v3'])
        v4_scores_fell.append(p['score_v4'])
    
    done += 1
    if done % 20 == 0: print(f"  {done}/{len(preds)}")
    time.sleep(0.08)

print(f"\n成功(触目标): {len(reached_v4)} | 失败(破右底): {len(fell_v4)}")

# Compare V3 vs V4
print(f"\n{'='*65}")
print(f"{'':<20} {'V3旧评分':>12} {'V4新评分':>12} {'改善':>8}")
print(f"{'-'*65}")

# Success group
r_v3, r_v4 = np.mean(v3_scores_reached), np.mean(v4_scores_reached)
f_v3, f_v4 = np.mean(v3_scores_fell), np.mean(v4_scores_fell)

print(f"{'成功组均值':<20} {r_v3:>12.1f} {r_v4:>12.1f} {r_v4-r_v3:>+8.1f}")
print(f"{'失败组均值':<20} {f_v3:>12.1f} {f_v4:>12.1f} {f_v4-f_v3:>+8.1f}")
print(f"{'成功-失败差':<20} {r_v3-f_v3:>12.1f} {r_v4-f_v4:>12.1f} {(r_v4-f_v4)-(r_v3-f_v3):>+8.1f}")
print()

# Effect size
def cohens_d(a, b):
    pooled = np.sqrt((np.var(a)+np.var(b))/2)
    return abs(np.mean(a)-np.mean(b))/pooled if pooled > 0 else 0

print(f"V3效应量: {cohens_d(v3_scores_reached, v3_scores_fell):.2f}")
print(f"V4效应量: {cohens_d(v4_scores_reached, v4_scores_fell):.2f}")

# Decile analysis
print(f"\n{'='*65}")
print(f"{'评分分位':<12} {'V3命中率':>10} {'V4命中率':>10} {'提升':>8}")
print(f"{'-'*65}")
for lo in [40, 45, 50, 55, 60]:
    for ver, scores_key in [('V3','score_v3'), ('V4','score_v4')]:
        g = [p for p in preds if p[scores_key] >= lo]
        if not g: continue
        h = sum(1 for p in g if p in reached_v4)
        if ver == 'V3':
            v3_hit = f"{h}/{len(g)}({h/len(g)*100:.0f}%)"
        else:
            v4_hit = f"{h}/{len(g)}({h/len(g)*100:.0f}%)"
    print(f"≥{lo:<11} {v3_hit:>10} {v4_hit:>10}")

# Individual examples
print(f"\n{'='*65}")
print(f"V4高分且成功 (top 3):")
for p in sorted(reached_v4, key=lambda x: -x['score_v4'])[:3]:
    print(f"  {p['name']}({p['code']}) V3={p['score_v3']:.0f}→V4={p['score_v4']:.0f} 目标¥{p['target_price']:.1f}")

print(f"\nV4高分但失败 (top 3):")
for p in sorted(fell_v4, key=lambda x: -x['score_v4'])[:3]:
    print(f"  {p['name']}({p['code']}) V3={p['score_v3']:.0f}→V4={p['score_v4']:.0f} 右底¥{p['right_price']:.1f}")

print(f"\nV4低分但成功 (bottom 3):")
for p in sorted(reached_v4, key=lambda x: x['score_v4'])[:3]:
    print(f"  {p['name']}({p['code']}) V3={p['score_v3']:.0f}→V4={p['score_v4']:.0f} 目标¥{p['target_price']:.1f}")
