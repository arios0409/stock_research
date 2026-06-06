#!/usr/bin/env python3
"""
A股同花顺概念板块扫描器
=========================
基于Tushare ths_index / ths_daily 接口，扫描热门概念板块。
数据源: Tushare Pro
依赖: 无(仅urllib+json，标准库)

用法:
  python3 ths_concept_scanner.py                   # 最近交易日
  python3 ths_concept_scanner.py 20260605           # 指定日期
  python3 ths_concept_scanner.py 20260605 --quick   # 快速模式(只用当日)
  python3 ths_concept_scanner.py 20260605 --csv     # 保存CSV
  python3 ths_concept_scanner.py 20260605 --top 20  # 显示前20
"""

import urllib.request
import json
import time
import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict

# ============ 配置 ============
TUSHARE_TOKEN='0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, '.cache')
os.makedirs(CACHE_DIR, exist_ok=True)

HS300_CODE = '000300.SH'

# 过滤掉宽基指数类"概念"（沪深300样本股等）
EXCLUDE_CONCEPT_TYPES = {'300', '50', '180', '380', '500', '688', '1000'}


# ============ Tushare API ============

def api_call(api_name, fields=None, **kwargs):
    """单次Tushare API调用，带简单重试"""
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields:
        payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data,
                                 headers={'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('code') != 0:
                code = result.get('code')
                msg = result.get('msg', '')
                # 频率超限 → 等待后重试
                if '频率' in msg or 'limit' in msg.lower():
                    wait = 65 if attempt == 0 else 125
                    print(f"  [限速] {api_name}: 等待{wait}s后重试...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"  [API Error] {api_name}: {msg}", file=sys.stderr)
                return None
            return result.get('data')
        except Exception as e:
            print(f"  [API Exception] {api_name}: {e}", file=sys.stderr)
            if attempt < 2:
                time.sleep(2)
    return None


def parse_data(data):
    if not data or 'fields' not in data or 'items' not in data:
        return []
    fields = data['fields']
    return [dict(zip(fields, item)) for item in data['items']]


# ============ 概念列表（带缓存） ============

def fetch_ths_concepts(force_refresh=False):
    """获取同花顺概念板块列表（缓存24小时）"""
    cache_path = os.path.join(CACHE_DIR, 'ths_concepts.json')

    # 尝试读缓存
    if not force_refresh and os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < 86400:  # 24h
            with open(cache_path, 'r') as f:
                cached = json.load(f)
            concepts = cached.get('concepts', [])
            if concepts:
                print(f"  [缓存] 加载 {len(concepts)} 个概念板块",
                      file=sys.stderr)
                return concepts

    print("  [进度] 获取同花顺概念板块列表...", file=sys.stderr)
    data = api_call('ths_index', exchange='A', type='N',
                    fields='ts_code,name,type,list_date,desc')
    rows = parse_data(data)
    if not rows:
        print("  [ERROR] ths_index 获取失败", file=sys.stderr)
        return []

    concepts = []
    for r in rows:
        code = r.get('ts_code', '')
        name = r.get('name', '')
        ctype = r.get('type', '')
        # 过滤宽基指数
        if ctype in EXCLUDE_CONCEPT_TYPES:
            continue
        concepts.append({
            'code': code,
            'name': name,
            'type': ctype,
        })

    # 写缓存
    with open(cache_path, 'w') as f:
        json.dump({'concepts': concepts, 'updated': time.time()}, f)

    print(f"  [结果] {len(concepts)} 个概念板块 (已过滤宽基指数)",
          file=sys.stderr)
    return concepts


# ============ 交易日探测 ============

def find_last_trade_day(target_date=None):
    """Forward probe for last trade day using trade_cal API"""
    ref = datetime.strptime(target_date, '%Y%m%d') if target_date else datetime.now()
    start = (ref - timedelta(days=15)).strftime('%Y%m%d')
    end = ref.strftime('%Y%m%d')
    data = api_call('trade_cal', exchange='SSE',
                    start_date=start, end_date=end,
                    fields='cal_date,is_open')
    rows = parse_data(data)
    if rows:
        open_days = [r['cal_date'] for r in rows if r.get('is_open') == 1]
        open_days.sort(reverse=True)
        if open_days:
            return open_days[0]
    return ref.strftime('%Y%m%d')


def get_trade_days(end_date_str, count=60):
    """Get recent N trade days using trade_cal"""
    end_dt = datetime.strptime(end_date_str, '%Y%m%d')
    start = (end_dt - timedelta(days=max(count * 3, 90))).strftime('%Y%m%d')
    data = api_call('trade_cal', exchange='SSE',
                    start_date=start, end_date=end_date_str,
                    fields='cal_date,is_open')
    rows = parse_data(data)
    if rows:
        trade_days = [r['cal_date'] for r in rows if r.get('is_open') == 1]
        trade_days.sort()
        return trade_days[-count:] if len(trade_days) >= count else trade_days
    return []


# ============ 概念行情获取 ============

def fetch_concept_daily_batch(trade_date):
    """
    批量获取某日所有概念板块行情。
    返回: {concept_code: {pct_chg, close, vol, amount}}
    """
    print(f"  [进度] {trade_date} 概念板块行情...", file=sys.stderr)
    data = api_call('ths_daily', trade_date=trade_date, limit=5000,
                    fields='ts_code,close,pct_chg,vol,amount')
    rows = parse_data(data)
    result = {}
    for r in rows:
        code = r.get('ts_code', '')
        result[code] = {
            'pct_chg': float(r.get('pct_chg', 0)),
            'close': float(r.get('close', 0)),
            'vol': float(r.get('vol', 0)),
            'amount': float(r.get('amount', 0)),
        }
    print(f"  [结果] {len(result)} 个概念有行情", file=sys.stderr)
    return result


def fetch_concept_history(trade_dates):
    """
    获取多个交易日所有概念行情（用于RPS和量比计算）。
    返回: {trade_date: {code: {pct_chg, vol}}}
    """
    result = {}
    total = len(trade_dates)
    for i, td in enumerate(trade_dates):
        if i % 10 == 0:
            print(f"  [进度] 历史行情 {i+1}/{total} ({td})", file=sys.stderr)
        data = api_call('ths_daily', trade_date=td, limit=5000,
                        fields='ts_code,pct_chg,vol')
        rows = parse_data(data)
        if rows:
            result[td] = {}
            for r in rows:
                code = r.get('ts_code', '')
                result[td][code] = {
                    'pct_chg': float(r.get('pct_chg', 0)),
                    'vol': float(r.get('vol', 0)),
                }
        time.sleep(0.15)
    return result


def fetch_hs300_ret(trade_date):
    """获取沪深300当日涨跌幅"""
    data = api_call('index_daily', ts_code=HS300_CODE,
                    start_date=trade_date, end_date=trade_date,
                    fields='trade_date,pct_chg')
    rows = parse_data(data)
    if rows:
        return float(rows[0].get('pct_chg', 0))
    return 0


# ============ 指标计算 ============

def compute_rps(values):
    """百分位排名"""
    n = len(values)
    if n == 0:
        return []
    sorted_vals = sorted(set(values))
    rank_map = {v: (i + 1) / n * 100 for i, v in enumerate(sorted_vals)}
    return [rank_map.get(v, 0) for v in values]


def minmax_norm(values):
    """最小-最大归一化到0-100"""
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [50.0] * len(values)
    return [(v - mn) / (mx - mn) * 100 for v in values]


def compute_concept_metrics(concepts, daily_data, history_data, latest_date):
    """
    计算所有概念的多维度指标。

    返回: [{code, name, daily_ret, rps_5d, rps_20d, vol_ratio, ret_5d, ret_20d}]
    """
    trade_dates = sorted(history_data.keys())
    if len(trade_dates) < 2:
        return []

    # 确定参考日期
    date_idx_5 = max(0, len(trade_dates) - 6)
    date_idx_20 = max(0, len(trade_dates) - 21)
    date_5 = trade_dates[date_idx_5]
    date_20 = trade_dates[date_idx_20]
    past_dates = trade_dates[:-1][-20:]  # 用于量比

    results = []
    for c in concepts:
        code = c['code']
        name = c['name']

        daily = daily_data.get(code, {})
        daily_ret = daily.get('pct_chg', 0)

        # 5日/20日收益
        ret_5d = 0
        ret_20d = 0
        if code in history_data.get(latest_date, {}):
            latest_close_data = None
            close_5_data = None
            close_20_data = None
            # 从历史数据估算: 用涨跌幅连乘
            # 简化: 直接用最早那天的数据估算
            pass

        # 用pct_chg累加近似多日收益 (实际应该用close，但ths_daily的close是概念指数点位)
        # 这里简化: 直接用对应日期的pct_chg
        h_latest = history_data.get(latest_date, {}).get(code, {})
        h_5 = history_data.get(date_5, {}).get(code, {})
        h_20 = history_data.get(date_20, {}).get(code, {})

        if h_5 and h_latest:
            # 近似: 用pct_chg累加
            ret_5d = 0
            dates_between = [d for d in trade_dates if date_5 < d <= latest_date]
            for d in dates_between:
                ret_5d += history_data.get(d, {}).get(code, {}).get('pct_chg', 0)

        if h_20 and h_latest:
            ret_20d = 0
            dates_between = [d for d in trade_dates if date_20 < d <= latest_date]
            for d in dates_between:
                ret_20d += history_data.get(d, {}).get(code, {}).get('pct_chg', 0)

        # 量比
        today_vol = daily.get('vol', 0)
        avg_vol = 0
        count_days = 0
        for td in past_dates:
            v = history_data.get(td, {}).get(code, {}).get('vol', 0)
            if v > 0:
                avg_vol += v
                count_days += 1
        avg_vol = avg_vol / max(count_days, 1)
        vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0
        vol_ratio = min(max(vol_ratio, 0.1), 10.0)

        results.append({
            'code': code,
            'name': name,
            'daily_ret': round(daily_ret, 2),
            'ret_5d': round(ret_5d, 2),
            'ret_20d': round(ret_20d, 2),
            'vol_ratio': round(vol_ratio, 2),
        })

    # 计算RPS
    rets_5d = [r['ret_5d'] for r in results]
    rets_20d = [r['ret_20d'] for r in results]
    rps5 = compute_rps(rets_5d)
    rps20 = compute_rps(rets_20d)

    for i in range(len(results)):
        results[i]['rps_5d'] = round(rps5[i], 1)
        results[i]['rps_20d'] = round(rps20[i], 1)

    return results


# ============ 评分引擎 ============

def score_concepts(metrics, hs300_ret):
    """
    五维综合评分:
      1. 当日涨幅 (20%)
      2. RPS_5D (30%)
      3. RPS_20D (20%)
      4. 量比 (20%)
      5. 超额收益 (10%)
    """
    n = len(metrics)
    if n == 0:
        return []

    daily_rets = [m['daily_ret'] for m in metrics]
    rps5 = [m['rps_5d'] for m in metrics]
    rps20 = [m['rps_20d'] for m in metrics]
    vols = [min(max(m['vol_ratio'], 0.5), 5.0) for m in metrics]
    excess = [m['daily_ret'] - hs300_ret for m in metrics]

    s_daily = minmax_norm(daily_rets)
    s_rps5 = rps5  # already 0-100
    s_rps20 = rps20
    s_vol = minmax_norm(vols)
    s_excess = minmax_norm(excess)

    weights = {'daily': 0.20, 'rps5': 0.30, 'rps20': 0.20,
               'vol': 0.20, 'excess': 0.10}

    scored = []
    for i in range(n):
        total = (
            s_daily[i] * weights['daily']
            + s_rps5[i] * weights['rps5']
            + s_rps20[i] * weights['rps20']
            + s_vol[i] * weights['vol']
            + s_excess[i] * weights['excess']
        )
        scored.append({
            'name': metrics[i]['name'],
            'code': metrics[i]['code'],
            'score': round(total, 1),
            'daily_ret': metrics[i]['daily_ret'],
            'excess_ret': round(excess[i], 2),
            'rps_5d': metrics[i]['rps_5d'],
            'rps_20d': metrics[i]['rps_20d'],
            'vol_ratio': metrics[i]['vol_ratio'],
            'ret_5d': metrics[i]['ret_5d'],
            'ret_20d': metrics[i]['ret_20d'],
            # 贡献分解
            'c_daily': round(s_daily[i] * weights['daily'], 1),
            'c_rps5': round(s_rps5[i] * weights['rps5'], 1),
            'c_rps20': round(s_rps20[i] * weights['rps20'], 1),
            'c_vol': round(s_vol[i] * weights['vol'], 1),
            'c_excess': round(s_excess[i] * weights['excess'], 1),
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored


# ============ 市场趋势评估（复用现有逻辑） ============

def assess_market_trend(trade_date):
    """HS300趋势判断 — 复用现有KDJ+MA逻辑"""
    trade_days = get_trade_days(trade_date, 30)
    if not trade_days:
        return {'regime': 'sideways', 'ret_5d': 0, 'ret_20d': 0}

    prices_data = {}
    for td in trade_days:
        data = api_call('index_daily', ts_code=HS300_CODE,
                        start_date=td, end_date=td,
                        fields='trade_date,open,high,low,close,pct_chg')
        rows = parse_data(data)
        if rows:
            r = rows[0]
            prices_data[td] = {
                'close': float(r['close']), 'high': float(r['high']),
                'low': float(r['low']), 'pct': float(r.get('pct_chg', 0))
            }
        time.sleep(0.15)

    sorted_dates = sorted(prices_data.keys())
    if len(sorted_dates) < 20:
        return {'regime': 'sideways', 'ret_5d': 0, 'ret_20d': 0}

    closes = [prices_data[d]['close'] for d in sorted_dates]
    highs = [prices_data[d]['high'] for d in sorted_dates]
    lows = [prices_data[d]['low'] for d in sorted_dates]
    pcts = [prices_data[d]['pct'] for d in sorted_dates]
    n = len(closes)

    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma_up = ma10 > ma20 * 1.002

    k_val, d_val = 50, 50
    if n >= 14:
        k_list, d_list = [50.0] * n, [50.0] * n
        for i in range(14, n):
            hn = max(highs[i-13:i+1])
            ln = min(lows[i-13:i+1])
            rsv = (closes[i] - ln) / (hn - ln) * 100 if hn != ln else 50
            k_list[i] = 2/3 * k_list[i-1] + 1/3 * rsv
            d_list[i] = 2/3 * d_list[i-1] + 1/3 * k_list[i]
        k_val = k_list[-1]
        d_val = d_list[-1]

    kdj_down = k_val < 20 and d_val < 30
    if kdj_down:
        regime = 'down'
    elif ma_up:
        regime = 'up'
    else:
        regime = 'sideways'

    return {
        'regime': regime,
        'ret_5d': round(sum(pcts[-5:]), 2),
        'ret_20d': round(sum(pcts[-20:]), 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'kdj_k': round(k_val, 1),
        'kdj_d': round(d_val, 1),
    }


# ============ 延续性评估 ============

def assess_continuity(scored, market_trend=None):
    """评估概念热度延续性"""
    continuity = {}
    for s in scored[:30]:
        name = s['name']
        daily = s['daily_ret']
        ret_5d = s['ret_5d']
        ret_20d = s['ret_20d']

        # 趋势判断
        if ret_5d > 0 and daily > 0 and ret_20d > 0:
            if daily > ret_5d > 0:
                trend = 'accelerating'
            else:
                trend = 'sustained'
        elif daily > 0 and ret_20d <= 0:
            trend = 'emerging'
        elif daily < 0 and (ret_5d > 0 or ret_20d > 0):
            trend = 'fading'
        else:
            trend = 'weak'

        # 评级
        if s['score'] >= 70 and trend in ('accelerating', 'sustained'):
            status = '加速热点' if trend == 'accelerating' else '持续热点'
        elif s['score'] >= 60:
            status = '新兴热点'
        elif s['score'] >= 45:
            status = '关注中'
        else:
            status = '待观察'

        continuity[name] = {'status': status, 'trend': trend}

        # 市场趋势修正
        if market_trend and market_trend.get('regime') == 'down':
            if s['score'] >= 70:
                continuity[name]['status'] = f'{status}(反转风险)'
        elif market_trend and market_trend.get('regime') == 'up':
            if status == '新兴热点' and s['score'] >= 60:
                continuity[name]['status'] = '持续热点(顺势)'

    return continuity


# ============ 输出渲染 ============

def c(s):
    return {
        'red': '\033[1;31m', 'yellow': '\033[1;33m',
        'green': '\033[1;32m', 'cyan': '\033[1;36m', 'reset': '\033[0m',
    }.get(s, '')


def render_results(scored, continuity, trade_date, hs300_ret,
                   show_all=False, top_n=20, market_trend=None):
    """渲染终端输出"""
    reset = c('reset')

    # 大盘概况
    hs_str = f'{"📈" if hs300_ret >= 0 else "📉"} HS300: {hs300_ret:+.2f}%'
    top10_up = sum(1 for s in scored[:10] if s['daily_ret'] > 0)
    mood = '强势' if top10_up >= 7 else ('偏强' if top10_up >= 5 else '分化')

    W = 72
    print(f'\n{"=" * W}')
    print(f'  同花顺概念板块扫描  {trade_date}')
    print(f'{"=" * W}')
    print(f'  {hs_str}  |  热点 {top10_up}/10 上涨  |  {mood}')

    if market_trend:
        trend_icon = {'up': '📈', 'sideways': '➡', 'down': '📉'}.get(
            market_trend['regime'], '❓')
        trend_label = {'up': '上升趋势', 'sideways': '震荡市',
                       'down': '下降趋势'}.get(market_trend['regime'], '未知')
        print(f'  {trend_icon} 市场: {trend_label}  '
              f'(K={market_trend["kdj_k"]:.0f} D={market_trend["kdj_d"]:.0f}  '
              f'MA10={market_trend["ma10"]:.0f})')
    print()

    # 排行表
    display_n = min(top_n, len(scored))
    print(f'  {"排":>3} {"概念":<12} {"得分":>5} {"涨幅%":>6} '
          f'{"RPS5":>4} {"RPS20":>4} {"量比":>4} {"5日%":>6} {"20日%":>6} {"热力":<12}')
    print(f'  {"-"*72}')

    for rank, s in enumerate(scored[:display_n], 1):
        name = s['name']
        con = continuity.get(name, {})
        status = con.get('status', '')

        color = c('red') if rank <= 3 else (
            c('yellow') if rank <= 5 else (
                c('green') if rank <= 10 else ''))

        print(f'{color}  {rank:>2} {name:<12} {s["score"]:>4.0f} '
              f'{s["daily_ret"]:>+5.2f} {s["rps_5d"]:>3.0f} '
              f'{s["rps_20d"]:>3.0f} {s["vol_ratio"]:>3.1f} '
              f'{s["ret_5d"]:>+5.2f} {s["ret_20d"]:>+5.2f} '
              f'{status:<12}{reset}')

    print(f'  {"-"*72}')
    print(f'  🔴 前3  🟡 4-5  🟢 6-10\n')

    # Top 5 详细
    print(f'{"=" * W}')
    print(f'  Top 5 详细分析')
    print(f'{"=" * W}')
    for rank, s in enumerate(scored[:5], 1):
        con = continuity.get(s['name'], {})
        trend_symbol = {'accelerating': '📈↑', 'sustained': '➡→',
                        'emerging': '🌟新', 'fading': '📉↓',
                        'weak': '⬇弱'}.get(con.get('trend', ''), '➡→')

        print(f'\n  #{rank} {s["name"]}  ({s["code"]})')
        print(f'     综合 {s["score"]:.0f}分  |  当日 {s["daily_ret"]:+.2f}%  '
              f'(超额{s["excess_ret"]:+.2f}%)')
        print(f'     RPS_5D={s["rps_5d"]:.0f}  RPS_20D={s["rps_20d"]:.0f}  '
              f'量比={s["vol_ratio"]:.1f}x')
        # 贡献
        contribs = [
            ('RPS5', s['c_rps5'], 15), ('RPS20', s['c_rps20'], 10),
            ('涨幅', s['c_daily'], 10), ('量比', s['c_vol'], 10),
            ('超额', s['c_excess'], 5),
        ]
        pos = [f'{n}+{c:.0f}' for n, c, th in contribs if c >= th]
        neg = [f'{n}{c:.0f}' for n, c, th in contribs if c < th]
        print(f'     ✅拉升: {"  ".join(pos) if pos else "—"}')
        print(f'     ❌拖累: {"  ".join(neg) if neg else "—"}')
        print(f'     5日 {s["ret_5d"]:+.2f}%  20日 {s["ret_20d"]:+.2f}%  '
              f'{trend_symbol} {con.get("status", "")}')

    # 延续性分布
    print(f'\n{"=" * W}')
    print(f'  延续性分布')
    print(f'{"=" * W}')
    levels = ['加速热点', '持续热点', '新兴热点', '关注中', '待观察']
    for status in levels:
        matching = [(s['name'], s['score']) for s in scored
                    if continuity.get(s['name'], {}).get('status', '').startswith(status)]
        if matching:
            names = '  '.join(f'{n}({sc:.0f})' for n, sc in matching[:8])
            print(f'  [{status}]: {names}')

    # 总结
    print(f'\n  🔥 TOP3: {" | ".join(s["name"] for s in scored[:3])}')
    print(f'  🔥 TOP5: {" | ".join(s["name"] for s in scored[:5])}')
    print(f'  📊 共 {len(scored)} 个概念板块\n')


# ============ CSV 导出 ============

def save_csv(scored, continuity, trade_date):
    outdir = os.path.join(SCRIPT_DIR, 'reports')
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'ths_concepts_{trade_date}.csv')
    header = '排名,概念代码,概念名称,得分,当日涨幅%,超额%,RPS5,RPS20,量比,5日%,20日%,状态'
    lines = [header]
    for i, s in enumerate(scored, 1):
        con = continuity.get(s['name'], {})
        lines.append(
            f'{i},{s["code"]},{s["name"]},{s["score"]},{s["daily_ret"]:.2f},'
            f'{s["excess_ret"]:.2f},{s["rps_5d"]:.1f},{s["rps_20d"]:.1f},'
            f'{s["vol_ratio"]:.2f},{s["ret_5d"]:.2f},{s["ret_20d"]:.2f},'
            f'{con.get("status", "")}'
        )
    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))
    print(f'  [CSV] 已保存: {path}', file=sys.stderr)
    return path


# ============ 主流程 ============

def main():
    quick_mode = False
    show_all = False
    save_csv_flag = False
    top_n = 20
    target_date_input = None

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--quick':
            quick_mode = True
        elif arg == '--all':
            show_all = True
        elif arg == '--csv' or arg == '--save-csv':
            save_csv_flag = True
        elif arg == '--top':
            i += 1
            if i < len(sys.argv):
                top_n = int(sys.argv[i])
        elif arg == '--refresh':
            # force refresh concept cache
            fetch_ths_concepts(force_refresh=True)
            return
        elif len(arg) == 8 and arg.isdigit():
            target_date_input = arg
        elif arg.startswith('--'):
            print(f'未知参数: {arg}')
            print('用法: python3 ths_concept_scanner.py [YYYYMMDD] '
                  '[--quick] [--all] [--csv] [--top N] [--refresh]')
            return
        i += 1

    # 步骤1: 交易日
    print('==> 步骤1: 确定交易日...', file=sys.stderr)
    trade_date = find_last_trade_day(target_date_input)
    print(f'  → {trade_date}\n', file=sys.stderr)

    # 步骤2: 获取概念列表
    print('==> 步骤2: 获取概念列表...', file=sys.stderr)
    concepts = fetch_ths_concepts()
    if not concepts:
        print('[ERROR] 概念列表为空', file=sys.stderr)
        return
    print(file=sys.stderr)

    # 步骤3: 当日行情
    print('==> 步骤3: 获取当日概念行情...', file=sys.stderr)
    daily_data = fetch_concept_daily_batch(trade_date)
    if not daily_data:
        print('[ERROR] 当日行情为空', file=sys.stderr)
        return
    print(file=sys.stderr)

    # 步骤4: 历史行情 (RPS+量比)
    trade_days = []
    if quick_mode:
        print('==> 步骤4: 快速模式 — 跳过RPS/量比\n', file=sys.stderr)
        history_data = {trade_date: daily_data}
        # 简化metrics
        metrics = []
        for c in concepts:
            code = c['code']
            d = daily_data.get(code, {})
            metrics.append({
                'code': code, 'name': c['name'],
                'daily_ret': round(d.get('pct_chg', 0), 2),
                'ret_5d': 0, 'ret_20d': 0,
                'vol_ratio': 1.0, 'rps_5d': 50, 'rps_20d': 50,
            })
    else:
        print('==> 步骤4: 获取历史交易日...', file=sys.stderr)
        trade_days = get_trade_days(trade_date, 60)
        print(f'  → {len(trade_days)} 个交易日', file=sys.stderr)

        print('==> 步骤4b: 获取历史概念行情...', file=sys.stderr)
        history_data = fetch_concept_history(trade_days)
        print(f'  → {len(history_data)} 天数据\n', file=sys.stderr)

        print('==> 步骤5: 计算多维度指标...', file=sys.stderr)
        metrics = compute_concept_metrics(
            concepts, daily_data, history_data, trade_date)
        print(f'  → {len(metrics)} 个概念\n', file=sys.stderr)

    if not metrics:
        print('[ERROR] 指标计算为空', file=sys.stderr)
        return

    # HS300基准
    print('==> 步骤6: 获取HS300基准...', file=sys.stderr)
    hs300_ret = fetch_hs300_ret(trade_date)
    print(f'  → {hs300_ret:+.2f}%\n', file=sys.stderr)

    # 评分
    print('==> 步骤7: 五维评分...', file=sys.stderr)
    scored = score_concepts(metrics, hs300_ret)
    print(f'  → {len(scored)} 个概念完成评分\n', file=sys.stderr)

    # 市场趋势
    print('==> 步骤8: 市场趋势评估...', file=sys.stderr)
    market_trend = assess_market_trend(trade_date)
    trend_icon = {'up': '📈', 'sideways': '➡', 'down': '📉'}.get(
        market_trend['regime'], '❓')
    print(f'  → {trend_icon} {market_trend["regime"]}\n', file=sys.stderr)

    # 延续性
    print('==> 步骤9: 延续性评估...', file=sys.stderr)
    continuity = assess_continuity(scored, market_trend)

    # 输出
    print('\n========== 输出结果 ==========\n')
    render_results(scored, continuity, trade_date, hs300_ret,
                   show_all, top_n, market_trend)

    if save_csv_flag:
        save_csv(scored, continuity, trade_date)

    print(f'  ⚡ 概念总数: {len(concepts)}, 有行情: {len(daily_data)}')
    if not quick_mode:
        print(f'  ⚡ 完整模式 ~{len(trade_days)+5} 次API调用')


if __name__ == '__main__':
    main()
