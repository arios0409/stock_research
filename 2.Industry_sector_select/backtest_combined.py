#!/usr/bin/env python3
"""
行业板块+大盘趋势联合回测
只在上升趋势(↑绿区)时选Top板块，对比无过滤
"""
import sys, os, time
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

START_DATE = '20250101'
END_DATE = '20260430'
FORWARD_DAYS = 3
TOP_N = [1, 3, 5, 10]

TRADING_DAYS_PER_YEAR = 245

# ============================================================
# 工具函数
# ============================================================

def get_trade_days(start, end, limit=600):
    all_days = []
    dt = datetime.strptime(end, '%Y%m%d')
    checked = 0
    while checked < limit:
        td = (dt - timedelta(days=checked)).strftime('%Y%m%d')
        if td < str(int(start)-1): break
        data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
        if data and data.get('items'): all_days.append(td)
        checked += 1
        time.sleep(0.06)
    return sorted(set(all_days))


def get_future(ed, days, n):
    idx = days.index(ed)
    return days[idx+1:idx+1+n] if idx+n < len(days) else []


# ============================================================
# 大盘趋势判定 (KDJ 14,5,3 概率系统)
# ============================================================

def compute_market_states(trade_days):
    """对每个交易日计算市场状态，返回 {date: state}
    state: 1=↑上升, 2=⚠风险, 3=↓下降
    """
    print('计算大盘趋势状态...', file=sys.stderr)
    
    # 获取上证指数数据
    idx_data = hs.api_call('index_daily', ts_code='000001.SH',
                          start_date=trade_days[0], end_date=trade_days[-1],
                          fields='trade_date,open,high,low,close')
    rows = hs.parse_data(idx_data)
    if not rows:
        print('  [WARN] 上证指数数据为空，跳过趋势过滤', file=sys.stderr)
        return {}
    
    # 按日期排序
    rows.sort(key=lambda r: r['trade_date'])
    
    closes = np.array([float(r['close']) for r in rows])
    highs = np.array([float(r['high']) for r in rows])
    lows = np.array([float(r['low']) for r in rows])
    dates = [r['trade_date'] for r in rows]
    
    # KDJ(14,5,3)
    N, M1, M2 = 14, 5, 3
    k = np.full(len(closes), np.nan)
    d = np.full(len(closes), np.nan)
    p_up = np.full(len(closes), 50.0)
    p_down = np.full(len(closes), 50.0)
    p_risk = np.full(len(closes), 50.0)
    
    for i in range(N-1, len(closes)):
        hh = np.max(highs[i-N+1:i+1])
        ll = np.min(lows[i-N+1:i+1])
        rsv = 50.0 if hh == ll else (closes[i]-ll)/(hh-ll)*100
        if np.isnan(k[i-1]):
            k[i] = rsv; d[i] = rsv
        else:
            k[i] = (rsv*1 + k[i-1]*(M1-1))/M1
            d[i] = (k[i]*1 + d[i-1]*(M2-1))/M2
    
    # 概率系统
    up_days = down_days = risk_days = 0
    for i in range(N, len(closes)):
        is_g = k[i-1] <= d[i-1] and k[i] > d[i]
        is_d = k[i-1] >= d[i-1] and k[i] < d[i]
        hd = is_d and k[i] >= 85
        dz = k[i] < 35 and d[i] < 40
        
        up_days = up_days+1 if k[i] > d[i] else 0
        down_days = down_days+1 if dz else 0
        risk_days = risk_days+1 if (k[i] < d[i] and k[i] >= 85) else 0
        
        # P_up
        if k[i] > d[i]:
            p_up_val = 80 if (is_g and k[i]<30 and d[i]<30) else (60 if is_g else min(60+up_days*5, 92))
        else:
            p_up_val = 30 if is_d else max(p_up[i-1]-(down_days*8 if down_days>0 else 3), 10)
        
        # P_down
        if dz: p_down_val = min(55+down_days*5, 88)
        elif k[i] < d[i] and k[i] < 50: p_down_val = min(45+(50-k[i])*1.5, 80)
        elif hd: p_down_val = 50
        elif risk_days >= 1: p_down_val = min(50+risk_days*3, 70)
        elif is_g: p_down_val = max(p_down[i-1]-15, 10)
        else: p_down_val = max(p_down[i-1]-2, 20)
        
        # P_risk
        if hd: p_risk_val = 65
        elif risk_days >= 1 and k[i] < d[i]: p_risk_val = min(65+risk_days*5, 88)
        elif k[i] < d[i] and k[i] >= 75: p_risk_val = min(45+(k[i]-75)*2, 65)
        elif dz: p_risk_val = max(p_risk[i-1]-10, 10)
        elif is_g: p_risk_val = max(p_risk[i-1]-20, 5)
        else: p_risk_val = max(p_risk[i-1]-2, 15)
        
        p_up[i] = p_up_val; p_down[i] = p_down_val; p_risk[i] = p_risk_val
    
    # 状态判定
    state_map = {}
    for i in range(N, len(closes)):
        s = 1 if (p_up[i] > p_risk[i] and p_up[i] > p_down[i]) else \
            2 if (p_risk[i] > p_up[i] and p_risk[i] > p_down[i]) else \
            3 if (p_down[i] > p_up[i] and p_down[i] > p_risk[i]) else 0
        state_map[dates[i]] = s
    
    # 统计
    up_cnt = sum(1 for s in state_map.values() if s == 1)
    risk_cnt = sum(1 for s in state_map.values() if s == 2)
    down_cnt = sum(1 for s in state_map.values() if s == 3)
    print(f'  ↑上升{up_cnt}天 ⚠风险{risk_cnt}天 ↓下降{down_cnt}天', file=sys.stderr)
    
    return state_map


# ============================================================
# 预取数据
# ============================================================

def prefetch_all(trade_days):
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
        if (i+1)%30 == 0: print(f'  [{i+1}/{len(trade_days)}]', file=sys.stderr)
        time.sleep(0.08)
    return daily, money


def build_ind_stats(ind_stocks, daily, trade_days):
    stats = {}
    for td in trade_days:
        snap = daily.get(td, {})
        s = {}
        for ind, codes in ind_stocks.items():
            rets = [snap[c] for c in codes if c in snap]
            if rets:
                s[ind] = {'avg_ret': sum(rets)/len(rets), 'up_ratio': sum(1 for r in rets if r>0)/len(rets)*100, 'stock_count': len(codes)}
        stats[td] = s
    return stats


# ============================================================
# 单日评分
# ============================================================

def score_day(ed, days, daily, ind_stats, ind_money, ind_stocks, s2i):
    idx = days.index(ed)
    hist = days[max(0, idx-25):idx+1]
    stats = ind_stats.get(ed, {})
    if not stats: return []
    
    multi = {}
    for ind in stats:
        r5, r20 = [], []
        for i, hd in enumerate(reversed(hist)):
            s = ind_stats.get(hd, {}).get(ind)
            if s:
                if i < 5: r5.append(s['avg_ret'])
                if i < 20: r20.append(s['avg_ret'])
        multi[ind] = {'ret_5d': sum(r5), 'ret_20d': sum(r20)}
    
    vol = {ind: 1.0 for ind in stats}
    lu = defaultdict(list)
    for c, p in daily.get(ed, {}).items():
        ind = s2i.get(c)
        if ind and p >= 9.5: lu[ind].append(c)
    
    mf = ind_money.get(ed, {})
    return hs.score_hot_sectors(stats, multi, vol, lu, 0, mf)


def fwd_ret(ind, future, daily, ind_stocks):
    codes = ind_stocks.get(ind, [])
    if not codes: return None
    total = 0.0
    for fd in future:
        snap = daily.get(fd, {})
        rets = [snap[c] for c in codes if c in snap]
        if rets: total += sum(rets)/len(rets)
    return total


# ============================================================
# 主流程
# ============================================================

def main():
    print('=== 行业板块+大盘趋势 联合回测 ===')
    print(f'  时期: {START_DATE} ~ {END_DATE}')
    print(f'  持有: {FORWARD_DAYS}天')
    
    # 1. 交易日
    print('\n[1] 交易日...', file=sys.stderr)
    all_days = get_trade_days(START_DATE, END_DATE)
    buff = get_trade_days('20241201', '20241231')
    ext_days = sorted(set(buff + all_days))
    eval_days = sorted(d for d in all_days if d >= START_DATE)
    print(f'  {len(eval_days)}评估日', file=sys.stderr)
    
    # 2. 大盘趋势
    print('\n[2] 大盘趋势...', file=sys.stderr)
    market_states = compute_market_states(ext_days)
    up_days = [d for d in eval_days if market_states.get(d) == 1]
    print(f'  上升趋势日: {len(up_days)}/{len(eval_days)} ({len(up_days)/len(eval_days)*100:.0f}%)', file=sys.stderr)
    
    # 3. 行业分类
    print('\n[3] 行业分类...', file=sys.stderr)
    s2i, ind_stocks, _ = hs.fetch_stock_industry_map()
    print(f'  {len(ind_stocks)}个行业', file=sys.stderr)
    
    # 4. 预取
    print('\n[4] 预取数据...', file=sys.stderr)
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
    
    # 5. 回测（同时跑有过滤和无过滤）
    print(f'\n[5] 回测...', file=sys.stderr)
    
    def run_backtest(filter_days=None):
        """filter_days: 只在这些天交易，None=全部"""
        results = {n: {'wins': 0, 'total': 0, 'ret_list': []} for n in TOP_N}
        trade_days_pool = filter_days if filter_days is not None else eval_days
        
        for i, ed in enumerate(trade_days_pool):
            fut = get_future(ed, ext_days, FORWARD_DAYS)
            if len(fut) < FORWARD_DAYS: continue
            
            scored = score_day(ed, ext_days, daily, ind_stats, ind_money, ind_stocks, s2i)
            if not scored: continue
            
            for n in TOP_N:
                top = scored[:n]
                rets = [fwd_ret(s['name'], fut, daily, ind_stocks) for s in top]
                rets = [r for r in rets if r is not None]
                if rets:
                    avg = sum(rets)/len(rets)
                    results[n]['ret_list'].append(avg)
                    results[n]['total'] += 1
                    if avg > 0: results[n]['wins'] += 1
            if (i+1)%50 == 0: print(f'  [{i+1}/{len(trade_days_pool)}] {ed}', file=sys.stderr)
        return results
    
    print('  无过滤(全部交易日)...', file=sys.stderr)
    all_res = run_backtest()
    
    print('  上升趋势过滤...', file=sys.stderr)
    up_res = run_backtest(up_days)
    
    # 6. 输出
    def print_results(label, results, total_days):
        print(f'\n{"="*75}')
        print(f'{label}  ({total_days}天)')
        print(f'{"="*75}')
        print(f'{"TopN":>6} {"信号":>6} {"胜率":>8} {"均收益":>9} {"月化":>8} {"年化":>8} {"中位":>9} {"最大":>9} {"最小":>9}')
        print(f'{"-"*67}')
        for n in TOP_N:
            r = results[n]
            if r['total'] > 0:
                rets = sorted(r['ret_list'])
                wr = r['wins']/r['total']*100
                avg = sum(rets)/len(rets)
                med = rets[len(rets)//2]
                monthly = avg * (TRADING_DAYS_PER_YEAR / 12 / FORWARD_DAYS)
                yearly = avg * (TRADING_DAYS_PER_YEAR / FORWARD_DAYS)
                print(f'{n:>6} {r["total"]:>6} {wr:>7.1f}% {avg:>+8.2f}% '
                      f'{monthly:>+7.2f}% {yearly:>+7.2f}% '
                      f'{med:>+8.2f}% {max(rets):>+8.2f}% {min(rets):>+8.2f}%')
    
    print_results('📊 无过滤（全部交易日）', all_res, len(eval_days))
    print_results('📈 上升趋势过滤', up_res, len(up_days))
    
    # 对比
    print(f'\n{"="*75}')
    print('对比: 上升趋势过滤 vs 无过滤 (Top3)')
    print(f'{"="*75}')
    a3, u3 = all_res[3], up_res[3]
    if a3['total'] > 0 and u3['total'] > 0:
        wr_improve = (u3['wins']/u3['total'] - a3['wins']/a3['total']) * 100
        ret_improve = (sum(u3['ret_list'])/len(u3['ret_list']) - sum(a3['ret_list'])/len(a3['ret_list']))
        print(f'  胜率:  {a3["wins"]/a3["total"]*100:.1f}% → {u3["wins"]/u3["total"]*100:.1f}% ({wr_improve:+.1f}pt)')
        print(f'  均收益: {sum(a3["ret_list"])/len(a3["ret_list"]):+.2f}% → {sum(u3["ret_list"])/len(u3["ret_list"]):+.2f}% ({ret_improve:+.2f}pt)')
        print(f'  信号数: {a3["total"]} → {u3["total"]} (减少{a3["total"]-u3["total"]}天)')


if __name__ == '__main__':
    main()
