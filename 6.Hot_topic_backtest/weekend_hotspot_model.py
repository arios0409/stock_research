#!/usr/bin/env python3
"""
周末热点→周一板块资金流入 评分模型 + 回测优化系统 v2
====================================================
方法: 获取全市场个股日线 → 按申万一级行业聚合 → 构建板块特征 → 预测周一资金流入

数据流:
  1. stock_basic: 获取个股→申万一级行业映射
  2. daily(trade_date=X): 按日期批量获取全市场个股行情 (每日期1次API调用)
  3. 按行业聚合: 计算板块级别的收益/量能/宽度等指标
  4. 特征工程: 基于周五及之前的数据构建10维特征
  5. 标签: 周一板块是否资金流入 (收益+超额+量能综合判定)
  6. 优化: 随机搜索最优权重

API调用估算: ~406次 (1 stock_basic + 1 trade_cal + ~404 daily)
耗时估算: ~7分钟 (1次/秒)
"""

import urllib.request
import json
import time
import os
import sys
import math
import random
from datetime import datetime, timedelta
from collections import defaultdict

# ============ 配置 ============
# 从现有脚本读取token
SCANNER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                           '..', '2.Industry_sector_select')
SCANNER_FILE = os.path.join(SCANNER_DIR, 'hot_sectors_scanner.py')

# 直接读取token
def get_token():
    with open(SCANNER_FILE, 'r') as f:
        for line in f:
            if 'TUSHARE_TOKEN' in line and '=' in line and "'" in line:
                return line.split("'")[1]
    raise RuntimeError("Cannot find TUSHARE_TOKEN")

TUSHARE_TOKEN = get_token()
API_URL = 'http://api.tushare.pro'
HS300_CODE = '000300.SH'

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# 子行业→申万一级映射 (从hot_sectors_scanner.py导入)
SUB_TO_L1 = {}

def load_sub_to_l1():
    """从hot_sectors_scanner.py加载子行业映射"""
    global SUB_TO_L1
    exec_globals = {}
    # 只读取映射表部分
    with open(SCANNER_FILE, 'r') as f:
        content = f.read()
    # 提取SUB_TO_L1字典
    start = content.find('SUB_TO_L1 = {')
    if start < 0:
        raise RuntimeError("Cannot find SUB_TO_L1 in scanner")
    # 找到字典结束位置
    brace_count = 0
    end = start
    for i, c in enumerate(content[start:], start):
        if c == '{':
            brace_count += 1
        elif c == '}':
            brace_count -= 1
            if brace_count == 0:
                end = i + 1
                break
    dict_str = content[start:end]
    exec(dict_str, exec_globals)
    SUB_TO_L1.update(exec_globals['SUB_TO_L1'])

# ============ API调用 ============
def api_call(api_name, max_retries=3, **params):
    """调用Tushare API"""
    payload = {
        'api_name': api_name,
        'token': TUSHARE_TOKEN,
        'params': params,
        'fields': ''
    }
    for attempt in range(max_retries):
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(API_URL, data=data,
                headers={'Content-Type': 'application/json'})
            resp = urllib.request.urlopen(req, timeout=60)
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('code') == 0:
                return result.get('data', {})
            elif result.get('code') == -2001:
                wait = 60 * (attempt + 1)
                print(f'    Rate limited, waiting {wait}s...')
                time.sleep(wait)
            else:
                print(f'    API error {result.get("code")}: {result.get("msg", "")}')
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    return None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                print(f'    Failed: {e}')
                return None
    return None


def fetch_daily_by_date(trade_date):
    """获取某日全市场个股数据, 带缓存"""
    cache_file = os.path.join(DATA_DIR, f'daily_{trade_date}.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    result = api_call('daily', trade_date=trade_date)
    if result and result.get('items'):
        fields = result['fields']
        rows = [dict(zip(fields, item)) for item in result['items']]
        with open(cache_file, 'w') as f:
            json.dump(rows, f)
        return rows
    return []


def fetch_stock_basic():
    """获取股票列表和行业分类"""
    cache_file = os.path.join(DATA_DIR, 'stock_basic_industry.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    result = api_call('stock_basic', exchange='', list_status='L',
                      fields='ts_code,symbol,name,industry')
    if result and result.get('items'):
        fields = result['fields']
        rows = [dict(zip(fields, item)) for item in result['items']]
        with open(cache_file, 'w') as f:
            json.dump(rows, f)
        return rows
    return []


def fetch_trade_cal(start_date, end_date):
    """获取交易日历"""
    cache_file = os.path.join(DATA_DIR, f'tradecal_{start_date}_{end_date}.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    result = api_call('trade_cal', exchange='SSE', start_date=start_date,
                      end_date=end_date, is_open=1)
    if result and result.get('items'):
        fields = result['fields']
        dates = sorted([dict(zip(fields, item))['cal_date'] for item in result['items']])
        with open(cache_file, 'w') as f:
            json.dump(dates, f)
        return dates
    return []


def fetch_index_daily(ts_code, start_date, end_date):
    """获取指数日线数据"""
    cache_file = os.path.join(DATA_DIR, f'idx_{ts_code.replace(".","_")}_{start_date}_{end_date}.json')
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    result = api_call('index_daily', ts_code=ts_code, start_date=start_date,
                      end_date=end_date)
    if result and result.get('items'):
        fields = result['fields']
        rows = sorted([dict(zip(fields, item)) for item in result['items']],
                      key=lambda x: x['trade_date'])
        with open(cache_file, 'w') as f:
            json.dump(rows, f)
        return rows
    return []


# ============ 数据聚合 ============
def aggregate_by_sector(daily_rows, stock_industry_map):
    """
    将个股数据按申万一级行业聚合
    返回: {sector_name: {avg_ret, avg_vol, median_ret, breadth, count}}
    """
    sector_data = defaultdict(lambda: {'rets': [], 'vols': [], 'pct_chgs': []})
    
    for row in daily_rows:
        ts_code = row.get('ts_code', '')
        industry = stock_industry_map.get(ts_code, '')
        l1 = SUB_TO_L1.get(industry, '')
        if not l1:
            continue
        
        pct_chg = row.get('pct_chg')
        vol = row.get('vol', 0)
        if pct_chg is not None:
            sector_data[l1]['rets'].append(pct_chg)
            sector_data[l1]['vols'].append(vol)
            sector_data[l1]['pct_chgs'].append(pct_chg)
    
    result = {}
    for sector, data in sector_data.items():
        rets = data['rets']
        vols = data['vols']
        n = len(rets)
        if n < 3:
            continue
        
        avg_ret = sum(rets) / n
        avg_vol = sum(vols) / n
        breadth = sum(1 for r in rets if r > 0) / n
        
        rets_sorted = sorted(rets)
        median_ret = rets_sorted[n // 2]
        
        result[sector] = {
            'avg_ret': avg_ret,
            'median_ret': median_ret,
            'avg_vol': avg_vol,
            'breadth': breadth,
            'count': n,
        }
    
    return result


# ============ 特征工程 ============
FEATURE_NAMES = [
    'ret_5d',       # 5日涨幅(短期动量)
    'ret_20d',      # 20日涨幅(中期趋势)
    'vol_ratio',    # 量比(5日均量/20日均量)
    'excess_5d',    # 5日超额(vs沪深300)
    'excess_20d',   # 20日超额(vs沪深300)
    'breadth',      # 上涨宽度(板块内上涨比例)
    'price_pos',    # 价格位置(在60日区间中的位置)
    'volatility',   # 波动率(20日收益标准差)
    'streak',       # 连涨周数
    'friday_ret',   # 周五当日涨幅
]


def build_sector_timeseries(all_date_sectors, trade_dates, benchmark_daily):
    """
    构建每个(周五, 板块)的特征向量
    
    all_date_sectors: {date: {sector: {avg_ret, avg_vol, breadth, ...}}}
    benchmark_daily: {date: pct_chg}
    """
    # 构建日期索引
    date_idx = {d: i for i, d in enumerate(trade_dates)}
    
    samples = []
    
    for i, date in enumerate(trade_dates):
        d = datetime.strptime(date, '%Y%m%d')
        if d.weekday() != 4:  # 只看周五
            continue
        if i < 20:  # 需要足够历史数据
            continue
        
        # 找下周一
        if i + 1 >= len(trade_dates):
            continue
        next_date = trade_dates[i + 1]
        nd = datetime.strptime(next_date, '%Y%m%d')
        if nd.weekday() != 0:  # 必须是周一
            continue
        
        sectors_today = all_date_sectors.get(date, {})
        sectors_next = all_date_sectors.get(next_date, {})
        
        for sector in sectors_today:
            if sector not in sectors_next:
                continue
            
            # 收集过去20个交易日的板块数据
            hist_rets = []
            hist_vols = []
            hist_breadths = []
            bench_rets = []
            
            for j in range(max(0, i-19), i+1):
                hd = trade_dates[j]
                sd = all_date_sectors.get(hd, {}).get(sector)
                if sd:
                    hist_rets.append(sd['avg_ret'])
                    hist_vols.append(sd['avg_vol'])
                    hist_breadths.append(sd['breadth'])
                bench_r = benchmark_daily.get(hd, 0)
                bench_rets.append(bench_r)
            
            if len(hist_rets) < 10:
                continue
            
            # 计算特征
            # 1. 5日涨幅 (过去5个交易日累计)
            recent_5 = hist_rets[-5:] if len(hist_rets) >= 5 else hist_rets
            ret_5d = sum(recent_5)
            
            # 2. 20日涨幅
            ret_20d = sum(hist_rets)
            
            # 3. 量比
            if len(hist_vols) >= 20:
                vol_5 = sum(hist_vols[-5:]) / 5
                vol_20 = sum(hist_vols) / len(hist_vols)
                vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0
            else:
                vol_ratio = 1.0
            
            # 4-5. 超额收益
            bench_5 = sum(bench_rets[-5:]) if len(bench_rets) >= 5 else sum(bench_rets)
            bench_20 = sum(bench_rets)
            excess_5d = ret_5d - bench_5
            excess_20d = ret_20d - bench_20
            
            # 6. 上涨宽度
            breadth = hist_breadths[-1] if hist_breadths else 0.5
            
            # 7. 价格位置 (用累计收益模拟)
            if len(hist_rets) >= 20:
                cum_rets = []
                cum = 0
                for r in hist_rets:
                    cum += r
                    cum_rets.append(cum)
                max_cum = max(cum_rets)
                min_cum = min(cum_rets)
                price_pos = (cum_rets[-1] - min_cum) / (max_cum - min_cum) if max_cum > min_cum else 0.5
            else:
                price_pos = 0.5
            
            # 8. 波动率
            if len(hist_rets) >= 10:
                mean_r = sum(hist_rets) / len(hist_rets)
                var_r = sum((r - mean_r)**2 for r in hist_rets) / len(hist_rets)
                volatility = math.sqrt(var_r)
            else:
                volatility = 0
            
            # 9. 连涨周数 (连续正的5日累计收益)
            streak = 0
            for k in range(len(hist_rets)-1, -1, -1):
                if hist_rets[k] > 0:
                    streak += 1
                else:
                    break
            
            # 10. 周五当日涨幅
            friday_ret = hist_rets[-1] if hist_rets else 0
            
            features = {
                'ret_5d': ret_5d,
                'ret_20d': ret_20d,
                'vol_ratio': vol_ratio,
                'excess_5d': excess_5d,
                'excess_20d': excess_20d,
                'breadth': breadth,
                'price_pos': price_pos,
                'volatility': volatility,
                'streak': streak,
                'friday_ret': friday_ret,
            }
            
            # 计算标签: 周一表现
            mon_data = sectors_next[sector]
            mon_ret = mon_data['avg_ret']
            mon_bench = benchmark_daily.get(next_date, 0)
            mon_excess = mon_ret - mon_bench
            
            # 周一量比 (需要历史量数据)
            # 简化: 用breadth作为替代信号
            mon_breadth = mon_data['breadth']
            
            # 标签
            if mon_ret > 0 and mon_excess > 0 and mon_breadth > 0.5:
                label = 2  # 强资金流入
            elif mon_ret > 0 and mon_excess > 0:
                label = 1  # 资金流入
            else:
                label = 0  # 无
            
            samples.append({
                'date': date,
                'monday': next_date,
                'sector': sector,
                'features': features,
                'label': label,
                'mon_ret': mon_ret,
                'mon_excess': mon_excess,
                'mon_breadth': mon_breadth,
            })
    
    return samples


# ============ 评分模型 ============
def compute_feature_ranges(samples):
    """计算特征归一化范围 (5%-95%分位)"""
    ranges = {}
    for feat in FEATURE_NAMES:
        vals = sorted([s['features'][feat] for s in samples])
        n = len(vals)
        if n > 0:
            vmin = vals[int(n * 0.05)]
            vmax = vals[int(n * 0.95)]
            ranges[feat] = (vmin, vmax)
        else:
            ranges[feat] = (0, 1)
    return ranges


def normalize(val, vmin, vmax):
    """归一化到[0,1]"""
    if vmax <= vmin:
        return 0.5
    return max(0.0, min(1.0, (val - vmin) / (vmax - vmin)))


def compute_score(features, weights, feature_ranges):
    """加权评分"""
    score = 0.0
    for feat, w in weights.items():
        val = features.get(feat, 0)
        vmin, vmax = feature_ranges.get(feat, (0, 1))
        score += w * normalize(val, vmin, vmax)
    return score


def evaluate_model(samples, weights, feature_ranges, top_pct=0.30):
    """
    评估模型:
    - 对每个周一，按评分排序板块，取top_pct为"预测热点"
    - 计算: 精确率, F1, Top板块平均收益, 超额收益
    """
    # 按周一分组
    monday_groups = defaultdict(list)
    for s in samples:
        score = compute_score(s['features'], weights, feature_ranges)
        monday_groups[s['monday']].append((score, s['label'], s['mon_ret'], s['mon_excess']))
    
    total_tp = total_fp = total_fn = total_tn = 0
    top_rets = []
    bottom_rets = []
    top_excess = []
    
    for monday, items in monday_groups.items():
        items_sorted = sorted(items, key=lambda x: x[0], reverse=True)
        n_top = max(1, int(len(items_sorted) * top_pct))
        
        for i, (score, label, mon_ret, mon_excess) in enumerate(items_sorted):
            is_pred = i < n_top
            is_actual = label >= 1
            
            if is_pred and is_actual:
                total_tp += 1
                top_rets.append(mon_ret)
                top_excess.append(mon_excess)
            elif is_pred:
                total_fp += 1
                top_rets.append(mon_ret)
                top_excess.append(mon_excess)
            elif is_actual:
                total_fn += 1
                bottom_rets.append(mon_ret)
            else:
                total_tn += 1
                bottom_rets.append(mon_ret)
    
    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    f1 = 2*precision*recall / (precision+recall) if (precision+recall) > 0 else 0
    
    avg_top = sum(top_rets)/len(top_rets) if top_rets else 0
    avg_bottom = sum(bottom_rets)/len(bottom_rets) if bottom_rets else 0
    excess = avg_top - avg_bottom
    avg_top_excess = sum(top_excess)/len(top_excess) if top_excess else 0
    
    # 强流入精确率
    total_strong = sum(1 for items in monday_groups.values() 
                       for i, (s, l, _, _) in enumerate(sorted(items, key=lambda x: x[0], reverse=True))
                       if i < max(1, int(len(items)*top_pct)) and l >= 2)
    n_total_top = sum(max(1, int(len(items)*top_pct)) for items in monday_groups.values())
    precision_strong = total_strong / n_total_top if n_total_top > 0 else 0
    
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'precision_strong': precision_strong,
        'avg_top_ret': avg_top,
        'avg_bottom_ret': avg_bottom,
        'excess_ret': excess,
        'avg_top_excess': avg_top_excess,
    }


# ============ 权重优化 ============
def optimize_weights(samples, feature_ranges):
    """两阶段随机搜索最优权重"""
    print("\n[4/5] 权重优化...")
    
    # 时间序列划分
    train = [s for s in samples if s['date'] < '20250101']
    val = [s for s in samples if s['date'] >= '20250101']
    
    print(f"  训练集: {len(train)} 样本 (2022-2024)")
    print(f"  验证集: {len(val)} 样本 (2025-2026)")
    
    if not train or not val:
        print("  WARNING: 数据不足，使用全量")
        train = samples
        val = samples
    
    best_score = -999
    best_weights = None
    best_metrics = None
    
    # 阶段1: 随机搜索
    random.seed(42)
    N1 = 500
    print(f"  阶段1: 随机搜索 {N1} 次...")
    
    for it in range(N1):
        raw = [random.random() for _ in FEATURE_NAMES]
        total = sum(raw)
        weights = {f: r/total for f, r in zip(FEATURE_NAMES, raw)}
        
        metrics = evaluate_model(train, weights, feature_ranges)
        composite = metrics['f1']*0.35 + metrics['excess_ret']*0.35 + metrics['precision_strong']*0.30
        
        if composite > best_score:
            best_score = composite
            best_weights = weights.copy()
            best_metrics = metrics.copy()
        
        if (it+1) % 100 == 0:
            print(f"    iter {it+1}/{N1}, best_score={best_score:.4f}, "
                  f"F1={best_metrics['f1']:.3f}, excess={best_metrics['excess_ret']:.3f}%")
    
    print(f"  阶段1完成, best={best_score:.4f}")
    
    # 阶段2: 精调
    N2 = 300
    print(f"  阶段2: 精调搜索 {N2} 次...")
    
    for it in range(N2):
        weights = {}
        for f in FEATURE_NAMES:
            noise = random.gauss(0, 0.04)
            weights[f] = max(0.005, best_weights[f] + noise)
        total = sum(weights.values())
        weights = {f: v/total for f, v in weights.items()}
        
        metrics = evaluate_model(train, weights, feature_ranges)
        composite = metrics['f1']*0.35 + metrics['excess_ret']*0.35 + metrics['precision_strong']*0.30
        
        if composite > best_score:
            best_score = composite
            best_weights = weights.copy()
            best_metrics = metrics.copy()
    
    print(f"  优化完成, best_score={best_score:.4f}")
    
    # 验证集评估
    val_metrics = evaluate_model(val, best_weights, feature_ranges)
    
    # 全量评估
    all_metrics = evaluate_model(samples, best_weights, feature_ranges)
    
    return best_weights, best_metrics, val_metrics, all_metrics


# ============ 输出 ============
def output_results(weights, train_metrics, val_metrics, all_metrics, feature_ranges, samples):
    """输出最终结果"""
    print("\n" + "=" * 70)
    print("[5/5] 优化结果 — 周末热点板块→周一资金流入 评分模型")
    print("=" * 70)
    
    print("\n>>> 最优权重 (按重要性排序) <<<")
    print("-" * 50)
    sorted_feats = sorted(weights.keys(), key=lambda x: weights[x], reverse=True)
    for f in sorted_feats:
        w = weights[f]
        bar = '█' * int(w * 60)
        print(f"  {f:15s}: {w:.4f}  {bar}")
    
    for name, metrics in [('训练集 (2022-2024)', train_metrics),
                          ('验证集 (2025-2026)', val_metrics),
                          ('全量 (2022-2026)', all_metrics)]:
        print(f"\n>>> {name} <<<")
        print("-" * 50)
        print(f"  精确率 (资金流入):     {metrics['precision']:.1%}")
        print(f"  强流入精确率:          {metrics['precision_strong']:.1%}")
        print(f"  召回率:                {metrics['recall']:.1%}")
        print(f"  F1分数:                {metrics['f1']:.4f}")
        print(f"  Top30%板块平均收益:    {metrics['avg_top_ret']:+.3f}%")
        print(f"  Top30%板块平均超额:    {metrics['avg_top_excess']:+.3f}%")
        print(f"  Bottom70%板块平均收益: {metrics['avg_bottom_ret']:+.3f}%")
        print(f"  超额收益(Top-Bottom):  {metrics['excess_ret']:+.3f}%")
    
    # 特征范围
    print(f"\n>>> 特征归一化范围 (5%-95%分位) <<<")
    print("-" * 50)
    for f in FEATURE_NAMES:
        vmin, vmax = feature_ranges[f]
        print(f"  {f:15s}: [{vmin:+.2f}, {vmax:+.2f}]")
    
    # 保存模型
    model_params = {
        'weights': weights,
        'feature_ranges': {k: list(v) for k, v in feature_ranges.items()},
        'feature_names': FEATURE_NAMES,
        'train_metrics': train_metrics,
        'val_metrics': val_metrics,
        'all_metrics': all_metrics,
        'total_samples': len(samples),
        'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    model_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                              'weekend_hotspot_model_params.json')
    with open(model_file, 'w') as f:
        json.dump(model_params, f, indent=2, ensure_ascii=False)
    print(f"\n模型参数已保存: {model_file}")
    
    # 使用指南
    print("\n>>> 使用指南 <<<")
    print("=" * 50)
    print("""
每周五收盘后:
  1. 获取全市场个股当日行情 + 过去20日历史
  2. 按申万一级行业聚合(收益/量能/宽度)
  3. 对每个行业计算10维特征
  4. 用归一化范围归一化到[0,1]
  5. 加权求和得评分(0~1)
  6. 取评分前30%为"周末热点板块"预测

评分含义:
  评分越高 → 周一资金流入概率越大
  Top30%板块 vs Bottom70% 的超额收益即为模型alpha

核心特征解读:
  ret_5d      短期动量 — 近5日板块涨幅
  ret_20d     中期趋势 — 近20日板块涨幅  
  vol_ratio   量能信号 — 5日/20日量比
  excess_5d   短期超额 — 板块vs大盘5日差
  excess_20d  中期超额 — 板块vs大盘20日差
  breadth     上涨宽度 — 板块内个股上涨比例
  price_pos   价格位置 — 在60日区间中的位置
  volatility  波动率 — 20日收益波动
  streak      连涨天数 — 连续上涨交易日数
  friday_ret  周五涨幅 — 周五当日板块表现
""")


# ============ 主流程 ============
def main():
    start_time = time.time()
    
    print("=" * 70)
    print("周末热点板块→周一资金流入 评分模型 回测系统 v2")
    print("=" * 70)
    
    # 加载映射
    print("\n[0/5] 加载行业映射...")
    load_sub_to_l1()
    print(f"  子行业映射数: {len(SUB_TO_L1)}")
    
    # Step 1: 获取交易日历
    print("\n[1/5] 获取交易日历 (2021-2026)...")
    trade_dates = fetch_trade_cal('20211001', '20260630')
    if not trade_dates:
        print("ERROR: 无法获取交易日历")
        sys.exit(1)
    print(f"  交易日数: {len(trade_dates)}")
    
    # 找周五→周一对
    pairs = []
    for i in range(len(trade_dates) - 1):
        d1 = datetime.strptime(trade_dates[i], '%Y%m%d')
        d2 = datetime.strptime(trade_dates[i+1], '%Y%m%d')
        if d1.weekday() == 4 and d2.weekday() == 0:
            pairs.append((trade_dates[i], trade_dates[i+1]))
    print(f"  周五→周一对: {len(pairs)}")
    
    # Step 2: 获取股票列表
    print("\n[2/5] 获取股票列表...")
    stocks = fetch_stock_basic()
    if not stocks:
        print("ERROR: 无法获取股票列表")
        sys.exit(1)
    stock_industry_map = {s['ts_code']: s.get('industry', '') for s in stocks}
    print(f"  股票数: {len(stocks)}")
    
    # 统计行业分布
    l1_counts = defaultdict(int)
    for ind in stock_industry_map.values():
        l1 = SUB_TO_L1.get(ind, '')
        if l1:
            l1_counts[l1] += 1
    print(f"  申万一级行业覆盖: {len(l1_counts)}")
    
    # Step 3: 获取基准数据
    print("\n[3/5] 获取沪深300基准数据...")
    bench_rows = fetch_index_daily(HS300_CODE, '20211001', '20260630')
    benchmark_daily = {}
    if bench_rows:
        benchmark_daily = {r['trade_date']: r.get('pct_chg', 0) for r in bench_rows}
        print(f"  沪深300日线数: {len(bench_rows)}")
    else:
        print("  WARNING: 无法获取沪深300, 超额收益将为0")
    
    # Step 4: 按日期获取全市场数据并聚合
    print("\n[4/5] 获取全市场日线数据并按行业聚合...")
    
    # 需要获取的日期: 所有交易日 (需要20日历史)
    # 但为了节省API调用，只获取有周五-周一对的日期及其前20个交易日
    needed_dates = set()
    date_set = set(trade_dates)
    for fri, mon in pairs:
        needed_dates.add(fri)
        needed_dates.add(mon)
        # 找周五前20个交易日
        fri_idx = trade_dates.index(fri) if fri in trade_dates else -1
        if fri_idx >= 0:
            for j in range(max(0, fri_idx-20), fri_idx+1):
                needed_dates.add(trade_dates[j])
    
    needed_dates = sorted(needed_dates)
    print(f"  需要获取的日期数: {len(needed_dates)}")
    
    all_date_sectors = {}
    fetched = 0
    total = len(needed_dates)
    
    for date in needed_dates:
        fetched += 1
        if fetched % 20 == 0 or fetched == total:
            elapsed = time.time() - start_time
            print(f"  获取进度: {fetched}/{total} ({fetched/total*100:.0f}%) "
                  f"已用{elapsed:.0f}s")
        
        rows = fetch_daily_by_date(date)
        if rows:
            sectors = aggregate_by_sector(rows, stock_industry_map)
            all_date_sectors[date] = sectors
        
        time.sleep(0.5)  # 限速
    
    print(f"  聚合完成, {len(all_date_sectors)} 个日期有数据")
    
    # Step 5: 构建样本
    print("\n[5/5] 构建特征样本...")
    samples = build_sector_timeseries(all_date_sectors, trade_dates, benchmark_daily)
    print(f"  总样本数: {len(samples)}")
    
    if not samples:
        print("ERROR: 无有效样本")
        sys.exit(1)
    
    # 标签分布
    label_counts = defaultdict(int)
    for s in samples:
        label_counts[s['label']] += 1
    print(f"  标签分布: 无流入(0)={label_counts[0]}, "
          f"流入(1)={label_counts[1]}, 强流入(2)={label_counts[2]}")
    
    # 特征范围
    feature_ranges = compute_feature_ranges(samples)
    
    # 优化
    weights, train_metrics, val_metrics, all_metrics = optimize_weights(samples, feature_ranges)
    
    # 输出
    output_results(weights, train_metrics, val_metrics, all_metrics, feature_ranges, samples)
    
    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")


if __name__ == '__main__':
    main()
