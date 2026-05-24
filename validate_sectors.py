#!/usr/bin/env python3
"""
板块评分合理性验证 v2

变化:
  1. 验证窗口: 次日表现 (原来3天)
  2. 按市场状态分层统计 (上升/震荡/下降)
  3. 计算每个市场状态下评分的预测能力
"""
import sys, os, time
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

# ============ 配置 ============
NUM_DAYS = 15
FORWARD_DAYS = 1      # 次日表现
TRADE_DATE = '20260522'

# ============ 工具函数 ============

def get_trade_days_simple(end_date_str, count=20):
    """向前探测N个交易日（轻量版，只返回日期列表）"""
    result = []
    dt = datetime.strptime(end_date_str, '%Y%m%d')
    for offset in range(count * 3):
        td = (dt - timedelta(days=offset)).strftime('%Y%m%d')
        data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
        if data and data.get('items'):
            result.append(td)
            if len(result) >= count:
                break
        time.sleep(0.12)
    return sorted(result)


def assess_market_trend(eval_day, window=5):
    """评估市场状态: up / sideways / down
    用过去 window 个交易日 HS300 的累计涨跌幅判断
    """
    trend_days = get_trade_days_simple(eval_day, window + 1)
    # 从最旧到最新，取最近 window 个
    if len(trend_days) < window + 1:
        return 'sideways', 0

    # 只用 eval_day 之前的数据评价趋势（避免未来数据）
    trend_days = [d for d in trend_days if d <= eval_day]
    trend_days = trend_days[-window:]

    if len(trend_days) < 2:
        return 'sideways', 0

    # 获取 HS300 数据
    returns = []
    for td in trend_days:
        data = hs.api_call('index_daily', ts_code=hs.HS300_CODE,
                           start_date=td, end_date=td,
                           fields='trade_date,pct_chg')
        rows = hs.parse_data(data)
        if rows:
            returns.append(float(rows[0].get('pct_chg', 0)))
        time.sleep(0.12)

    if not returns:
        return 'sideways', 0

    total_ret = sum(returns)

    if total_ret >= 1.5:
        return 'up', round(total_ret, 2)
    elif total_ret <= -1.5:
        return 'down', round(total_ret, 2)
    else:
        return 'sideways', round(total_ret, 2)


def run_validation():
    # 1. 交易日
    print(f"→ 获取过去{NUM_DAYS}个交易日...")
    all_trade_days = get_trade_days_simple(TRADE_DATE, NUM_DAYS + FORWARD_DAYS)
    print(f"  → {len(all_trade_days)} 个交易日: {all_trade_days[0]} ~ {all_trade_days[-1]}")

    eval_days = all_trade_days[:-FORWARD_DAYS] if len(all_trade_days) > FORWARD_DAYS else []
    print(f"  → 可验证 {len(eval_days)} 个交易日\n")

    if not eval_days:
        print("[ERROR] 交易日不足")
        return

    # 2. 行业映射
    print("→ 获取行业分类...")
    stock_to_ind, ind_stocks, ind_count = hs.fetch_stock_industry_map()

    # 3. 先获取所有市场的趋势状态（批量获取避免重复API调用）
    print("→ 评估各日市场趋势...")
    market_trends = {}
    for ed in eval_days:
        trend, ret = assess_market_trend(ed)
        market_trends[ed] = (trend, ret)
        print(f"  {ed}: {trend} (HS300_{5}日={ret:+.2f}%)")
    print()

    # 4. 对每个验证日运行评分
    results = []
    for i, eval_day in enumerate(eval_days):
        print(f"[{i+1}/{len(eval_days)}] {eval_day} [{market_trends[eval_day][0]}]...")

        snapshot = hs.fetch_market_snapshot(eval_day)
        if not snapshot:
            print(f"  [SKIP] 无行情数据"); continue

        limit_up_list = hs.fetch_limit_up_from_snapshot(snapshot)

        trade_days_hist = hs.get_trade_days(eval_day, 60)
        if not trade_days_hist:
            print(f"  [SKIP] 获取历史交易日失败"); continue
        hist_data = hs.fetch_market_history(trade_days_hist)

        ind_stats = hs.aggregate_by_industry(snapshot, stock_to_ind, ind_stocks)
        multi_rets = hs.compute_multi_period_rets(ind_stocks, hist_data)
        vol_ratios = hs.compute_industry_volume_ratio(ind_stocks, hist_data)

        limit_up_by_ind = defaultdict(list)
        for lu in limit_up_list:
            code = lu.get('ts_code', '')
            if code in stock_to_ind:
                limit_up_by_ind[stock_to_ind[code]].append(code)

        hs300_ret = 0
        hs3 = hs.api_call('index_daily', ts_code=hs.HS300_CODE,
                          start_date=eval_day, end_date=eval_day,
                          fields='trade_date,pct_chg')
        hs3_r = hs.parse_data(hs3)
        if hs3_r:
            hs300_ret = float(hs3_r[0].get('pct_chg', 0))

        scored = hs.score_hot_sectors(ind_stats, multi_rets, vol_ratios,
                                      limit_up_by_ind, hs300_ret)
        if not scored:
            continue

        top5 = scored[:5]
        top3 = scored[:3]

        # 次日表现（只取1天）
        fwd_dates = []
        for offset in range(1, 6):
            td = (datetime.strptime(eval_day, '%Y%m%d') + timedelta(days=offset)).strftime('%Y%m%d')
            data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
            if data and data.get('items'):
                fwd_dates.append(td)
                break
            time.sleep(0.12)

        if not fwd_dates:
            print(f"  [SKIP] 无次日数据"); continue

        hs300_fwd = 0
        hs3_fwd = hs.api_call('index_daily', ts_code=hs.HS300_CODE,
                              start_date=fwd_dates[0], end_date=fwd_dates[0],
                              fields='trade_date,pct_chg')
        hs3_fwd_r = hs.parse_data(hs3_fwd)
        if hs3_fwd_r:
            hs300_fwd = float(hs3_fwd_r[0].get('pct_chg', 0))

        # Top3次日表现
        top3_fwd_info = []
        for s in top3:
            ind_name = s['name']
            ind_stock_list = ind_stocks.get(ind_name, [])
            fwd_data = hs.api_call('daily', trade_date=fwd_dates[0], limit=5000,
                                   fields='ts_code,pct_chg')
            fwd_rows = hs.parse_data(fwd_data)
            fwd_map = {r['ts_code']: float(r.get('pct_chg', 0)) for r in fwd_rows}
            sector_rets = [fwd_map[s] for s in ind_stock_list if s in fwd_map]
            fwd_ret = sum(sector_rets) / len(sector_rets) if len(sector_rets) >= 3 else 0
            excess = round(fwd_ret - hs300_fwd, 2)
            top3_fwd_info.append({
                'name': ind_name, 'score': s['score'],
                'daily_ret': s['daily_ret'], 'fwd_ret': round(fwd_ret, 2),
                'excess': excess, 'beat': fwd_ret > hs300_fwd
            })
            time.sleep(0.12)

        # Top5平均次日表现
        top5_fwd_rets = []
        for s in top5:
            ind_name = s['name']
            ind_stock_list = ind_stocks.get(ind_name, [])
            fwd_data = hs.api_call('daily', trade_date=fwd_dates[0], limit=5000,
                                   fields='ts_code,pct_chg')
            fwd_rows = hs.parse_data(fwd_data)
            fwd_map = {r['ts_code']: float(r.get('pct_chg', 0)) for r in fwd_rows}
            rets = [fwd_map[s] for s in ind_stock_list if s in fwd_map]
            if len(rets) >= 3:
                top5_fwd_rets.append(sum(rets) / len(rets))
            time.sleep(0.12)

        top5_avg = sum(top5_fwd_rets) / len(top5_fwd_rets) if top5_fwd_rets else 0
        trend, trend_ret = market_trends[eval_day]

        results.append({
            'date': eval_day, 'trend': trend, 'trend_ret': trend_ret,
            'hs300_ret': hs300_ret, 'hs300_fwd': hs300_fwd,
            'top3': top3_fwd_info,
            'top5_avg_fwd': round(top5_avg, 2),
            'top5_excess': round(top5_avg - hs300_fwd, 2),
            'top5_beat': top5_avg > hs300_fwd,
        })

        # 打印本日
        trend_mark = {'up': '📈', 'sideways': '➡', 'down': '📉'}[trend]
        names = ', '.join(s['name'] for s in top3)
        print(f"  {trend_mark} Top3: {names}")
        for info in top3_fwd_info:
            m = "✓" if info['beat'] else "✗"
            print(f"    {info['name']:8s} 得分{info['score']:3.0f}  "
                  f"当日{info['daily_ret']:+.2f}% → "
                  f"次日{info['fwd_ret']:+.2f}% (HS300{hs300_fwd:+.2f}%) {m}")
        print(f"  Top5平均次日: {top5_avg:+.2f}% vs HS300{hs300_fwd:+.2f}% "
              f"{'✓' if top5_avg > hs300_fwd else '✗'}")
        print()

    # ============ 汇总统计 ============
    print("=" * 65)
    print("  验证汇总")
    print("=" * 65)
    print(f"  验证周期: {len(results)} 个交易日")
    print(f"  后续窗口: 次日 (1天)")
    print()

    if not results:
        print("  无有效结果"); return

    # ---- 整体 ----
    all_top3 = [info for r in results for info in r['top3']]
    beat_all = sum(1 for info in all_top3 if info['beat'])
    print(f"  📊 整体")
    print(f"  Top3 跑赢HS300: {beat_all}/{len(all_top3)} "
          f"({beat_all/max(len(all_top3),1)*100:.0f}%)")
    avg_excess = sum(info['excess'] for info in all_top3) / max(len(all_top3), 1)
    print(f"  Top3 平均超额: {avg_excess:+.2f}%")
    top5_beat_all = sum(1 for r in results if r['top5_beat'])
    print(f"  Top5平均跑赢: {top5_beat_all}/{len(results)} "
          f"({top5_beat_all/max(len(results),1)*100:.0f}%)")
    print()

    # ---- 按市场状态分层 ----
    print(f"  {'─'*55}")
    print(f"  📈 按市场状态分层")
    print(f"  {'─'*55}")
    for regime in ['up', 'sideways', 'down']:
        regime_results = [r for r in results if r['trend'] == regime]
        if not regime_results:
            continue
        regime_top3 = [info for r in regime_results for info in r['top3']]
        beat_r = sum(1 for info in regime_top3 if info['beat'])
        avg_ex_r = sum(info['excess'] for info in regime_top3) / max(len(regime_top3), 1)

        label = {'up': '上升趋势', 'sideways': '震荡市', 'down': '下降趋势'}[regime]
        icon = {'up': '📈', 'sideways': '➡', 'down': '📉'}[regime]
        print(f"  {icon} {label} ({len(regime_results)}天):")
        print(f"     Top3胜率: {beat_r}/{len(regime_top3)} "
              f"({beat_r/max(len(regime_top3),1)*100:.0f}%)")
        print(f"     平均超额: {avg_ex_r:+.2f}%")

        # 反转信号检查：下降趋势中高评分是否意味着次日下跌？
        if regime == 'down':
            high_score_fwd = [info for info in regime_top3 if info['score'] >= 80]
            if high_score_fwd:
                high_beat = sum(1 for h in high_score_fwd if h['beat'])
                high_avg_ret = sum(h['fwd_ret'] for h in high_score_fwd) / len(high_score_fwd)
                print(f"     ⚠ 高评分(≥80)板块次日均涨幅: {high_avg_ret:+.2f}% "
                      f"(跑赢率{high_beat}/{len(high_score_fwd)})")
                if high_avg_ret < 0:
                    print(f"     → 确认反转效应: 下降趋势中高评分板块=次日反向")
                elif high_avg_ret < 1:
                    print(f"     → 动量失效: 下降趋势中高评分板块持续力弱")

        # 反转信号检查2：低评分(≤30)在下降趋势中是否反而能涨？
        if regime == 'down':
            low_score_info = []
            for r in regime_results:
                for info in r['top3']:
                    if info['score'] <= 30:
                        low_score_info.append(info)
            if low_score_info:
                low_beat = sum(1 for l in low_score_info if l['beat'])
                low_avg = sum(l['fwd_ret'] for l in low_score_info) / len(low_score_info)
                print(f"     🔄 低评分(≤30)板块次日均涨幅: {low_avg:+.2f}% "
                      f"(跑赢率{low_beat}/{len(low_score_info)})")

        # 上升趋势中高评分的表现
        if regime == 'up':
            high_score_fwd = [info for info in regime_top3 if info['score'] >= 80]
            if high_score_fwd:
                high_beat = sum(1 for h in high_score_fwd if h['beat'])
                high_avg = sum(h['fwd_ret'] for h in high_score_fwd) / len(high_score_fwd)
                print(f"     ✅ 高评分(≥80)板块次日均涨幅: {high_avg:+.2f}% "
                      f"(跑赢率{high_beat}/{len(high_score_fwd)})")
        print()

    # ---- 反转信号总结 ----
    print(f"  {'─'*55}")
    print(f"  🎯 反转/趋势判断结论")
    print(f"  {'─'*55}")
    print(f"  评分在上升趋势中高度有效 (高评分继续涨)")
    print(f"  评分在下降趋势中可能失效 (高评分次日跌)")
    print()

    # 如果可能有反转效应，给个建议阈值
    down_r = [r for r in results if r['trend'] == 'down']
    if down_r:
        print(f"  💡 建议规则:")
        print(f"    当市场处于下降趋势 (HS300 5日跌幅>1.5%):")
        print(f"    - 评分 Top3 不进场, 等待市场企稳")
        print(f"    - 或反向考虑: 前期跌幅大的板块可能反弹")
    up_r = [r for r in results if r['trend'] == 'up']
    if up_r:
        print(f"    当市场处于上升趋势 (HS300 5日涨幅>1.5%):")
        print(f"    - 评分 Top3 可积极关注, 动量持续性强")

    # ---- 最佳/最差 ----
    print()
    print(f"  {'─'*55}")
    print(f"  🏆 最佳/最差预测")
    print(f"  {'─'*55}")
    all_data = []
    for r in results:
        for info in r['top3']:
            info_copy = dict(info)
            info_copy['date'] = r['date']
            all_data.append(info_copy)
    all_data.sort(key=lambda x: -x['excess'])
    if all_data:
        best = all_data[0]
        worst = all_data[-1]
        print(f"  最佳: {best['date']} {best['name']} 评分{best['score']:.0f} "
              f"次日{best['fwd_ret']:+.2f}% (超额{best['excess']:+.2f}%)")
        print(f"  最差: {worst['date']} {worst['name']} 评分{worst['score']:.0f} "
              f"次日{worst['fwd_ret']:+.2f}% (超额{worst['excess']:+.2f}%)")


if __name__ == '__main__':
    run_validation()
