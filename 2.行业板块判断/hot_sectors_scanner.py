#!/usr/bin/env python3
"""
A股热门板块检测复盘工具 (个股聚合版)
======================================
基于全市场个股行情数据，按申万行业分类聚合，计算各板块热度。

数据源: Tushare Pro (个股daily接口，免费版可用)
依赖: 无(仅urllib+json，标准库)

用法:
  python3 hot_sectors_scanner.py                    # 最近交易日
  python3 hot_sectors_scanner.py 20260512           # 指定日期
  python3 hot_sectors_scanner.py 20260512 --quick   # 快速模式(只用当日数据)
  python3 hot_sectors_scanner.py 20260512 --csv     # 保存CSV

输出:
  - 综合评分排行 (6维度加权)
  - 各维度明细 (超额收益/RPS/量比/涨停/宽度)
  - 热门延续性评估
"""

import urllib.request
import json
import time
import sys
import os
import math
from datetime import datetime, timedelta
from collections import defaultdict

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

HS300_CODE = '000300.SH'

# ============ 子行业→申万一级行业映射 ============
# Tushare stock_basic.industry 返回的是申万三级子行业名
# 这里映射到申万一级31个行业
SUB_TO_L1 = {
    # 农林牧渔
    '种植业': '农林牧渔', '渔业': '农林牧渔', '林业': '农林牧渔',
    '饲料': '农林牧渔', '农业综合': '农林牧渔',
    # 食品饮料
    '食品': '食品饮料', '乳制品': '食品饮料', '白酒': '食品饮料',
    '啤酒': '食品饮料', '红黄酒': '食品饮料', '软饮料': '食品饮料',
    # 纺织服饰
    '纺织': '纺织服饰', '服饰': '纺织服饰',
    # 轻工制造
    '造纸': '轻工制造', '家居用品': '轻工制造', '文教休闲': '轻工制造',
    '广告包装': '轻工制造', '纺织机械': '轻工制造', '轻工机械': '轻工制造',
    # 医药生物
    '医疗保健': '医药生物', '化学制药': '医药生物', '生物制药': '医药生物',
    '中成药': '医药生物', '医药商业': '医药生物',
    # 公用事业
    '火力发电': '公用事业', '水力发电': '公用事业', '新型电力': '公用事业',
    '水务': '公用事业', '供气供热': '公用事业', '环境保护': '公用事业',
    # 交通运输
    '公路': '交通运输', '路桥': '交通运输', '公共交通': '交通运输',
    '铁路': '交通运输', '空运': '交通运输', '机场': '交通运输',
    '港口': '交通运输', '水运': '交通运输', '仓储物流': '交通运输',
    # 房地产
    '区域地产': '房地产', '全国地产': '房地产', '园区开发': '房地产',
    '房产服务': '房地产',
    # 商贸零售
    '百货': '商贸零售', '商贸代理': '商贸零售', '其他商业': '商贸零售',
    '超市连锁': '商贸零售', '批发业': '商贸零售', '商品城': '商贸零售',
    '电器连锁': '商贸零售',
    # 社会服务
    '旅游景点': '社会服务', '旅游服务': '社会服务', '酒店餐饮': '社会服务',
    # 综合
    '综合类': '综合',
    # 建筑材料
    '水泥': '建筑材料', '玻璃': '建筑材料', '陶瓷': '建筑材料',
    '其他建材': '建筑材料',
    # 建筑装饰
    '建筑工程': '建筑装饰', '装修装饰': '建筑装饰',
    # 电力设备
    '电气设备': '电力设备', '电器仪表': '电力设备',
    # 国防军工
    '航空': '国防军工', '船舶': '国防军工', '运输设备': '国防军工',
    '化工机械': '国防军工', '农用机械': '国防军工',
    # 计算机
    '软件服务': '计算机', 'IT设备': '计算机', '互联网': '计算机',
    # 传媒
    '影视音像': '传媒', '出版业': '传媒',
    # 通信
    '通信设备': '通信', '电信运营': '通信',
    # 银行
    '银行': '银行',
    # 非银金融
    '证券': '非银金融', '保险': '非银金融', '多元金融': '非银金融',
    # 汽车
    '汽车整车': '汽车', '汽车配件': '汽车', '汽车服务': '汽车',
    '摩托车': '汽车',
    # 机械设备
    '专用机械': '机械设备', '机械基件': '机械设备', '机床制造': '机械设备',
    '工程机械': '机械设备',
    # 有色金属
    '铜': '有色金属', '铝': '有色金属', '铅锌': '有色金属',
    '黄金': '有色金属', '小金属': '有色金属', '矿物制品': '有色金属',
    # 煤炭
    '煤炭开采': '煤炭', '焦炭加工': '煤炭',
    # 石油石化
    '石油开采': '石油石化', '石油加工': '石油石化', '石油贸易': '石油石化',
    # 钢铁
    '普钢': '钢铁', '钢加工': '钢铁', '特种钢': '钢铁',
    # 基础化工
    '化工原料': '基础化工', '塑料': '基础化工', '橡胶': '基础化工',
    '农药化肥': '基础化工', '染料涂料': '基础化工', '化纤': '基础化工',
    '日用化工': '基础化工',
    # 电子
    '元器件': '电子', '半导体': '电子',
    # 家用电器
    '家用电器': '家用电器',
}
# 未覆盖到的子行业归为"其他"
SUB_TO_L1_DEFAULT = '其他'


# ============ Tushare API ============

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields:
        payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data,
                                 headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') != 0:
            print(f"  [API Error] {api_name}: {result.get('msg')}", file=sys.stderr)
            return None
        return result.get('data')
    except Exception as e:
        print(f"  [API Exception] {api_name}: {e}", file=sys.stderr)
        return None


def parse_data(data):
    if not data or 'fields' not in data or 'items' not in data:
        return []
    fields = data['fields']
    return [dict(zip(fields, item)) for item in data['items']]


# ============ 交易日识别 ============

def find_last_trade_day(target_date=None):
    """向前最多10天找一个有行情的日期"""
    ref = datetime.strptime(target_date, '%Y%m%d') if target_date else datetime.now()
    for offset in range(10):
        test_date = ref - timedelta(days=offset)
        ds = test_date.strftime('%Y%m%d')
        data = api_call('daily', trade_date=ds, limit=2,
                        fields='ts_code,trade_date')
        if data and data.get('items'):
            return ds
        time.sleep(0.12)
    print("  [WARN] 未找到交易日，使用输入的日期", file=sys.stderr)
    return ref.strftime('%Y%m%d')


def get_trade_days(end_date_str, count=60):
    """从 end_date 往前逐日探测，找到最近的N个交易日
    (轻量级探测，只返回日期列表不返回数据)
    """
    end_dt = datetime.strptime(end_date_str, '%Y%m%d')
    trade_days = []
    max_probe = int(count * 2) + 20

    for offset in range(max_probe):
        td = (end_dt - timedelta(days=offset)).strftime('%Y%m%d')
        data = api_call('daily', trade_date=td, limit=1,
                        fields='ts_code,trade_date')
        if data and data.get('items'):
            trade_days.append(td)
            if len(trade_days) >= count:
                break
        time.sleep(0.12)

    trade_days.sort()
    return trade_days


def fetch_market_history(trade_dates):
    """
    批量获取多个交易日的全市场行情 (与get_trade_days分离，各自独立)
    返回: {trade_date: [{ts_code, close, pct_chg, vol}, ...]}
    """
    result = {}
    total = len(trade_dates)
    for i, td in enumerate(trade_dates):
        if i % 10 == 0 or i == total - 1:
            print(f"  [进度] 历史行情 {i+1}/{total} ({td})", file=sys.stderr)
        data = api_call('daily', trade_date=td, limit=5000,
                        fields='ts_code,close,pct_chg,vol')
        rows = parse_data(data)
        if rows:
            result[td] = rows
        time.sleep(0.12)
    return result


# ============ 核心数据获取 ============

def fetch_stock_industry_map():
    """获取全市场股票→申万行业映射"""
    print("  [进度] 获取股票行业分类...", file=sys.stderr)
    data = api_call('stock_basic', fields='ts_code,name,industry,list_status',
                    list_status='L')
    rows = parse_data(data)

    stock_to_industry = {}
    industry_stocks = defaultdict(list)
    industry_count = defaultdict(int)

    for r in rows:
        ind = r.get('industry', '')
        if ind and ind != 'None' and ind != '':
            stock_to_industry[r['ts_code']] = ind
            industry_stocks[ind].append(r['ts_code'])
            industry_count[ind] += 1
    print(f"  [结果] {len(stock_to_industry)} 只股票有行业分类, "
          f"{len(industry_count)} 个行业", file=sys.stderr)
    return stock_to_industry, dict(industry_stocks), dict(industry_count)


def remap_industries_to_l1(stock_to_ind, industry_stocks, industry_count):
    """将子行业归并到申万一级行业

    返回: (stock_to_l1, l1_stocks, l1_count)
      - stock_to_l1: {ts_code: l1_name}
      - l1_stocks: {l1_name: [ts_code, ...]}
      - l1_count: {l1_name: count}
    """
    stock_to_l1 = {}
    l1_stocks = defaultdict(list)
    l1_count = defaultdict(int)
    unmapped = set()

    for ts_code, sub_ind in stock_to_ind.items():
        l1 = SUB_TO_L1.get(sub_ind, SUB_TO_L1_DEFAULT)
        if l1 == SUB_TO_L1_DEFAULT:
            unmapped.add(sub_ind)
        stock_to_l1[ts_code] = l1
        l1_stocks[l1].append(ts_code)
        l1_count[l1] += 1

    if unmapped:
        print(f"  [WARN] {len(unmapped)} 个子行业未映射到申万一级: "
              f"{', '.join(sorted(unmapped)[:10])}", file=sys.stderr)
    print(f"  [结果] 归并后 {len(l1_count)} 个申万一级行业", file=sys.stderr)
    return stock_to_l1, dict(l1_stocks), dict(l1_count)


def fetch_market_snapshot(trade_date):
    """获取指定日期全市场个股行情"""
    print(f"  [进度] {trade_date} 全市场行情...", file=sys.stderr)
    data = api_call('daily', trade_date=trade_date, limit=5000,
                    fields='ts_code,trade_date,open,high,low,close,'
                           'pre_close,pct_chg,vol,amount')
    return parse_data(data)


def fetch_market_history(trade_dates):
    """
    批量获取多个交易日的全市场行情
    返回: {trade_date: [{ts_code, close, pct_chg, vol}, ...]}
    """
    result = {}
    total = len(trade_dates)
    for i, td in enumerate(trade_dates):
        if i % 10 == 0:
            print(f"  [进度] 历史行情 {i+1}/{total} ({td})", file=sys.stderr)
        data = api_call('daily', trade_date=td, limit=5000,
                        fields='ts_code,close,pct_chg,vol')
        rows = parse_data(data)
        if rows:
            result[td] = rows
        time.sleep(0.12)
    return result


def fetch_limit_up_from_snapshot(snapshot):
    """从全市场行情数据中识别涨停股票（替代limit_list API，免费版可用）

    主板涨停阈值 9.8%，科创/创业板 19.8%
    返回: [{ts_code}, ...]  (仅ts_code后续用到)
    """
    limit_up_list = []
    for r in snapshot:
        pct = float(r.get('pct_chg', 0))
        ts_code = r.get('ts_code', '')
        if not ts_code:
            continue
        # 判断股票所属板块
        if ts_code.startswith('30') or ts_code.startswith('68'):
            threshold = 19.5  # 创业板30/科创板68
        else:
            threshold = 9.5   # 主板/中小板
        if pct >= threshold:
            limit_up_list.append({'ts_code': ts_code})
    return limit_up_list


def fetch_benchmark_history(code, trade_dates):
    """获取基准指数在指定日期的日线"""
    results = {}
    # 用一个范围查询更高效
    start_date = trade_dates[0]
    end_date = trade_dates[-1]
    data = api_call('index_daily', ts_code=code,
                    start_date=start_date, end_date=end_date,
                    fields='trade_date,pct_chg,close')
    rows = parse_data(data)
    for r in rows:
        results[r['trade_date']] = float(r.get('pct_chg', 0))
    return results


# ============ 市场趋势评估 ============

def assess_market_trend(trade_date, hist_data_days=5):
    """
    混合趋势判断: KDJ(14,3,3) K-D位置判断下跌 + MA10/MA20判断上涨

    上涨判断 (MA10/MA20):  56.1%准确率, 277天信号
      MA10 > MA20 × 1.002 → 上升趋势

    下跌判断 (KDJ K-D位置): 53.8%准确率, 105天信号
      K(14,3,3) < 20 且 D < 30 → 下降趋势

    返回: {'regime': str, 'ret_5d': float, 'ret_20d': float, 'ma10': float, 'ma20': float}
    """
    # 获取HS300历史数据 (需要至少30个交易日)
    trade_days = get_trade_days(trade_date, 30)
    if not trade_days:
        return {'regime': 'sideways', 'ret_5d': 0, 'ret_20d': 0}

    # 获取HS300日线 (含high/low用于KDJ)
    prices_data = {}
    for td in trade_days:
        data = api_call('index_daily', ts_code=HS300_CODE,
                        start_date=td, end_date=td,
                        fields='trade_date,open,high,low,close,pct_chg')
        rows = parse_data(data)
        if rows:
            r = rows[0]
            prices_data[td] = {
                'close': float(r['close']),
                'high': float(r['high']),
                'low': float(r['low']),
                'pct': float(r.get('pct_chg', 0))
            }
        time.sleep(0.12)

    sorted_dates = sorted(prices_data.keys())
    if len(sorted_dates) < 20:
        return {'regime': 'sideways', 'ret_5d': 0, 'ret_20d': 0}

    closes = [prices_data[d]['close'] for d in sorted_dates]
    highs = [prices_data[d]['high'] for d in sorted_dates]
    lows = [prices_data[d]['low'] for d in sorted_dates]
    pcts = [prices_data[d]['pct'] for d in sorted_dates]
    n = len(closes)
    latest_close = closes[-1]

    # ---- MA10/MA20 (用于上涨判断) ----
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma_up = ma10 > ma20 * 1.002

    # ---- KDJ(14,3,3) (用于下跌判断) ----
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

    # KDJ K-D位置: K<20 且 D<30 → 下跌信号
    kdj_down = k_val < 20 and d_val < 30

    # ---- 混合判定 ----
    # 下跌用KDJ(更准), 上涨用MA(更多信号)
    if kdj_down:
        regime = 'down'
    elif ma_up:
        regime = 'up'
    else:
        regime = 'sideways'

    # 5日/20日涨跌幅 (供显示)
    ret_5d = sum(pcts[-5:]) if len(pcts) >= 5 else 0
    ret_20d = sum(pcts[-20:]) if len(pcts) >= 20 else 0

    return {
        'regime': regime,
        'ret_5d': round(ret_5d, 2),
        'ret_20d': round(ret_20d, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'kdj_k': round(k_val, 1),
        'kdj_d': round(d_val, 1),
    }


# ============ 行业聚合计算 ============

def aggregate_by_industry(stock_snapshot, stock_to_industry, industry_stocks_dict):
    """
    将个股行情按行业汇总
    返回: {industry_name: {daily_ret(等权), up_count, total_count, vol_sum, ...}}
    """
    # 构建股价数据查询
    stock_data = {}
    for r in stock_snapshot:
        ts = r.get('ts_code', '')
        pct = float(r.get('pct_chg', 0))
        vol = float(r.get('vol', 0))
        stock_data[ts] = {'pct_chg': pct, 'vol': vol}

    industry_stats = {}
    for ind_name, stocks in industry_stocks_dict.items():
        active = [s for s in stocks if s in stock_data]
        if len(active) < 3:
            continue

        rets = [stock_data[s]['pct_chg'] for s in active]
        vols = [stock_data[s]['vol'] for s in active]
        up_count = sum(1 for r in rets if r > 0)

        industry_stats[ind_name] = {
            'avg_ret': sum(rets) / len(rets),           # 等权平均涨幅
            'up_ratio': up_count / len(active) * 100,    # 板块宽度(%)
            'total_vol': sum(vols),                       # 总成交量
            'stock_count': len(active),
            'up_count': up_count,
        }

    return industry_stats


def compute_multi_period_rets(industry_stocks_dict, historical_data):
    """
    计算各行业的多周期涨跌幅（5日/20日）
    使用历史行情数据，按行业等权聚合

    返回: {industry_name: {ret_5d, ret_20d}}
    """
    # 获取所有交易日并排序
    trade_dates = sorted(historical_data.keys())
    if len(trade_dates) < 2:
        return {}

    # 对每个股票，建立日期→收盘价的映射
    stock_close_by_date = {}
    for td, rows in historical_data.items():
        for r in rows:
            ts = r.get('ts_code', '')
            close = float(r.get('close', 0))
            if ts not in stock_close_by_date:
                stock_close_by_date[ts] = {}
            stock_close_by_date[ts][td] = close

    result = {}
    latest_date = trade_dates[-1]
    date_idx_5 = max(0, len(trade_dates) - 6)  # 5个交易日前
    date_idx_20 = max(0, len(trade_dates) - 21)  # 20个交易日前
    date_5 = trade_dates[date_idx_5]
    date_20 = trade_dates[date_idx_20]
    date_1 = trade_dates[0]

    for ind_name, stocks in industry_stocks_dict.items():
        rets_5d = []
        rets_20d = []
        rets_start = []

        close_data = stock_close_by_date
        for s in stocks:
            if s not in close_data:
                continue
            d = close_data[s]
            c_latest = d.get(latest_date)
            c_5 = d.get(date_5)
            c_20 = d.get(date_20)
            c_start = d.get(date_1)

            if c_latest and c_5 and c_5 > 0:
                rets_5d.append((c_latest - c_5) / c_5 * 100)
            if c_latest and c_20 and c_20 > 0:
                rets_20d.append((c_latest - c_20) / c_20 * 100)
            if c_latest and c_start and c_start > 0:
                rets_start.append((c_latest - c_start) / c_start * 100)

        if rets_5d:
            result[ind_name] = {
                'ret_5d': sum(rets_5d) / len(rets_5d),
                'ret_20d': sum(rets_20d) / len(rets_20d) if rets_20d else 0,
            }
        else:
            result[ind_name] = {'ret_5d': 0, 'ret_20d': 0}

    return result


def compute_industry_volume_ratio(industry_stocks_dict, historical_data):
    """
    计算各行业的量比 (当日量/20日均量)
    返回: {industry_name: vol_ratio}
    """
    trade_dates = sorted(historical_data.keys())
    if len(trade_dates) < 2:
        return {}

    latest_date = trade_dates[-1]

    # 对每个股票，建立日期→成交量的映射
    stock_vol_by_date = {}
    for td, rows in historical_data.items():
        for r in rows:
            ts = r.get('ts_code', '')
            vol = float(r.get('vol', 0))
            if ts not in stock_vol_by_date:
                stock_vol_by_date[ts] = {}
            stock_vol_by_date[ts][td] = vol

    result = {}
    for ind_name, stocks in industry_stocks_dict.items():
        # 当日行业总成交量
        today_vol = 0
        avg_vol_20d = 0
        days_available = len(trade_dates) - 1  # 排除最新一天，作为当日

        # 用过去20天（排除当日）计算平均量
        past_dates = trade_dates[:-1][-20:]  # 最多20天
        if not past_dates:
            result[ind_name] = 1.0
            continue

        total_past_vol = 0
        count_days = 0

        for day_idx, td in enumerate(past_dates):
            day_vol = 0
            for s in stocks:
                if s in stock_vol_by_date and td in stock_vol_by_date[s]:
                    day_vol += stock_vol_by_date[s][td]
            total_past_vol += day_vol
            count_days += 1

        # 当日量
        for s in stocks:
            if s in stock_vol_by_date and latest_date in stock_vol_by_date[s]:
                today_vol += stock_vol_by_date[s][latest_date]

        avg_daily = total_past_vol / max(count_days, 1)
        vol_ratio = today_vol / avg_daily if avg_daily > 0 else 1.0
        result[ind_name] = min(max(vol_ratio, 0.1), 10.0)

    return result


# ============ 资金流向聚合 ============

def fetch_industry_moneyflow(trade_date, stock_to_ind):
    """获取个股资金流向并按行业聚合
    返回: {industry: {'net_amount': 净流入额, 'total_amount': 总成交额, 
                      'net_rate': 净流入率, 'mf_stocks': [连续5天正流入天数]}}
    """
    data = api_call('moneyflow', trade_date=trade_date,
                    fields='ts_code,buy_lg_amount,sell_lg_amount,'
                           'buy_elg_amount,sell_elg_amount,net_mf_amount')
    rows = parse_data(data)
    if not rows:
        return {}

    ind_money = {}
    for r in rows:
        code = r.get('ts_code', '')
        ind = stock_to_ind.get(code, '')
        if not ind:
            continue

        # 主力净流入 = 大单 + 特大单净流入
        buy_main = float(r.get('buy_lg_amount', 0)) + float(r.get('buy_elg_amount', 0))
        sell_main = float(r.get('sell_lg_amount', 0)) + float(r.get('sell_elg_amount', 0))
        net_mf = float(r.get('net_mf_amount', 0))

        if ind not in ind_money:
            ind_money[ind] = {'net_amount': 0, 'total_buy': 0, 'total_sell': 0, 'count': 0}
        ind_money[ind]['net_amount'] += net_mf
        ind_money[ind]['total_buy'] += buy_main
        ind_money[ind]['total_sell'] += sell_main
        ind_money[ind]['count'] += 1

    # 计算净流入率
    for ind, m in ind_money.items():
        total_turnover = m['total_buy'] + m['total_sell']
        if total_turnover > 0:
            m['net_rate'] = m['net_amount'] / total_turnover * 100  # 百分比
        else:
            m['net_rate'] = 0
    return ind_money


# ============ 评分引擎 ============

def calc_rps(values):
    """百分位排名 0-100"""
    n = len(values)
    if n == 0:
        return []
    sorted_vals = sorted(set(values))
    rank_map = {v: (i + 1) / n * 100 for i, v in enumerate(sorted_vals)}
    return [rank_map.get(v, 0) for v in values]


def minmax_norm(values):
    if not values:
        return []
    mn, mx = min(values), max(values)
    if mx == mn:
        return [50.0] * len(values)
    return [(v - mn) / (mx - mn) * 100 for v in values]


def score_hot_sectors(industry_stats, multi_period_rets, vol_ratios,
                      limit_up_industries, hs300_ret, moneyflow_data=None):
    """
    八维综合评分

    维度 & 权重 (新版):
      1. 当日超额收益 (10%): vs HS300
      2. RPS_5D (20%): 5日涨幅百分位
      3. RPS_20D (15%): 20日涨幅百分位
      4. 量比 (10%): 当日量/20日均量
      5. 涨停密度 (10%): 涨停家数/行业总股数
      6. 板块宽度 (10%): 上涨股票占比
      7. 主力净流入率 (15%): (大单+特大单净流入)/总成交额
      8. 资金强度 (10%): 净流入率 * 量比 (量价资金共振)

    返回: [{name, score, daily_ret, rps_5d, rps_20d, vol_ratio, limit_up, breadth, 
             net_mf_rate, mf_score, ...}]
    """
    industries = list(industry_stats.keys())
    if not industries:
        return []

    n = len(industries)

    # 维度1: 超额收益 (权重降低)
    excess_rets = [industry_stats[ind]['avg_ret'] - hs300_ret for ind in industries]
    score_excess = minmax_norm(excess_rets)

    # 维度2: RPS_5D (权重提高)
    rets_5d = [multi_period_rets.get(ind, {}).get('ret_5d', 0) for ind in industries]
    score_rps5 = calc_rps(rets_5d)

    # 维度3: RPS_20D
    rets_20d = [multi_period_rets.get(ind, {}).get('ret_20d', 0) for ind in industries]
    score_rps20 = calc_rps(rets_20d)

    # 维度4: 量比
    vol_scores = [vol_ratios.get(ind, 1.0) for ind in industries]
    vol_clipped = [min(max(v, 0.5), 5.0) for v in vol_scores]
    score_vol = minmax_norm(vol_clipped)

    # 维度5: 涨停密度
    score_lu = []
    for ind in industries:
        lu_count = len(limit_up_industries.get(ind, []))
        stock_count = industry_stats[ind]['stock_count']
        density = lu_count / max(stock_count, 1) * 100
        score_lu.append(min(density * 8, 100))
    score_lu = [min(s, 100) for s in score_lu]

    # 维度6: 板块宽度
    score_breadth = [industry_stats[ind]['up_ratio'] for ind in industries]
    score_breadth = [min(s, 100) for s in score_breadth]

    # 维度7: 主力净流入率
    if moneyflow_data:
        mf_rates = [moneyflow_data.get(ind, {}).get('net_rate', 0) for ind in industries]
        # 净流入率可能是负的，用minmax归一化
        score_mf = minmax_norm(mf_rates)
    else:
        score_mf = [50.0] * n

    # 维度8: 资金强度 = 净流入率 × 量比 (量价资金共振)
    if moneyflow_data:
        mf_strength = []
        for ind in industries:
            rate = moneyflow_data.get(ind, {}).get('net_rate', 0)
            vratio = vol_ratios.get(ind, 1.0)
            # 净流入率为正时放大量比效应，为负时缩小
            strength = rate * vratio if rate > 0 else rate * min(vratio, 1.0)
            mf_strength.append(strength)
        score_mf_strength = minmax_norm(mf_strength)
    else:
        score_mf_strength = [50.0] * n

    # 综合得分 (新版权重)
    weights = {'excess': 0.10, 'rps5': 0.20, 'rps20': 0.15,
               'vol': 0.10, 'lu': 0.10, 'breadth': 0.10,
               'mf': 0.15, 'mf_str': 0.10}
    composites = []
    for i in range(n):
        total = (
            score_excess[i] * weights['excess']
            + score_rps5[i] * weights['rps5']
            + score_rps20[i] * weights['rps20']
            + score_vol[i] * weights['vol']
            + score_lu[i] * weights['lu']
            + score_breadth[i] * weights['breadth']
            + score_mf[i] * weights['mf']
            + score_mf_strength[i] * weights['mf_str']
        )
        composites.append(total)

    # 组装结果
    scored = []
    for i, ind in enumerate(industries):
        st = industry_stats[ind]
        lu_count = len(limit_up_industries.get(ind, []))
        mf_rate = moneyflow_data.get(ind, {}).get('net_rate', 0) if moneyflow_data else 0
        scored.append({
            'name': ind,
            'score': round(composites[i], 1),
            'daily_ret': round(st['avg_ret'], 2),
            'excess_ret': round(excess_rets[i], 2),
            'rps_5d': round(score_rps5[i], 1),
            'rps_20d': round(score_rps20[i], 1),
            'vol_ratio': round(vol_scores[i], 2),
            'limit_up': lu_count,
            'breadth': round(st['up_ratio'], 1),
            'stock_count': st['stock_count'],
            'ret_5d': round(multi_period_rets.get(ind, {}).get('ret_5d', 0), 2),
            'ret_20d': round(multi_period_rets.get(ind, {}).get('ret_20d', 0), 2),
            'net_mf_rate': round(mf_rate, 2),
            'mf_score': round(score_mf[i], 1),
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored


# ============ 延续性评估 ============

def assess_continuity(scored, multi_period_rets, industry_stats, market_trend=None):
    """
    基于多周期数据的延续性评估
    等级: 加速热点 > 持续热点 > 新兴热点 > 关注中 > 待观察

    market_trend: {'regime': 'up'|'sideways'|'down', 'ret_5d': float, 'ret_20d': float}
      用于在下跌市中降低评分置信度
    """
    top10_names = {s['name'] for s in scored[:10]}
    continuity = {}

    for s in scored[:20]:
        ind = s['name']
        st = industry_stats[ind]
        ret_5d = multi_period_rets.get(ind, {}).get('ret_5d', 0)
        ret_20d = multi_period_rets.get(ind, {}).get('ret_20d', 0)

        daily = s['daily_ret']
        breadth = st['up_ratio']
        lu = s['limit_up']

        # 趋势判断: 20日 vs 5日 vs 当日
        # 加速: 当日 > 5日 > 20日 (越来越强)
        # 持续: 5日 > 0且当日 > 0
        # 新兴: 当日突然爆发但过去一般
        # 退潮: 5日/20日不错但当日走弱

        # 赚钱效应: 近期5天的平均涨幅 vs 再前5天
        ret_trend = 'stable'
        if ret_5d > 0 and daily > 0 and ret_20d > 0:
            if daily > ret_5d > 0:
                ret_trend = 'accelerating'
            else:
                ret_trend = 'sustained'
        elif daily > 0 and ret_20d <= 0:
            ret_trend = 'emerging'
        elif daily < 0 and (ret_5d > 0 or ret_20d > 0):
            ret_trend = 'fading'
        elif daily < 0:
            ret_trend = 'weak'

        # 热度持续性评级
        if s['score'] >= 75 and breadth >= 60 and ret_trend in ('accelerating', 'sustained'):
            if ret_trend == 'accelerating':
                status = '加速热点'
            else:
                status = '持续热点'
        elif s['score'] >= 65 and breadth >= 50:
            status = '新兴热点'
        elif s['score'] >= 50:
            status = '关注中'
        else:
            status = '待观察'

        # 特殊情况修正
        if lu >= 5 and s['score'] >= 60:
            # 涨停潮 → 至少算热点
            if status in ('待观察', '关注中'):
                status = '新兴热点'

        continuity[ind] = {
            'status': status,
            'trend': ret_trend,
        }

        # ---- 市场趋势修正: 下跌市中反转风险 ----
        if market_trend and market_trend.get('regime') == 'down':
            # 下跌市中, 高评分板块有反转风险
            if s['score'] >= 75:
                continuity[ind]['status'] = f'{status}(反转风险)'
                continuity[ind]['reversal_risk'] = True
            elif s['score'] >= 60:
                # 中等评分也降一级
                if status == '新兴热点':
                    continuity[ind]['status'] = '关注中(承压)'
                elif status == '关注中':
                    continuity[ind]['status'] = '待观察(承压)'
                continuity[ind]['reversal_risk'] = True
        elif market_trend and market_trend.get('regime') == 'up':
            # 上升趋势中, 新兴热点可提升一级
            if status == '新兴热点' and s['score'] >= 70:
                continuity[ind]['status'] = '持续热点(顺势)'
            elif status == '加速热点':
                continuity[ind]['status'] = '加速热点(顺势)'

    return continuity


# ============ 输出渲染 ============

def c(s):
    """终端颜色辅助"""
    return {
        'red': '\033[1;31m',
        'yellow': '\033[1;33m',
        'green': '\033[1;32m',
        'cyan': '\033[1;36m',
        'reset': '\033[0m',
    }.get(s, '')


def print_header(title):
    W = 72
    print(f'\n{"=" * W}')
    print(f'  {title}')
    print(f'{"=" * W}')


def render_results(scored, continuity, trade_date, hs300_ret, show_all=False,
                    market_trend=None):
    """渲染终端输出"""
    reset = c('reset')

    # ---- 大盘概况 ----
    hs_str = f'{"📈" if hs300_ret >= 0 else "📉"} 沪深300: {hs300_ret:+.2f}%'
    top10_up = sum(1 for s in scored[:10] if s['daily_ret'] > 0)
    mood = '强势' if top10_up >= 7 else ('偏强' if top10_up >= 5 else '分化')
    print_header(f'A股热门板块复盘  {trade_date}')
    print(f'  {hs_str}  |  热点 {top10_up}/10 上涨  |  市场状态: {mood}')

    # 市场趋势横幅
    if market_trend:
        trend_icon = {'up': '📈', 'sideways': '➡', 'down': '📉'}.get(market_trend['regime'], '❓')
        trend_label = {'up': '上升趋势', 'sideways': '震荡市', 'down': '下降趋势'}.get(market_trend['regime'], '未知')
        ma10 = market_trend.get('ma10', 0)
        ma20 = market_trend.get('ma20', 0)
        k = market_trend.get('kdj_k', 0)
        d = market_trend.get('kdj_d', 0)
        method = '(MA↑+KDJ↓)'
        print(f'  {trend_icon} 市场趋势: {trend_label}{method}  '
              f'(MA10={ma10:.0f} MA20={ma20:.0f}  '
              f'K={k:.0f} D={d:.0f}  '
              f'5日={market_trend["ret_5d"]:+.2f}%  '
              f'20日={market_trend["ret_20d"]:+.2f}%)')
        if market_trend['regime'] == 'down':
            print(f'  ⚠️ 下降趋势(KDJ确认): 高评分板块追高风险大, 优先等待企稳')
        elif market_trend['regime'] == 'up':
            print(f'  ✅ 上升趋势(MA确认): 可关注评分Top3板块的动量延续')
    print()

    # ---- 热门板块 Top 15 ----
    display_n = len(scored) if show_all else min(15, len(scored))
    print(f'  {"排":>3} {"行业":<8} {"得分":>5} {"涨幅%":>6} {"超额":>6} '
          f'{"RPS5":>4} {"RPS20":>4} {"量比":>4} {"净流":>6} {"涨停":>4} {"宽度%":>5} {"热力":<10}')
    print(f'  {"-"*80}')

    for rank, s in enumerate(scored[:display_n], 1):
        ind = s['name']
        con = continuity.get(ind, {})
        status = con.get('status', '')

        # 颜色
        color = c('red') if rank <= 3 else (c('yellow') if rank <= 5 else (
            c('green') if rank <= 10 else ''))
        lu_str = f'{s["limit_up"]}' if s['limit_up'] > 0 else ''

        # 终端输出（ANSI颜色会增加显示长度，用空格补偿）
        mf_str = f'{s["net_mf_rate"]:>+5.1f}' if 'net_mf_rate' in s else ''
        print(f'{color}  {rank:>2} {ind:<8} {s["score"]:>4.0f} '
              f'{s["daily_ret"]:>+5.2f} {s["excess_ret"]:>+5.2f} '
              f'{s["rps_5d"]:>3.0f} {s["rps_20d"]:>3.0f} '
              f'{s["vol_ratio"]:>3.1f} {mf_str:>6} '
              f'{lu_str:>4} '
              f'{s["breadth"]:>4.0f} {status:<10}{reset}')

    print(f'  {"-"*80}')
    print(f'  🔴 前3  🟡 4-5  🟢 6-10\n')

    # ---- 热门板块概况 ----
    print_header('Top 5 详细分析')
    for rank, s in enumerate(scored[:5], 1):
        ind = s['name']
        con = continuity.get(ind, {})
        trend_symbol = {'accelerating': '📈↑',
                        'sustained': '➡→',
                        'emerging': '🌟新',
                        'fading': '📉↓',
                        'weak': '⬇弱'}.get(con.get('trend', ''), '➡→')

        print(f'\n  #{rank} {ind}')
        print(f'     综合 {s["score"]:.0f}分  |  当日 {s["daily_ret"]:+.2f}% '
              f'(超额 {s["excess_ret"]:+.2f}%)')
        print(f'     RPS_5D={s["rps_5d"]:.0f}  RPS_20D={s["rps_20d"]:.0f}  '
              f'量比={s["vol_ratio"]:.1f}x  主力净流={s["net_mf_rate"]:+.1f}%')
        print(f'     涨停 {s["limit_up"]}家  |  宽度 {s["breadth"]:.0f}% '
              f'({s["stock_count"]}只)')
        print(f'     5日涨幅 {s["ret_5d"]:+.2f}%  20日涨幅 {s["ret_20d"]:+.2f}%  '
              f'趋势 {trend_symbol} {con.get("status", "")}')
    print()

    # ---- 延续性概览 ----
    print_header('延续性分布')
    levels = [('加速热点', 4), ('持续热点', 3), ('新兴热点', 2),
              ('关注中', 1), ('待观察', 0)]
    for status, _ in levels:
        matching = [(s['name'], s['score'])
                    for s in scored if continuity.get(s['name'], {}).get('status') == status]
        if matching:
            names = '  '.join(f'{n}({sc:.0f})' for n, sc in matching[:8])
            print(f'  [{status}]: {names}')
    print()

    # ---- 完整排行 ----
    if show_all or len(scored) > 15:
        print_header(f'全部 {len(scored)} 个行业排行')
        print(f'  {"排":>3} {"行业":<8} {"得分":>4} {"涨幅%":>6} '
              f'{"RPS5":>4} {"RPS20":>4} {"量比":>4} {"涨停":>4} {"宽度%":>4} '
              f'{"5日%":>6} {"20日%":>6} {"状态":<8}')
        print(f'  {"-"*76}')
        for rank, s in enumerate(scored, 1):
            ind = s['name']
            con = continuity.get(ind, {})
            lu_str = f'{s["limit_up"]}' if s['limit_up'] > 0 else ''
            ret_5 = f'{s["ret_5d"]:+.2f}' if s['ret_5d'] != 0 else ' 0.00'
            ret_20 = f'{s["ret_20d"]:+.2f}' if s['ret_20d'] != 0 else ' 0.00'
            print(f'  {rank:>2}  {ind:<8} {s["score"]:>3.0f} '
                  f'{s["daily_ret"]:>+5.2f} {s["rps_5d"]:>3.0f} '
                  f'{s["rps_20d"]:>3.0f} {s["vol_ratio"]:>3.1f} '
                  f'{lu_str:>4} {s["breadth"]:>3.0f} '
                  f'{ret_5:>6} {ret_20:>6} {con.get("status",""):<8}')
        print()

    # ---- 总结 ----
    top3 = ' | '.join(s['name'] for s in scored[:3])
    top5 = ' | '.join(s['name'] for s in scored[:5])
    print(f'  🔥 TOP3: {top3}')
    print(f'  🔥 TOP5: {top5}')
    print(f'  📊 统计: 涨停行业 {sum(1 for s in scored if s["limit_up"]>0)}个  '
          f'涨停股总数 {sum(s["limit_up"] for s in scored)}只')
    print()


# ============ CSV 导出 ============

def save_csv(scored, continuity, trade_date):
    outdir = os.path.join(SCRIPT_DIR, 'reports')
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'hot_sectors_{trade_date}.csv')

    header = '排名,行业,综合得分,当日涨幅%,超额收益%,RPS_5D,RPS_20D,量比,主力净流入%,涨停数,板块宽度%,5日涨幅%,20日涨幅%,热度状态,个股数'
    lines = [header]
    for i, s in enumerate(scored, 1):
        c = continuity.get(s['name'], {})
        lines.append(
            f'{i},{s["name"]},{s["score"]},{s["daily_ret"]:.2f},{s["excess_ret"]:.2f},'
            f'{s["rps_5d"]:.1f},{s["rps_20d"]:.1f},{s["vol_ratio"]:.2f},'
            f'{s["net_mf_rate"]:.1f},{s["limit_up"]},'
            f'{s["breadth"]:.1f},{s["ret_5d"]:.2f},{s["ret_20d"]:.2f},'
            f'{c.get("status","")},{s["stock_count"]}'
        )

    with open(path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))
    print(f'  [CSV] 已保存: {path}', file=sys.stderr)
    return path


# ============ 主流程 ============

def main():
    # ---- 参数解析 ----
    quick_mode = False
    show_all = False
    save_csv_flag = False
    l1_mode = False
    target_date_input = None

    for arg in sys.argv[1:]:
        if arg == '--quick':
            quick_mode = True
        elif arg == '--all':
            show_all = True
        elif arg == '--csv' or arg == '--save-csv':
            save_csv_flag = True
        elif arg == '--l1':
            l1_mode = True
        elif len(arg) == 8 and arg.isdigit():
            target_date_input = arg
        elif arg.startswith('--'):
            print(f'未知参数: {arg}')
            print('用法: python3 hot_sectors_scanner.py [YYYYMMDD] [--quick] [--all] [--csv] [--l1]')
            return

    # ---- 步骤1: 确定交易日 ----
    print('==> 步骤1: 确定交易日...', file=sys.stderr)
    trade_date = find_last_trade_day(target_date_input)
    print(f'  → {trade_date}\n', file=sys.stderr)

    # ---- 步骤2: 获取行业映射 ----
    print('==> 步骤2: 获取行业分类...', file=sys.stderr)
    stock_to_ind, industry_stocks, industry_count = fetch_stock_industry_map()
    print(file=sys.stderr)

    # ---- 步骤2b: 归并到申万一级 (--l1) ----
    if l1_mode:
        print('==> 步骤2b: 归并到申万一级行业...', file=sys.stderr)
        stock_to_ind, industry_stocks, industry_count = remap_industries_to_l1(
            stock_to_ind, industry_stocks, industry_count)
        print(file=sys.stderr)

    # ---- 步骤3: 获取当日行情 ----
    print('==> 步骤3: 获取当日全市场行情...', file=sys.stderr)
    snapshot = fetch_market_snapshot(trade_date)
    print(f'  → {len(snapshot)} 条记录\n', file=sys.stderr)

    if not snapshot:
        print('[ERROR] 当日行情为空，请检查日期或网络', file=sys.stderr)
        return

    # ---- 步骤4: 从行情数据识别涨停 ----
    print('==> 步骤4: 识别涨停股票(从行情数据)...', file=sys.stderr)
    limit_up_list = fetch_limit_up_from_snapshot(snapshot)
    print(f'  → {len(limit_up_list)} 只涨停\n', file=sys.stderr)

    # ---- 步骤5: 获取历史行情 (用于RPS和量比计算) ----
    if quick_mode:
        print('==> 步骤5: 快速模式 — 不用历史数据\n', file=sys.stderr)
        historical_data = {trade_date: snapshot}
        # 快速模式下使用简化评分
    else:
        print('==> 步骤5: 获取历史行情 (60个交易日)...', file=sys.stderr)
        trade_days = get_trade_days(trade_date, 60)
        print(f'  → {len(trade_days)} 个交易日\n', file=sys.stderr)
        historical_data = fetch_market_history(trade_days)
        print(file=sys.stderr)

    # ---- 步骤6: 行业聚合计算 ----
    print('==> 步骤6: 行业聚合计算...', file=sys.stderr)
    industry_stats = aggregate_by_industry(snapshot, stock_to_ind, industry_stocks)
    print(f'  → {len(industry_stats)} 个行业有数据\n', file=sys.stderr)

    # ---- 步骤7: 多周期收益计算 ----
    if quick_mode:
        print('==> 步骤7: 快速模式 — 跳过RPS/量比计算\n', file=sys.stderr)
        multi_period_rets = {ind: {'ret_5d': 0, 'ret_20d': 0} for ind in industry_stats}
        vol_ratios = {ind: 1.0 for ind in industry_stats}
    else:
        print('==> 步骤7: 计算多周期收益...', file=sys.stderr)
        multi_period_rets = compute_multi_period_rets(industry_stocks, historical_data)
        print(f'  → {len(multi_period_rets)} 个行业\n', file=sys.stderr)

        print('==> 步骤7b: 计算行业量比...', file=sys.stderr)
        vol_ratios = compute_industry_volume_ratio(industry_stocks, historical_data)
        print(f'  → {len(vol_ratios)} 个行业\n', file=sys.stderr)

    # ---- 步骤7c: 获取资金流向 ----
    print('==> 步骤7c: 获取资金流向...', file=sys.stderr)
    moneyflow_data = fetch_industry_moneyflow(trade_date, stock_to_ind)
    if moneyflow_data:
        net_pos = sum(1 for m in moneyflow_data.values() if m.get('net_rate', 0) > 0)
        print(f'  → {len(moneyflow_data)} 个行业, {net_pos}个净流入\n', file=sys.stderr)
    else:
        print(f'  → (无数据，跳过资金流维度)\n', file=sys.stderr)

    # ---- 涨停按行业归类 ----
    limit_up_industries = defaultdict(list)
    stock_to_ind_rev = stock_to_ind  # already have this
    for lu in limit_up_list:
        code = lu.get('ts_code', '')
        if code in stock_to_ind_rev:
            ind = stock_to_ind_rev[code]
            limit_up_industries[ind].append(code)

    # ---- HS300基准 ---
    hs300_ret = 0
    try:
        # HS300日线免费版可查
        hs3 = api_call('index_daily', ts_code=HS300_CODE,
                       start_date=trade_date, end_date=trade_date,
                       fields='trade_date,pct_chg')
        hs3_r = parse_data(hs3)
        if hs3_r:
            hs300_ret = float(hs3_r[0].get('pct_chg', 0))
    except Exception:
        pass

    # ---- 步骤8: 八维评分 ----
    print('==> 步骤8: 八维评分(含资金流)...', file=sys.stderr)
    scored = score_hot_sectors(industry_stats, multi_period_rets, vol_ratios,
                               limit_up_industries, hs300_ret, moneyflow_data)
    print(f'  → {len(scored)} 个行业完成评分\n', file=sys.stderr)

    # ---- 步骤8b: 市场趋势评估 ----
    print('==> 步骤8b: 评估市场趋势...', file=sys.stderr)
    market_trend = assess_market_trend(trade_date)
    trend_icon = {'up': '📈', 'sideways': '➡', 'down': '📉'}.get(market_trend['regime'], '❓')
    print(f'  → {trend_icon} {market_trend["regime"]}  '
          f'(HS300 5日={market_trend["ret_5d"]:+.2f}%  '
          f'20日={market_trend["ret_20d"]:+.2f}%)\n', file=sys.stderr)

    # ---- 步骤9: 延续性评估 (带市场趋势修正) ----
    print('==> 步骤9: 延续性评估...', file=sys.stderr)
    continuity = assess_continuity(scored, multi_period_rets, industry_stats,
                                   market_trend)

    # ---- 步骤10: 输出 ----
    print('\n========== 输出结果 ==========\n')
    render_results(scored, continuity, trade_date, hs300_ret, show_all,
                   market_trend)

    # CSV
    if save_csv_flag:
        save_csv(scored, continuity, trade_date)

    # ---- 速度统计 ----
    if not quick_mode:
        print(f'  ⚡ 完整模式调用 ~70+ 次API, 耗时约 10-15秒')
        print(f'    快捷模式: python3 hot_sectors_scanner.py --quick (只需2次API)\n')


if __name__ == '__main__':
    main()
