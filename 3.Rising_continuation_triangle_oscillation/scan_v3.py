#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
沪深300 三角收敛上涨中继形态扫描 v3
- 筛选时间: 用户指定范围 (2025-11 ~ 2026-05-13)
- 画图范围: 2年日K线 (2024-05 ~ 2026-05)
- 图中标注上榜理由
"""

import tushare as ts
import pandas as pd
import numpy as np
import json, os, time, warnings

import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager as fm

# Add Windows Chinese fonts
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei'] + plt.rcParams['font.sans-serif']
plt.rcParams['axes.unicode_minus'] = False

warnings.filterwarnings('ignore')

OUT = '/mnt/e/Hermes_workspace/Project/1.stock_research/1.上升中继三角震荡'
TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

# 时间范围
SCAN_START = '20251101'   # 形态筛选起始
SCAN_END   = '20260513'   # 形态筛选截止（含）
CHART_START = '20240501'  # 图表显示起始（2年）
CHART_END   = '20260513'  # 图表显示截止
REF_DATE = pd.Timestamp('2026-05-13')

# 加载名称映射
with open(f'{OUT}/all_names.json') as f:
    NAMES = json.load(f)

# 加载沪深300成分股
with open(f'{OUT}/hs300_stocks.json') as f:
    STOCK_LIST = json.load(f)

print("="*70)
print("  沪深300 三角收敛上涨中继形态扫描 v3")
print(f"  筛选时间: 2025-11 ~ 2026-05-13")
print(f"  图表显示: 2年日K线")
print(f"  成分股: {len(STOCK_LIST)}只")
print("="*70)

# ============================================================================
# 1. 获取数据（2年）
# ============================================================================
def fetch_data(tushare_code):
    try:
        df = ts.pro_bar(ts_code=tushare_code, adj='qfq',
                       start_date=CHART_START, end_date=CHART_END)
        if df is None or len(df) < 30:
            return None
        df = df.sort_values('trade_date').reset_index(drop=True)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        return df
    except:
        return None

print("\n>>> 获取2年日线数据...")
stock_data = []
for i, s in enumerate(STOCK_LIST):
    if i % 50 == 0:
        print(f"  {i}/{len(STOCK_LIST)}", flush=True)
    df = fetch_data(s['tushare_code'])
    if df is not None:
        stock_data.append({**s, 'df': df})
    time.sleep(0.15)
print(f"  成功: {len(stock_data)}/{len(STOCK_LIST)}", flush=True)

# ============================================================================
# 2. 在筛选时间范围内检测三角收敛
# ============================================================================
def find_swings(df, order=3):
    highs, lows = [], []
    for i in range(order, len(df)-order):
        if all(df.iloc[i]['high'] >= df.iloc[j]['high'] for j in range(i-order, i+order+1) if j != i):
            highs.append((i, df.iloc[i]['high']))
        if all(df.iloc[i]['low'] <= df.iloc[j]['low'] for j in range(i-order, i+order+1) if j != i):
            lows.append((i, df.iloc[i]['low']))
    return highs, lows

def detect_triangle(df, scan_start, scan_end):
    """只在scan_start~scan_end时间范围内检测三角收敛"""
    results = []
    highs, lows = find_swings(df, order=3)
    if len(highs) < 2 or len(lows) < 2:
        return results

    # 找到筛选时间范围对应的索引
    ss_idx = df[df['trade_date'] >= scan_start].index.min()
    se_idx = df[df['trade_date'] <= scan_end].index.max()
    if pd.isna(ss_idx) or pd.isna(se_idx):
        return results
    ss_idx = int(ss_idx); se_idx = int(se_idx)

    seen = set()
    for h0 in range(len(highs)):
        for l0 in range(len(lows)):
            h1i, h1v = highs[h0]; l1i, l1v = lows[l0]
            if abs(h1i - l1i) > 10:
                continue
            hp = [(h1i, h1v)]; lp = [(l1i, l1v)]
            for h in highs[h0+1:]:
                if h[0] > lp[-1][0]: hp.append(h); break
            for l in lows[l0+1:]:
                if l[0] > hp[-1][0]: lp.append(l); break
            if len(hp) < 2 or len(lp) < 2:
                continue

            hi, hv = [p[0] for p in hp], [p[1] for p in hp]
            li, lv = [p[0] for p in lp], [p[1] for p in lp]
            hs = (hv[-1]-hv[0])/max(hi[-1]-hi[0],1)
            ls_ = (lv[-1]-lv[0])/max(li[-1]-li[0],1)
            if hs >= 0 or ls_ <= 0:
                continue

            tri_s = min(hi[0], li[0])
            tri_e = max(hi[-1], li[-1])
            dur = tri_e - tri_s

            # 三角收敛必须在筛选时间范围内
            if tri_e < ss_idx or tri_s > se_idx:
                continue
            if dur < 15 or dur > 100:
                continue
            hgt = hv[0] - lv[0]
            avg = df.iloc[tri_s:tri_e+1]['close'].mean()
            if hgt/avg < 0.03 or hgt/avg > 0.35:
                continue
            key = (tri_s, tri_e)
            if key in seen:
                continue
            seen.add(key)

            # 找突破
            bk_i, bk_p = None, None
            for i in range(tri_e+1, min(tri_e+15, len(df))):
                if df.iloc[i]['close'] > hv[0] + hs*(i-hi[0]):
                    bk_i, bk_p = i, df.iloc[i]['close']
                    break
            if bk_i is None:
                li2 = len(df)-1
                res2 = hv[0] + hs*(li2-hi[0])
                if df.iloc[li2]['close'] > res2*0.985:
                    bk_i, bk_p = li2, df.iloc[li2]['close']
            if bk_i is None:
                continue

            # 前期趋势
            ps = max(0, tri_s-25)
            pre = df.iloc[ps:tri_s]['close']
            if len(pre) < 10:
                continue
            pt = (pre.iloc[-1]-pre.iloc[0])/pre.iloc[0]
            if pt < -0.03:
                continue

            tgt = bk_p + hgt
            cp = df.iloc[-1]['close']
            up = (tgt-bk_p)/bk_p*100
            ag = (cp-bk_p)/bk_p*100
            pr = df.iloc[bk_i:]['close'].pct_change().dropna()
            wr = (pr>0).sum()/len(pr) if len(pr)>0 else 0.5
            sym = 1-abs(abs(hs)-abs(ls_))/(abs(hs)+abs(ls_)+1e-10)
            dtr = (REF_DATE - df.iloc[tri_e]['trade_date']).days

            time_s = 100 if dtr<=3 else (90 if dtr<=7 else (75 if dtr<=14 else (60 if dtr<=21 else (50 if dtr<=30 else max(0,40-(dtr-30))))))
            w = wr*100
            u = min(100, up*5)
            total = time_s*0.35 + w*0.30 + u*0.35

            results.append(dict(
                hp=hp, lp=lp, hs=hs, ls=ls_, hgt=hgt,
                bk_i=bk_i, bk_p=bk_p, tgt=tgt, cp=cp, up=up, ag=ag,
                wr=min(max(wr,0.3),0.95), sym=sym, pt=pt, dtr=dtr, dur=dur,
                tri_s=tri_s, tri_e=tri_e,
                ts_date=df.iloc[tri_s]['trade_date'],
                te_date=df.iloc[tri_e]['trade_date'],
                bk_date=df.iloc[bk_i]['trade_date'],
                time_score=time_s, win_score=w, upside_score=u, total=total, df=df
            ))
    return results

print("\n>>> 检测三角收敛形态（筛选范围: 2025-11 ~ 2026-05-13）...")
all_res = []
for sd in stock_data:
    pats = detect_triangle(sd['df'], SCAN_START, SCAN_END)
    for p in pats:
        p['code'] = sd['tushare_code']
        p['name'] = NAMES.get(p['code'], p['code'].split('.')[0])
        p['weight'] = sd['weight']
        all_res.append(p)

print(f"  共发现 {len(all_res)} 个形态", flush=True)

if not all_res:
    print("  未找到，尝试放宽条件...")
    for sd in stock_data:
        pats = detect_triangle(sd['df'], '20260101', SCAN_END)
        for p in pats:
            p['code'] = sd['tushare_code']
            p['name'] = NAMES.get(p['code'], p['code'].split('.')[0])
            p['weight'] = sd['weight']
            all_res.append(p)
    print(f"  放宽后共 {len(all_res)} 个")

if not all_res:
    print("  未找到任何形态，退出。")
    exit(0)

# 筛选：预计目标涨幅 >= 8%
all_res = [r for r in all_res if r['up'] >= 8.0]
print(f"  筛除涨幅<8%后，剩余 {len(all_res)} 个形态", flush=True)

if not all_res:
    print("  筛除后无符合条件的形态，退出。")
    exit(0)

# 按胜率排序（降序）
all_res.sort(key=lambda x: x['wr'], reverse=True)
top5 = all_res[:5]

# ============================================================================
# 3. 生成上榜理由文本
# ============================================================================
def gen_reasons(r):
    reasons = []
    d = r['dtr']
    if d <= 3:
        reasons.append(f"形态刚收敛完成（距5/13仅{d}天），突破信号最新鲜")
    elif d <= 7:
        reasons.append(f"形态于{d}天前完成收敛，突破时间窗口理想")
    elif d <= 14:
        reasons.append(f"形态于{d}天前收敛，突破信号有效")
    else:
        reasons.append(f"形态于{d}天前收敛")

    wr = r['wr']*100
    if wr > 70:
        reasons.append(f"突破后日线胜率{wr:.0f}%，表现优秀")
    elif wr > 55:
        reasons.append(f"突破后日线胜率{wr:.0f}%，表现较好")
    else:
        reasons.append(f"突破后日线胜率{wr:.0f}%")

    reasons.append(f"量度目标涨幅{r['up']:.1f}%（目标¥{r['tgt']:.2f} / 突破¥{r['bk_p']:.2f}）")

    sym = r['sym']
    if sym > 0.8:
        reasons.append(f"三角收敛对称度{sym:.0%}，形态标准")
    elif sym > 0.5:
        reasons.append(f"三角收敛对称度{sym:.0%}，形态较好")

    if r['pt'] > 0.1:
        reasons.append(f"收敛前强上涨趋势+{r['pt']*100:.1f}%，典型上涨中继")
    elif r['pt'] > 0:
        reasons.append(f"收敛前上涨趋势+{r['pt']*100:.1f}%，确认中继属性")

    reasons.append(f"三角持续{r['dur']}个交易日，整理充分")
    return reasons

# ============================================================================
# 4. 绘图（2年日K线 + 上榜理由）
# ============================================================================
def plot_it(r, rank):
    df = r['df']
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 13),
        gridspec_kw={'height_ratios': [3.5, 1]}, facecolor='#0d1117')

    title = f'#{rank}  {r["code"].split(".")[0]}  {r["name"]}  三角收敛上涨中继'
    fig.suptitle(title, fontsize=18, fontweight='bold', color='#c9d1d9', y=0.99)

    # 2年日K线 (蜡烛图风格 - 用填充)
    ax1.set_facecolor('#161b22')
    ax1.plot(df['trade_date'], df['close'], color='#58a6ff', lw=1.2, label='收盘价', zorder=5)
    ax1.fill_between(df['trade_date'], df['low'], df['high'], alpha=0.08, color='#58a6ff')

    # 三角区域
    hf = np.polyfit([p[0] for p in r['hp']], [p[1] for p in r['hp']], 1)
    lf = np.polyfit([p[0] for p in r['lp']], [p[1] for p in r['lp']], 1)
    tri_s, tri_e = r['tri_s'], r['tri_e']
    xr = range(tri_s, tri_e+1)
    xd = [df.iloc[i]['trade_date'] for i in xr]
    ul = np.polyval(hf, list(xr))
    ll = np.polyval(lf, list(xr))

    ax1.fill_between(xd, ll, ul, alpha=0.18, color='#FFD700', label='三角收敛区域')
    ax1.plot(xd, ul, color='#f85149', lw=3, label='阻力线')
    ax1.plot(xd, ll, color='#3fb950', lw=3, label='支撑线')

    # Swing点
    for idx, pv in r['hp']:
        ax1.plot(df.iloc[idx]['trade_date'], pv, 'v', color='#f85149', ms=10, zorder=10, markeredgewidth=2)
    for idx, pv in r['lp']:
        ax1.plot(df.iloc[idx]['trade_date'], pv, '^', color='#3fb950', ms=10, zorder=10, markeredgewidth=2)

    # 突破点
    bk_d = df.iloc[r['bk_i']]['trade_date']
    ax1.annotate('突破', xy=(bk_d, r['bk_p']),
        xytext=(bk_d, r['bk_p'] + r['hgt']*0.15), fontsize=12, fontweight='bold',
        color='#3fb950', arrowprops=dict(arrowstyle='->', color='#3fb950', lw=2.5), zorder=15)

    # 目标价 & 突破价
    ax1.axhline(y=r['tgt'], color='#FFD700', ls='--', lw=2, alpha=0.8,
                label=f'量度目标: {r["tgt"]:.2f}', zorder=8)
    ax1.axhline(y=r['bk_p'], color='#3fb950', ls=':', lw=2, alpha=0.6,
                label=f'突破价: {r["bk_p"]:.2f}', zorder=8)

    # 上升空间箭头
    ax1.annotate('', xy=(bk_d, r['tgt']), xytext=(bk_d, r['bk_p']),
        arrowprops=dict(arrowstyle='<->', color='#FFD700', lw=3), zorder=15)
    mid = (r['tgt'] + r['bk_p']) / 2
    ax1.text(bk_d, mid, f' +{r["up"]:.1f}%', fontsize=14, fontweight='bold',
        color='#FFD700', ha='left', va='center', zorder=15,
        bbox=dict(boxstyle='round,pad=0.4', facecolor='#161b22', edgecolor='#FFD700', alpha=0.9, lw=2))

    ax1.set_ylabel('价格 (元)', color='#c9d1d9', fontsize=12)
    ax1.legend(loc='upper left', fontsize=10, facecolor='#161b22', edgecolor='#30363d',
               labelcolor='#c9d1d9', framealpha=0.9)
    ax1.grid(True, alpha=0.15)
    ax1.tick_params(colors='#c9d1d9', labelsize=10)

    # 成交量
    ax2.set_facecolor('#161b22')
    cv = ['#3fb950' if df.iloc[i]['close'] >= df.iloc[i]['open'] else '#f85149' for i in range(len(df))]
    ax2.bar(df['trade_date'], df['vol'], color=cv, alpha=0.6)
    ax2.axvspan(df.iloc[tri_s]['trade_date'], df.iloc[tri_e]['trade_date'],
        alpha=0.18, color='#FFD700')
    ax2.set_ylabel('成交量', color='#c9d1d9', fontsize=12)
    ax2.grid(True, alpha=0.15)
    ax2.tick_params(colors='#c9d1d9', labelsize=10)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # --- 上榜理由框 ---
    reasons = gen_reasons(r)
    reason_text = f"上榜理由 (综合得分: {r['total']:.1f}):\n" + "\n".join([f"{i+1}. {r}" for i, r in enumerate(reasons)])
    props = dict(boxstyle='round,pad=0.8', facecolor='#161b22', edgecolor='#58a6ff', alpha=0.95, lw=2)
    ax1.text(0.02, 0.02, reason_text, transform=ax1.transAxes, fontsize=10,
        verticalalignment='bottom', color='#c9d1d9', fontfamily='monospace',
        bbox=props, zorder=20, linespacing=1.6)

    plt.xticks(rotation=45)
    plt.tight_layout()
    path = f'{OUT}/top{rank}_{r["code"].split(".")[0]}_{r["name"]}_v3.png'
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f"  已保存: {os.path.basename(path)}", flush=True)

# ============================================================================
# 5. 输出结果
# ============================================================================
print(f"\n{'='*70}")
print(f"  TOP 5 三角收敛上涨中继")
print(f"{'='*70}")

for i, r in enumerate(top5):
    print(f"\n{'─'*50}")
    print(f"第{i+1}名: {r['code']} {r['name']} (权重{r['weight']:.1f}%)")
    print(f"  综合得分: {r['total']:.1f} | 时间:{r['time_score']:.0f} 胜率:{r['win_score']:.0f} 空间:{r['upside_score']:.0f}")
    print(f"  三角区间: {r['ts_date'].strftime('%Y-%m-%d')} ~ {r['te_date'].strftime('%Y-%m-%d')} ({r['dur']}天)")
    print(f"  突破日期: {r['bk_date'].strftime('%Y-%m-%d')} @ ¥{r['bk_p']:.2f}")
    print(f"  量度目标: ¥{r['tgt']:.2f} (空间 {r['up']:.1f}%)")
    print(f"  当前价格: ¥{r['cp']:.2f} (已涨 {r['ag']:+.1f}%)")
    print(f"  上榜理由:")
    for j, reason in enumerate(gen_reasons(r), 1):
        print(f"    {j}. {reason}")
    plot_it(r, i+1)

# 6. 保存TOP 30 CSV
top30 = all_res[:30]
csv_rows = []
for i, r in enumerate(top30):
    csv_rows.append({
        '排名': i+1,
        '代码': r['code'].split('.')[0],
        '名称': r['name'],
        '综合得分': round(r['total'], 1),
        '三角开始日期': r['ts_date'].strftime('%Y-%m-%d'),
        '三角结束日期': r['te_date'].strftime('%Y-%m-%d'),
        '三角持续天数': r['dur'],
        '突破日期': r['bk_date'].strftime('%Y-%m-%d'),
        '突破价格': round(r['bk_p'], 2),
        '当前价格': round(r['cp'], 2),
        '当前已涨跌幅_pct': round(r['ag'], 1),
        '三角前涨幅_pct': round(r['pt']*100, 1),
        '预计目标涨幅_pct': round(r['up'], 1),
        '量度目标价': round(r['tgt'], 2),
        '胜率_pct': round(r['wr']*100, 0),
        '对称度_pct': round(r['sym']*100, 0),
        '权重_pct': round(r['weight'], 1),
    })

csv_df = pd.DataFrame(csv_rows)
csv_path = f'{OUT}/top30_三角收敛上涨中继.csv'
csv_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
print(f"\nTOP30 CSV已保存: {csv_path}")
print(csv_df[['排名','代码','名称','综合得分','三角持续天数','三角前涨幅_pct','预计目标涨幅_pct','胜率_pct']].to_string(index=False))

print(f"\n{'='*70}")
print(f"完成！图表已保存至 {OUT}")
print(f"{'='*70}")
