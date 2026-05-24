#!/usr/bin/env python3
"""
行业板块评分回测 V2 (含资金流)
测试: 选出Top N板块后未来3天表现
时期: 2025-01 ~ 2026-04
优化: 全量预取，一次评分多次分析
"""
import sys, os, time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

START_DATE = '20250101'
END_DATE = '20260430'
FORWARD_DAYS = 3
TOP_N = [1, 3, 5, 10]

# ============================================================
# 工具函数
# ============================================================

def get_trade_days(start, end, limit=600):
    all_days = []
    dt = datetime.strptime(end, '%Y%m%d')
    checked = 0
    while checked < limit:
        td = (dt - timedelta(days=checked)).strftime('%Y%m%d')
        if td < str(int(start)-1):
            break
        data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
        if data and data.get('items'):
            all_days.append(td)
        checked += 1
        time.sleep(0.06)
    return sorted(set(all_days))


def get_future(eval_day, all_days, n):
    idx = all_days.index(eval_day)
    return all_days[idx+1:idx+1+n] if idx + n < len(all_days) else []


def prefetch_all(trade_days):
    """预取行情的收益率和资金流"""
    print(f'预取 {len(trade_days)} 天数据...', file=sys.stderr)
    daily = {}
    money = {}
    for i, td in enumerate(trade_days):
        d = hs.api_call('daily', trade_date=td, limit=5000, fields='ts_code,pct_chg')
        daily[td] = {r['ts_code']: float(r['pct_chg']) for r in (hs.parse_data(d) or [])}
        m = hs.api_call('moneyflow', trade_date=td,
                       fields='ts_code,buy_lg_amount,sell_lg_amount,'
                              'buy_elg_amount,sell_elg_amount')
        mf = {}
        for r in (hs.parse_data(m) or []):
            c = r['ts_code']
            ba = float(r.get('buy_lg_amount',0)) + float(r.get('buy_elg_amount',0))
            sa = float(r.get('sell_lg_amount',0)) + float(r.get('sell_elg_amount',0))
            t = ba + sa
            net = float(r.get('net_mf_amount', 0) or 0)
            mf[c] = {'net_rate': net/t*100 if t>0 else 0}
        money[td] = mf
        if (i+1)%30 == 0:
            print(f'  [{i+1}/{len(trade_days)}]', file=sys.stderr)
        time.sleep(0.08)
    return daily, money


def build_ind_stats(ind_stocks, daily, trade_days):
    """预计算所有行业的每日统计"""
    stats = {}
    for td in trade_days:
        snap = daily.get(td, {})
        s = {}
        for ind, codes in ind_stocks.items():
            rets = [snap[c] for c in codes if c in snap]
            if rets:
                s[ind] = {
                    'avg_ret': sum(rets)/len(rets),
                    'up_ratio': sum(1 for r in rets if r>0)/len(rets)*100,
                    'stock_count': len(codes),
                }
        stats[td] = s
    return stats


# ============================================================
# 单日评分（只用预取数据，不调API）
# ============================================================

def score_day(eval_day, all_days, daily, ind_stats, ind_money, ind_stocks, stock_to_ind):
    idx = all_days.index(eval_day)
    hist = all_days[max(0, idx-25):idx+1]
    stats = ind_stats.get(eval_day, {})
    if not stats:
        return []
    
    # RPS
    multi = {}
    for ind in stats:
        r5, r20 = [], []
        for i, hd in enumerate(reversed(hist)):
            s = ind_stats.get(hd, {}).get(ind)
            if s:
                if i < 5: r5.append(s['avg_ret'])
                if i < 20: r20.append(s['avg_ret'])
        multi[ind] = {'ret_5d': sum(r5), 'ret_20d': sum(r20)}
    
    # 量比(简化)
    vol = {ind: 1.0 for ind in stats}
    
    # 涨停
    lu = defaultdict(list)
    snap = daily.get(eval_day, {})
    for c, p in snap.items():
        ind = stock_to_ind.get(c)
        if ind and p >= 9.5:
            lu[ind].append(c)
    
    # HS300(预取后不用再调API，简化)
    hs300_ret = 0
    
    # 资金流
    mf = ind_money.get(eval_day, {})
    
    return hs.score_hot_sectors(stats, multi, vol, lu, hs300_ret, mf)


def compute_fwd_ret(ind, future_days, daily, ind_stocks):
    """计算行业未来N天累计收益"""
    codes = ind_stocks.get(ind, [])
    if not codes:
        return None
    total = 0.0
    for fd in future_days:
        snap = daily.get(fd, {})
        rets = [snap[c] for c in codes if c in snap]
        if rets:
            total += sum(rets) / len(rets)
    return total


# ============================================================
# 主流程
# ============================================================

def main():
    print(f'=== 行业板块回测 V2 ===', file=sys.stderr)
    print(f'  时期: {START_DATE} ~ {END_DATE}', file=sys.stderr)
    print(f'  持有: {FORWARD_DAYS}天', file=sys.stderr)
    
    # 1. 交易日
    print('\n[1] 交易日...', file=sys.stderr)
    all_days = get_trade_days(START_DATE, END_DATE)
    buff = get_trade_days('20241201', '20241231')
    ext_days = sorted(set(buff + all_days))
    eval_days = sorted(d for d in all_days if d >= START_DATE)
    print(f'  {len(eval_days)}个评估日 + {len(buff)}缓冲', file=sys.stderr)
    
    # 2. 行业分类
    print('\n[2] 行业分类...', file=sys.stderr)
    s2i, ind_stocks, _ = hs.fetch_stock_industry_map()
    print(f'  {len(ind_stocks)}个行业', file=sys.stderr)
    
    # 3. 预取
    print('\n[3] 预取数据...', file=sys.stderr)
    daily, money = prefetch_all(ext_days)
    ind_stats = build_ind_stats(ind_stocks, daily, ext_days)
    ind_money = {}
    for td in ext_days:
        mf = money.get(td, {})
        agg = {}
        for ind, codes in ind_stocks.items():
            rates = [mf[c]['net_rate'] for c in codes if c in mf]
            agg[ind] = {'net_rate': sum(rates)/len(rates) if rates else 0}
        ind_money[td] = agg
    
    # 4. 回测
    print(f'\n[4] 回测 {len(eval_days)}天...', file=sys.stderr)
    all_scored = {}  # {eval_day: scored_list}
    results = {n: {'wins': 0, 'total': 0, 'ret_list': []} for n in TOP_N}
    
    for i, ed in enumerate(eval_days):
        fut = get_future(ed, ext_days, FORWARD_DAYS)
        if len(fut) < FORWARD_DAYS:
            continue
        
        scored = score_day(ed, ext_days, daily, ind_stats, ind_money, ind_stocks, s2i)
        all_scored[ed] = scored
        if not scored:
            continue
        
        for n in TOP_N:
            top = scored[:n]
            rets = [compute_fwd_ret(s['name'], fut, daily, ind_stocks) for s in top]
            rets = [r for r in rets if r is not None]
            if rets:
                avg = sum(rets)/len(rets)
                results[n]['ret_list'].append(avg)
                results[n]['total'] += 1
                if avg > 0: results[n]['wins'] += 1
        
        if (i+1)%50 == 0:
            print(f'  [{i+1}/{len(eval_days)}] {ed}', file=sys.stderr)
    
    # 5. 输出
    print(f'\n{"="*70}')
    print(f'结果  {START_DATE}~{END_DATE}  持有{FORWARD_DAYS}天')
    print(f'{"="*70}')
    print(f'{"TopN":>6} {"信号":>6} {"胜率":>8} {"均收益":>9} {"中位":>9} {"最大":>9} {"最小":>9}')
    print(f'{"-"*62}')
    for n in TOP_N:
        r = results[n]
        if r['total'] > 0:
            rets = sorted(r['ret_list'])
            wr = r['wins']/r['total']*100
            avg = sum(rets)/len(rets)
            med = rets[len(rets)//2]
            print(f'{n:>6} {r["total"]:>6} {wr:>7.1f}% {avg:>+8.2f}% {med:>+8.2f}% '
                  f'{max(rets):>+8.2f}% {min(rets):>+8.2f}%')
    
    # 分阶段
    print(f'\n{"="*70}')
    print(f'分阶段胜率')
    print(f'{"="*70}')
    periods = [
        ('2025Q1-Q2', lambda d: d < '20250701'),
        ('2025Q3-Q4', lambda d: '20250701' <= d < '20260101'),
        ('2026Q1', lambda d: d >= '20260101'),
    ]
    for pname, pred in periods:
        days = [d for d in eval_days if pred(d)]
        print(f'\n{pname} ({len(days)}天):')
        for n in TOP_N:
            w = t = 0
            for ed in days:
                if ed not in all_scored:
                    continue
                scored = all_scored[ed]
                if not scored: continue
                fut = get_future(ed, ext_days, FORWARD_DAYS)
                if len(fut) < FORWARD_DAYS: continue
                top = scored[:n]
                rets = [compute_fwd_ret(s['name'], fut, daily, ind_stocks) for s in top]
                rets = [r for r in rets if r is not None]
                if rets:
                    t += 1
                    if sum(rets)/len(rets) > 0: w += 1
            if t > 0: print(f'  Top{n}: {w}/{t}={w/t*100:.1f}%')
    
    # 胜率按月
    print(f'\n{"="*70}')
    print(f'月度胜率 (Top5)')
    print(f'{"="*70}')
    months = {}
    for ed in eval_days:
        m = ed[:6]
        if m not in months: months[m] = {'w':0,'t':0}
        if ed not in all_scored: continue
        scored = all_scored[ed]
        if not scored: continue
        fut = get_future(ed, ext_days, FORWARD_DAYS)
        if len(fut) < FORWARD_DAYS: continue
        top = scored[:5]
        rets = [compute_fwd_ret(s['name'], fut, daily, ind_stocks) for s in top]
        rets = [r for r in rets if r is not None]
        if rets:
            months[m]['t'] += 1
            if sum(rets)/len(rets) > 0: months[m]['w'] += 1
    for m in sorted(months):
        d = months[m]
        wr = d['w']/d['t']*100 if d['t']>0 else 0
        bar = '█' * int(wr/10) + '░' * (10-int(wr/10))
        print(f'  {m}  {bar}  {d["w"]:>2}/{d["t"]:<2} {wr:>5.1f}%')


if __name__ == '__main__':
    main()
