#!/usr/bin/env python3
"""
6个月板块评分回测 (v2 - 优化版)

优化: 一次性拉取所有历史数据，共享给每个验证日
避免每天重复fetch 60天历史(7,200次API → 180次API)
"""
import sys, os, time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

# ============ 配置 ============
END_DATE = '20260522'       # 最新交易日
LOOKBACK_MONTHS = 6         # 回看6个月
FORWARD_DAYS = 1            # 次日表现

# ============ 获取所有交易日 ============

def get_all_trade_days(end_date, count=180):
    """获取 count 个交易日（从最新往前找）"""
    result = []
    dt = datetime.strptime(end_date, '%Y%m%d')
    checked = 0
    while len(result) < count and checked < count * 3:
        td = (dt - timedelta(days=checked)).strftime('%Y%m%d')
        data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
        if data and data.get('items'):
            result.append(td)
        checked += 1
        time.sleep(0.08)
    return sorted(result)


def get_forward_dates(eval_day, all_days):
    """从 all_days 中找到 eval_day 后面的天数"""
    idx = all_days.index(eval_day)
    return all_days[idx+1:idx+1+FORWARD_DAYS] if idx + FORWARD_DAYS < len(all_days) else []


def assess_trend_from_ma(closes):
    """用 MA10 vs MA20 判断趋势 (与原算法一致)"""
    if len(closes) < 20:
        return 'sideways', 0
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    if ma10 > ma20 * 1.002:
        return 'up', round((ma10 - ma20) / ma20 * 100, 2)
    elif ma10 < ma20 * 0.998:
        return 'down', round((ma10 - ma20) / ma20 * 100, 2)
    else:
        return 'sideways', round((ma10 - ma20) / ma20 * 100, 2)


# ============ 主流程 ============

def run_backtest():
    print(f"🔍 6个月板块评分回测")
    print(f"   {END_DATE} 往前 {LOOKBACK_MONTHS} 个月")
    print(f"   验证窗口: 次日 ({FORWARD_DAYS}天)")
    print()

    # 1. 获取交易日列表
    print("→ 获取交易日列表...")
    # 预估交易天数: 6个月 ≈ 120个交易日 + 60个历史日
    all_trade_days = get_all_trade_days(END_DATE, 180)
    print(f"  ✓ {len(all_trade_days)} 个交易日: {all_trade_days[0]} ~ {all_trade_days[-1]}")

    if len(all_trade_days) < 60:
        print("[ERROR] 交易日不足"); return

    # eval_days = 所有有次日数据的交易日
    eval_days = [d for d in all_trade_days if d != all_trade_days[-1]]
    print(f"  → 可验证 {len(eval_days)} 个交易日")

    # 2. 获取行业映射
    print("\n→ 获取行业分类...")
    stock_to_ind, ind_stocks, ind_count = hs.fetch_stock_industry_map()

    # 使用 L1 一级行业
    print("  → 归并到申万一级行业...")
    stock_to_ind, ind_stocks, ind_count = hs.remap_industries_to_l1(
        stock_to_ind, ind_stocks, ind_count)

    # 3. 一次性获取历史行情 (前60天 ~ 最新日)
    earliest_needed = all_trade_days[-1 - 60]  # 最早一个验证日前60天
    hist_dates = [d for d in all_trade_days if d >= earliest_needed][:60]
    # 再加所有eval_days (作为当日行情)
    all_hist_dates = sorted(set(hist_dates + eval_days))

    print(f"\n→ 批量获取历史行情 ({len(all_hist_dates)}天)...")
    historical_data = {}
    for i, td in enumerate(all_hist_dates):
        if i % 20 == 0:
            print(f"  [进度] {i+1}/{len(all_hist_dates)} ({td})")
        data = hs.api_call('daily', trade_date=td, limit=5000,
                           fields='ts_code,close,pct_chg,vol')
        rows = hs.parse_data(data)
        if rows:
            historical_data[td] = rows
        time.sleep(0.08)

    print(f"  ✓ {len(historical_data)} 天数据")

    # 4. 获取HS300日线
    print("\n→ 获取HS300基准...")
    hs300_data = {}
    for td in all_hist_dates:
        data = hs.api_call('index_daily', ts_code=hs.HS300_CODE,
                           start_date=td, end_date=td,
                           fields='trade_date,close,pct_chg')
        rows = hs.parse_data(data)
        if rows:
            hs300_data[td] = {
                'close': float(rows[0].get('close', 0)),
                'pct': float(rows[0].get('pct_chg', 0))
            }
        time.sleep(0.08)
    print(f"  ✓ {len(hs300_data)} 天")

    # 5. 对每个验证日运行评分
    print(f"\n{'='*60}")
    print(f"  开始回测 {len(eval_days)} 个交易日")
    print(f"{'='*60}\n")

    results = []
    for i, eval_day in enumerate(eval_days):
        if (i+1) % 20 == 0:
            print(f"  → 进度: {i+1}/{len(eval_days)} ({i/len(eval_days)*100:.0f}%)")

        # 当日行情
        snapshot_data = historical_data.get(eval_day)
        if not snapshot_data:
            continue

        # 历史子集: 该日往前60天
        day_idx = all_hist_dates.index(eval_day)
        hist_start = max(0, day_idx - 60)
        hist_subset_dates = all_hist_dates[hist_start:day_idx+1]
        hist_subset = {d: historical_data[d] for d in hist_subset_dates if d in historical_data}
        if len(hist_subset) < 5:
            continue

        # 涨停
        limit_up_list = hs.fetch_limit_up_from_snapshot(snapshot_data)

        # 行业聚合
        ind_stats = hs.aggregate_by_industry(snapshot_data, stock_to_ind, ind_stocks)
        if not ind_stats:
            continue

        multi_rets = hs.compute_multi_period_rets(ind_stocks, hist_subset)
        vol_ratios = hs.compute_industry_volume_ratio(ind_stocks, hist_subset)

        limit_up_by_ind = defaultdict(list)
        for lu in limit_up_list:
            code = lu.get('ts_code', '')
            if code in stock_to_ind:
                limit_up_by_ind[stock_to_ind[code]].append(code)

        # HS300当日
        hs300_ret = hs300_data.get(eval_day, {}).get('pct', 0)

        # 评分
        scored = hs.score_hot_sectors(ind_stats, multi_rets, vol_ratios,
                                      limit_up_by_ind, hs300_ret)
        if not scored or len(scored) < 3:
            continue

        top3 = scored[:3]
        top5 = scored[:5]

        # 次日表现
        fwd_dates = get_forward_dates(eval_day, all_trade_days)
        if not fwd_dates:
            continue
        fwd_date = fwd_dates[0]

        hs300_fwd = hs300_data.get(fwd_date, {}).get('pct', 0)

        # Top3次日收益
        fwd_data = historical_data.get(fwd_date)
        if not fwd_data:
            continue
        fwd_map = {r['ts_code']: float(r.get('pct_chg', 0)) for r in fwd_data}

        top3_fwd = []
        for s in top3:
            ind_name = s['name']
            stocks = ind_stocks.get(ind_name, [])
            rets = [fwd_map[s] for s in stocks if s in fwd_map]
            if len(rets) < 3:
                continue
            avg = sum(rets) / len(rets)
            top3_fwd.append({
                'name': ind_name, 'score': s['score'],
                'daily_ret': s['daily_ret'],
                'fwd_ret': round(avg, 2),
                'excess': round(avg - hs300_fwd, 2),
                'beat': avg > hs300_fwd
            })

        if len(top3_fwd) < 3:
            continue

        # Top5次日平均
        top5_rets = []
        for s in top5:
            ind_name = s['name']
            stocks = ind_stocks.get(ind_name, [])
            rets = [fwd_map[s] for s in stocks if s in fwd_map]
            if len(rets) >= 3:
                top5_rets.append(sum(rets)/len(rets))

        top5_avg = sum(top5_rets)/len(top5_rets) if top5_rets else 0

        # 趋势 (MA10/MA20 交叉)
        hs300_closes = [hs300_data.get(d, {}).get('close', 0) for d in all_hist_dates
                       if d in hs300_data and d <= eval_day]
        trend, trend_ret = assess_trend_from_ma(hs300_closes)

        results.append({
            'date': eval_day, 'trend': trend, 'trend_ret': trend_ret,
            'hs300_ret': hs300_ret, 'hs300_fwd': hs300_fwd,
            'top3_scores': [s['score'] for s in top3],
            'top3_names': [s['name'] for s in top3],
            'top3_fwd': top3_fwd,
            'top5_avg_fwd': round(top5_avg, 2),
            'top5_excess': round(top5_avg - hs300_fwd, 2),
            'top5_beat': top5_avg > hs300_fwd,
        })

    # ============ 汇总统计 ============
    print(f"\n{'='*65}")
    print(f"  6个月板块评分回测报告")
    print(f"  {all_trade_days[0]} ~ {all_trade_days[-1]}")
    print(f"{'='*65}")
    print(f"  验证天数: {len(results)}")
    print(f"  验证窗口: 次日 ({FORWARD_DAYS}天)")
    print(f"  行业级别: 申万一级 (31个)")
    print()

    # ---- 整体 ----
    all_top3 = [info for r in results for info in r['top3_fwd']]
    beat_all = sum(1 for info in all_top3 if info['beat'])
    avg_ex = sum(info['excess'] for info in all_top3) / max(len(all_top3), 1)
    print(f"  📊 整体表现")
    print(f"  {'─'*50}")
    print(f"  Top3 跑赢HS300: {beat_all}/{len(all_top3)} "
          f"({beat_all/max(len(all_top3),1)*100:.0f}%)")
    print(f"  Top3 平均超额收益: {avg_ex:+.2f}%")
    top5_beat_all = sum(1 for r in results if r['top5_beat'])
    print(f"  Top5 平均跑赢HS300: {top5_beat_all}/{len(results)} "
          f"({top5_beat_all/max(len(results),1)*100:.0f}%)")
    print()

    # ---- 按市场状态分层 ----
    print(f"  📈 按市场状态分层")
    print(f"  {'─'*50}")
    for regime, label in [('up', '上升趋势'), ('sideways', '震荡市'), ('down', '下降趋势')]:
        rr = [r for r in results if r['trend'] == regime]
        if not rr:
            continue
        r_top3 = [info for r in rr for info in r['top3_fwd']]
        beat_r = sum(1 for info in r_top3 if info['beat'])
        avg_ex_r = sum(info['excess'] for info in r_top3) / max(len(r_top3), 1)

        icon = {'up': '📈', 'sideways': '➡', 'down': '📉'}[regime]
        print(f"  {icon} {label} ({len(rr)}天, {len(r_top3)}样本):")
        print(f"     胜率: {beat_r}/{len(r_top3)} ({beat_r/max(len(r_top3),1)*100:.0f}%)")
        print(f"     超额: {avg_ex_r:+.2f}%")

        # 高评分分析
        high = [info for info in r_top3 if info['score'] >= 80]
        if high:
            h_beat = sum(1 for h in high if h['beat'])
            h_ret = sum(h['fwd_ret'] for h in high) / len(high)
            print(f"     高评分(≥80): {h_beat}/{len(high)} "
                  f"({h_beat/max(len(high),1)*100:.0f}%), 均涨幅 {h_ret:+.2f}%")

        # 低评分分析（下降趋势中）
        if regime == 'down':
            low = [info for info in r_top3 if info['score'] <= 40]
            if low:
                l_beat = sum(1 for l in low if l['beat'])
                l_ret = sum(l['fwd_ret'] for l in low) / len(low)
                print(f"     低评分(≤40): {l_beat}/{len(low)} "
                      f"({l_beat/max(len(low),1)*100:.0f}%), 均涨幅 {l_ret:+.2f}%")
        print()

    # ---- 月度表现 ----
    print(f"  📅 月度表现")
    print(f"  {'─'*50}")
    by_month = defaultdict(list)
    for r in results:
        month = r['date'][:6]
        by_month[month].append(r)
    for month in sorted(by_month.keys()):
        mr = by_month[month]
        m_top3 = [info for r in mr for info in r['top3_fwd']]
        m_beat = sum(1 for info in m_top3 if info['beat'])
        m_ex = sum(info['excess'] for info in m_top3) / max(len(m_top3), 1)
        trend_counts = defaultdict(int)
        for r in mr:
            trend_counts[r['trend']] += 1
        t_str = ' '.join(f"{icon}{cnt}" for icon, label in [('📈','up'),('➡','sideways'),('📉','down')]
                        for regime, cnt in [(label, trend_counts.get(label,0))])
        # simplified
        t_parts = []
        if trend_counts.get('up', 0): t_parts.append(f"📈{trend_counts['up']}")
        if trend_counts.get('sideways', 0): t_parts.append(f"➡{trend_counts['sideways']}")
        if trend_counts.get('down', 0): t_parts.append(f"📉{trend_counts['down']}")
        print(f"  {month}  {m_beat}/{len(m_top3)} ({m_beat/max(len(m_top3),1)*100:.0f}%)  "
              f"超额{m_ex:+.2f}%  {' '.join(t_parts)}")

    # ---- 最佳/最差预测 ----
    print()
    print(f"  🏆 最佳/最差预测")
    print(f"  {'─'*50}")
    all_info = []
    for r in results:
        for info in r['top3_fwd']:
            info['date'] = r['date']
            all_info.append(info)
    all_info.sort(key=lambda x: -x['excess'])
    for top in [all_info[0], all_info[1], all_info[-2], all_info[-1]]:
        m = '✓' if top['beat'] else '✗'
        print(f"  {top['date']} {top['name']:8s} 评分{top['score']:.0f}  "
              f"当日{top['daily_ret']:+.2f}% → 次日{top['fwd_ret']:+.2f}% "
              f"(超额{top['excess']:+.2f}%) {m}")
    print()

    # ---- 结论 ----
    print(f"  {'─'*50}")
    print(f"  📌 结论")
    print(f"  {'─'*50}")
    # 综合结论
    up_days = len([r for r in results if r['trend'] == 'up'])
    down_days = len([r for r in results if r['trend'] == 'down'])
    sideways_days = len([r for r in results if r['trend'] == 'sideways'])
    print(f"  市场分布: 📈{up_days}天 ➡{sideways_days}天 📉{down_days}天")

    up_top3 = [info for r in results if r['trend']=='up' for info in r['top3_fwd']]
    up_beat = sum(1 for info in up_top3 if info['beat'])
    up_rate = up_beat/max(len(up_top3),1)*100

    down_top3 = [info for r in results if r['trend']=='down' for info in r['top3_fwd']]
    down_beat = sum(1 for info in down_top3 if info['beat'])
    down_rate = down_beat/max(len(down_top3),1)*100

    print(f"  上升趋势胜率: {up_rate:.0f}%  {'✅ 有效' if up_rate > 60 else '➡ 一般'}")
    print(f"  下降趋势胜率: {down_rate:.0f}%  {'❌ 回避' if down_rate < 45 else '➡ 一般'}")

    if down_rate < 45:
        print(f"\n  ⚠️ 核心结论: 上升趋势中使用评分, 下降趋势中禁用评分")
        print(f"     当 HS300 5日跌幅 > 1.5% 时, 评分 Top3 不操作")


if __name__ == '__main__':
    run_backtest()
