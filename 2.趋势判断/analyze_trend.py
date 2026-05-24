#!/usr/bin/env python3
"""分析趋势判断本身的准确度"""
import sys, os, time
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

END_DATE = '20260522'

# 获取交易日
days = []
for offset in range(200):
    td = (datetime.strptime(END_DATE, '%Y%m%d') - timedelta(days=offset)).strftime('%Y%m%d')
    data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
    if data and data.get('items'):
        days.append(td)
        if len(days) >= 180:
            break
    time.sleep(0.08)
days.sort()

# 获取HS300
hs300 = {}
for td in days:
    data = hs.api_call('index_daily', ts_code='000300.SH',
                       start_date=td, end_date=td,
                       fields='trade_date,close,pct_chg')
    rows = hs.parse_data(data)
    if rows:
        hs300[td] = {'close': float(rows[0]['close']), 'pct': float(rows[0]['pct_chg'])}
    time.sleep(0.08)

print(f'交易日: {len(days)}, {days[0]} ~ {days[-1]}')

# 对每天: 用5日HS300判断趋势, 看次日是否正确
results = []
for i in range(5, len(days)-1):
    cur = days[i]
    nxt = days[i+1]
    start_idx = max(0, i-5)
    ret_5d = sum(hs300[days[j]]['pct'] for j in range(start_idx, i+1) if days[j] in hs300)
    trend = 'up' if ret_5d >= 1.5 else ('down' if ret_5d <= -1.5 else 'sideways')
    nxt_ret = hs300[nxt]['pct'] if nxt in hs300 else 0
    results.append({
        'date': cur, 'trend': trend, 'ret_5d': round(ret_5d, 2),
        'nxt_ret': nxt_ret, 'nxt_up': nxt_ret > 0
    })

print(f'\n{"="*60}')
print(f'趋势判断准确度分析')
print(f'{"="*60}\n')

for trend, label, icon in [('up','上升趋势','📈'), ('sideways','震荡市','➡'), ('down','下降趋势','📉')]:
    subset = [r for r in results if r['trend'] == trend]
    if not subset:
        continue
    up_next = sum(1 for r in subset if r['nxt_up'])
    avg_nxt = sum(r['nxt_ret'] for r in subset) / len(subset)
    print(f'{icon} {label} ({len(subset)}天):')
    print(f'   次日大盘上涨: {up_next}/{len(subset)} ({up_next/len(subset)*100:.0f}%)')
    print(f'   次日均涨幅: {avg_nxt:+.3f}%')
    # 趋势自身的持续准确率
    if trend == 'up':
        print(f'   趋势信号准确率: {up_next/len(subset)*100:.0f}% → 说"涨"次日真涨的概率')
    elif trend == 'down':
        down_next = len(subset) - up_next
        print(f'   趋势信号准确率: {down_next/len(subset)*100:.0f}% → 说"跌"次日真跌的概率')
    print()

# 趋势持续力
print(f'{"="*60}')
print(f'趋势持续时间分析')
print(f'{"="*60}\n')

# 连续同趋势段
runs = []
ct = results[0]['trend']
run_len = 1
for r in results[1:]:
    if r['trend'] == ct:
        run_len += 1
    else:
        runs.append((ct, run_len))
        ct = r['trend']
        run_len = 1
runs.append((ct, run_len))

for trend, label in [('up','上升'), ('down','下降'), ('sideways','震荡')]:
    tr = [r for r in runs if r[0] == trend]
    if tr:
        lens = [r[1] for r in tr]
        avg = sum(lens)/len(lens)
        mx = max(lens)
        print(f'  {label}趋势: {len(tr)}次, 平均持续{avg:.1f}天, 最长{mx}天')

# 趋势跃迁概率
print()
print(f'{"="*60}')
print(f'趋势跃迁概率（今天→明天）')
print(f'{"="*60}\n')

trans = defaultdict(lambda: defaultdict(int))
for i in range(1, len(results)):
    trans[results[i-1]['trend']][results[i]['trend']] += 1

for ft in ['up', 'sideways', 'down']:
    total = sum(trans[ft].values())
    if total == 0:
        continue
    parts = []
    for tt in ['up', 'sideways', 'down']:
        cnt = trans[ft][tt]
        parts.append(f'{tt}={cnt/total*100:.0f}%')
    print(f'  {ft} →  {" |  ".join(parts)}')

# 阈值敏感性分析
print()
print(f'{"="*60}')
print(f'阈值敏感性分析')
print(f'{"="*60}\n')

for threshold in [0.5, 1.0, 1.5, 2.0, 3.0]:
    up_days = []
    down_days = []
    for i in range(5, len(days)-1):
        cur = days[i]
        nxt = days[i+1]
        start_idx = max(0, i-5)
        ret_5d = sum(hs300[days[j]]['pct'] for j in range(start_idx, i+1) if days[j] in hs300)
        nxt_ret = hs300[nxt]['pct'] if nxt in hs300 else 0
        if ret_5d >= threshold:
            up_days.append(nxt_ret)
        elif ret_5d <= -threshold:
            down_days.append(nxt_ret)
    
    up_win = sum(1 for r in up_days if r > 0) if up_days else 0
    down_win = sum(1 for r in down_days if r < 0) if down_days else 0
    up_avg = sum(up_days)/len(up_days) if up_days else 0
    down_avg = sum(down_days)/len(down_days) if down_days else 0
    
    print(f'  阈值 ±{threshold:.1f}%:')
    print(f'    📈 上升信号: {len(up_days)}天, 次日上涨{up_win}/{len(up_days)} ({up_win/max(len(up_days),1)*100:.0f}%), 均{up_avg:+.3f}%')
    print(f'    📉 下降信号: {len(down_days)}天, 次日下跌{down_win}/{len(down_days)} ({down_win/max(len(down_days),1)*100:.0f}%), 均{down_avg:+.3f}%')
