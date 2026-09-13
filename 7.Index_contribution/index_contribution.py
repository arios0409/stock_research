#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指数板块贡献度归因 (Index Sector Contribution Attribution)
==========================================================
计算上证综指 / 沪深300 当日涨跌中，各申万一级行业的贡献度。

原理:
  指数涨跌幅 ≈ Σ(成分股权重 × 成分股涨跌幅)
  某行业贡献(百分点) = Σ(该行业内 权重 × 涨跌幅)

  行业涨跌 = 行业内成分股的加权平均涨跌幅 (Σ权重×涨跌 / Σ权重)
  贡献占比 = 贡献 ÷ 指数涨跌 (正数=拉涨, 负数=砸盘)

加权口径:
  上证综指  → 总市值加权 (total_mv)，全沪市样本 (.SH, 含科创板, 排除B股)
  沪深300   → 自由流通市值权重 (index_weight 接口直接给 weight)

数据源: Tushare Pro (免费版可用)
依赖: 仅标准库 (urllib + json)，无需 venv

用法:
  python3 index_contribution.py                 # 最近交易日, 两个指数
  python3 index_contribution.py 20260821       # 指定日期
  python3 index_contribution.py --sh           # 仅上证综指
  python3 index_contribution.py --hs300        # 仅沪深300
"""

import urllib.request, json, time, sys, os, re, csv
from datetime import datetime, timedelta
from collections import defaultdict

# ===== 可视化 (可选, 需 matplotlib) =====
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False

# ===== 配置 =====
API_URL = 'http://api.tushare.pro'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)   # stock_research/


def _load_token():
    """从相邻已存在脚本正则读取 token, 避免 write_file 截断 token (pitfall 26)"""
    for p in [os.path.join(BASE_DIR, 'dapan_scan_auto.py'),
              os.path.join(BASE_DIR, '2.Industry_sector_select', 'hot_sectors_scanner.py')]:
        try:
            with open(p, encoding='utf-8') as f:
                m = re.search(r'TUSHARE_TOKEN\s*=\s*["\']([0-9a-fA-F]{20,})["\']', f.read())
                if m:
                    return m.group(1)
        except Exception:
            pass
    raise SystemExit('[FATAL] 未找到 TUSHARE_TOKEN, 请确认 dapan_scan_auto.py 存在')


TUSHARE_TOKEN = _load_token()

# ===== 申万二级 → 申万一级 映射 (与 hot_sectors_scanner.py 保持一致) =====
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
SUB_TO_L1_DEFAULT = '其他'


# ===== Tushare API 封装 =====
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
            print(f'  [API Error] {api_name}: {result.get("msg")}', file=sys.stderr)
            return None
        return result.get('data')
    except Exception as e:
        print(f'  [API Exception] {api_name}: {e}', file=sys.stderr)
        return None


def parse_data(data):
    if not data or 'fields' not in data or 'items' not in data:
        return []
    fields = data['fields']
    return [dict(zip(fields, item)) for item in data['items']]


def fetch_all(api_name, fields=None, page_size=6000, **kwargs):
    """分页拉取全量数据 (offset/limit)"""
    rows = []
    offset = 0
    while True:
        data = api_call(api_name, fields=fields, offset=offset, limit=page_size, **kwargs)
        batch = parse_data(data)
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        time.sleep(0.12)
    return rows


def find_last_trade_day(target_date=None):
    """向前最多15天找最近有行情的交易日"""
    ref = datetime.strptime(target_date, '%Y%m%d') if target_date else datetime.now()
    for offset in range(15):
        ds = (ref - timedelta(days=offset)).strftime('%Y%m%d')
        data = api_call('daily', trade_date=ds, limit=2, fields='ts_code,trade_date')
        if data and data.get('items'):
            return ds
        time.sleep(0.12)
    raise SystemExit('[FATAL] 15天内未找到交易日')


def find_prev_trade_day(trade_date):
    """给定交易日, 返回其前一个交易日"""
    d = datetime.strptime(trade_date, '%Y%m%d')
    prev = (d - timedelta(days=1)).strftime('%Y%m%d')
    return find_last_trade_day(prev)


def load_rets(trade_date, windows=(5, 10, 20)):
    """从 sector_ret_cache.csv 读板块多周期累计涨幅(简单累加%), 返回 {行业: {窗口: 涨幅%}}。

    cache 由 rotation_regime.py 生成, 口径=申万一级行业简单平均涨跌幅(与轮动扫描一致)。
    """
    cache = os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv')
    if not os.path.exists(cache):
        return {}
    try:
        with open(cache, encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return {}
            cols = header[1:]          # 首列是空字符串(日期索引列)
            dated = []
            for line in reader:
                if len(line) >= 2:
                    dated.append((line[0], line[1:]))
    except Exception as e:
        print(f'  [WARN] 读 sector_ret_cache 失败: {e}', file=sys.stderr)
        return {}
    window = [d for d in dated if d[0] <= trade_date][-max(windows):]
    if not window:
        return {}
    acc = {}
    for w in windows:
        for _, vals in window[-w:]:
            for c, v in zip(cols, vals):
                try:
                    d = acc.setdefault(c, {})
                    d[w] = d.get(w, 0.0) + float(v)
                except (ValueError, TypeError):
                    pass
    return acc


def get_trade_days(start_date, end_date):
    """用 trade_cal 拿区间内交易日 (SSE 交易所)"""
    data = api_call('trade_cal', exchange='SSE', start_date=start_date, end_date=end_date,
                    fields='cal_date,is_open')
    rows = parse_data(data)
    days = sorted(r['cal_date'] for r in rows if str(r.get('is_open', '')) == '1')
    return days


# ===== 归因核心 =====
def fetch_industry_map():
    """全市场 {ts_code: 申万一级行业}"""
    rows = fetch_all('stock_basic', fields='ts_code,industry', list_status='L')
    m = {}
    unmapped = defaultdict(int)
    for r in rows:
        sub = (r.get('industry') or '').strip()
        if not sub:
            continue
        l1 = SUB_TO_L1.get(sub, SUB_TO_L1_DEFAULT)
        if l1 == SUB_TO_L1_DEFAULT:
            unmapped[sub] += 1
        m[r['ts_code']] = l1
    if unmapped:
        top = sorted(unmapped.items(), key=lambda x: -x[1])[:12]
        print(f'  [WARN] {len(unmapped)} 个未映射子行业(共{sum(unmapped.values())}只): '
              f'{", ".join(f"{k}({v})" for k, v in top)}', file=sys.stderr)
    print(f'  [信息] 行业映射覆盖 {len(m)} 只股票', file=sys.stderr)
    return m


def _agg_result(name, code, trade_date, idx_pct, agg):
    """agg: {l1: {'w': 权重占比%(或权重和), 'contrib': 贡献(百分点)}}"""
    rows = []
    for l1, d in agg.items():
        w = d['w']
        contrib = d['contrib']
        sector_ret = (contrib / (w / 100.0)) if w > 0 else 0.0   # 行业加权涨跌%
        rows.append({'name': l1, 'w': w, 'sector_ret': sector_ret, 'contrib': contrib})
    rows.sort(key=lambda x: -x['contrib'])
    total_contrib = sum(r['contrib'] for r in rows)
    return {'name': name, 'code': code, 'date': trade_date,
            'idx_pct': idx_pct, 'total_contrib': total_contrib, 'rows': rows}


def attribution_sh(trade_date, industry_map):
    """上证综指归因: 总市值加权, 全沪市(.SH, 排除900xxx B股)"""
    t0 = time.time()
    daily = fetch_all('daily', fields='ts_code,pct_chg', trade_date=trade_date)
    pct = {r['ts_code']: float(r['pct_chg']) for r in daily
           if r.get('pct_chg') is not None}
    mv = fetch_all('daily_basic', fields='ts_code,total_mv', trade_date=trade_date)
    total_mv = {r['ts_code']: float(r['total_mv']) for r in mv
                if r.get('total_mv') is not None}

    sh_all = [c for c in total_mv if c.endswith('.SH') and not c.startswith('900')]
    # 停牌股无当日行情 → pct 记 0 (前日市值=当日市值)
    pct_full = {c: pct.get(c, 0.0) for c in sh_all}
    # 前一日总市值 = 当日总市值 / (1+pct/100)，股本不变时严格成立 → 消除权重再平衡偏差
    prev_mv = {c: total_mv[c] / (1 + pct_full[c] / 100.0) for c in sh_all}
    sum_prev = sum(prev_mv.values())

    agg = defaultdict(lambda: {'w': 0.0, 'contrib': 0.0})
    for c in sh_all:
        w = prev_mv[c] / sum_prev          # 前日市值权重(小数)
        l1 = industry_map.get(c, '其他')
        agg[l1]['w'] += w * 100           # 权重占比%
        agg[l1]['contrib'] += w * pct_full[c]  # 贡献(百分点)

    idx = api_call('index_daily', ts_code='000001.SH',
                   start_date=trade_date, end_date=trade_date, fields='pct_chg')
    idx_rows = parse_data(idx)
    idx_pct = float(idx_rows[0]['pct_chg']) if idx_rows else None
    return _agg_result('上证综指', '000001.SH', trade_date, idx_pct, agg), (time.time() - t0)


_HS300_CONST = None


def get_hs300_constituents():
    """沪深300 最新一期成分股列表 (index_weight, 月度调仓)"""
    global _HS300_CONST
    if _HS300_CONST is not None:
        return _HS300_CONST
    data = api_call('index_weight', index_code='399300.SZ')
    rows = parse_data(data)
    if not rows:
        raise SystemExit('[FATAL] 无法获取沪深300成分股 (index_weight)')
    latest = max(r['trade_date'] for r in rows)
    codes = sorted(set(r['con_code'] for r in rows if r['trade_date'] == latest))
    _HS300_CONST = codes
    print(f"  [信息] 沪深300成分股 {len(codes)} 只 (最新调仓日 {latest})", file=sys.stderr)
    return codes


def attribution_hs300(trade_date, industry_map):
    """沪深300归因: 自算每日自由流通市值权重 (free_share×前收)，消除月度权重滞后"""
    t0 = time.time()
    const_codes = get_hs300_constituents()

    daily = fetch_all('daily', fields='ts_code,pct_chg', trade_date=trade_date)
    pct = {r['ts_code']: float(r['pct_chg']) for r in daily if r.get('pct_chg') is not None}
    mv = fetch_all('daily_basic', fields='ts_code,close,free_share', trade_date=trade_date)
    close = {r['ts_code']: float(r['close']) for r in mv if r.get('close') is not None}
    free_share = {r['ts_code']: float(r['free_share']) for r in mv if r.get('free_share') is not None}

    # 前日自由流通市值(万元) = free_share(万股)×close(元) / (1+pct/100)
    codes = [c for c in const_codes if c in pct and c in close and c in free_share]
    prev_ffmv = {c: free_share[c] * close[c] / (1 + pct[c] / 100.0) for c in codes}
    sum_prev = sum(prev_ffmv.values())

    agg = defaultdict(lambda: {'w': 0.0, 'contrib': 0.0})
    for c in codes:
        w = prev_ffmv[c] / sum_prev
        l1 = industry_map.get(c, '其他')
        agg[l1]['w'] += w * 100
        agg[l1]['contrib'] += w * pct[c]

    idx = api_call('index_daily', ts_code='000300.SH',
                   start_date=trade_date, end_date=trade_date, fields='pct_chg')
    idx_rows = parse_data(idx)
    idx_pct = float(idx_rows[0]['pct_chg']) if idx_rows else None
    return _agg_result('沪深300', '000300.SH', trade_date, idx_pct, agg), (time.time() - t0)


def print_result(res, elapsed):
    print()
    print('=' * 74)
    print(f"{res['name']} ({res['code']}) 板块贡献归因  @ {res['date']}")
    print('=' * 74)
    idx_pct = res['idx_pct']
    if idx_pct is not None:
        dev = res['total_contrib'] - idx_pct
        print(f"指数当日涨跌: {idx_pct:+.2f}%   Σ各板块贡献: {res['total_contrib']:+.2f}pt   "
              f"重构误差 {dev:+.2f}pt   拉取 {elapsed:.1f}s")
    print()
    pos_sum = sum(r['contrib'] for r in res['rows'] if r['contrib'] > 0)
    neg_sum = sum(r['contrib'] for r in res['rows'] if r['contrib'] < 0)
    print(f"{'排名':<4}{'方向':<4}{'行业':<10}{'权重占比':>10}{'行业涨跌':>10}{'贡献(pt)':>10}{'占同向力%':>10}")
    print('-' * 74)
    for i, r in enumerate(res['rows'], 1):
        c = r['contrib']
        if c > 0:
            direction, share = '↑', (c / pos_sum * 100 if pos_sum > 0 else 0)
        elif c < 0:
            direction, share = '↓', (abs(c) / abs(neg_sum) * 100 if neg_sum < 0 else 0)
        else:
            direction, share = '·', 0
        print(f"{i:<4}{direction:<4}{r['name']:<10}{r['w']:>9.2f}%{r['sector_ret']:>+9.2f}%"
              f"{c:>+9.2f}{share:>9.1f}%")
    print('-' * 74)
    print("说明: 贡献(pt)=权重×行业涨跌, 即该行业对指数涨跌幅的直接贡献(百分点), 可正负相加≈指数涨跌。")
    print("      ↑拉涨 ↓砸盘。'占同向力%'=该板块在拉涨(或砸盘)总力量中的份额。")
    print("      重构误差=Σ贡献−指数涨跌, 越小越准(理想=0)。")


def save_csv(res, subdir=None):
    outdir = os.path.join(SCRIPT_DIR, 'output')
    if subdir:
        outdir = os.path.join(outdir, subdir)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{res['code'].split('.')[0]}_{res['date']}_板块贡献.csv")
    pos_sum = sum(r['contrib'] for r in res['rows'] if r['contrib'] > 0)
    neg_sum = sum(r['contrib'] for r in res['rows'] if r['contrib'] < 0)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('排名,方向,行业,权重占比%,行业涨跌%,贡献pt,占同向力%\n')
        for i, r in enumerate(res['rows'], 1):
            c = r['contrib']
            if c > 0:
                direction, share = '拉涨', (c / pos_sum * 100 if pos_sum > 0 else 0)
            elif c < 0:
                direction, share = '砸盘', (abs(c) / abs(neg_sum) * 100 if neg_sum < 0 else 0)
            else:
                direction, share = '平', 0
            f.write(f"{i},{direction},{r['name']},{r['w']:.2f},{r['sector_ret']:.2f},{c:.3f},{share:.1f}\n")
    print(f"[CSV] {path}", file=sys.stderr)


def save_range_csv(code, agg, start_date, end_date):
    outdir = os.path.join(SCRIPT_DIR, 'output')
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{code}_{start_date}_{end_date}_区间累计贡献.csv")
    rows = [{'name': l1, 'avg_w': (d['w_sum'] / d['n'] if d['n'] else 0), 'contrib': d['contrib']}
            for l1, d in agg.items()]
    rows.sort(key=lambda x: -x['contrib'])
    pos_sum = sum(r['contrib'] for r in rows if r['contrib'] > 0)
    neg_sum = sum(r['contrib'] for r in rows if r['contrib'] < 0)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('排名,方向,行业,平均权重%,累计贡献pt,占同向力%\n')
        for i, r in enumerate(rows, 1):
            c = r['contrib']
            if c > 0:
                direction, share = '拉涨', (c / pos_sum * 100 if pos_sum > 0 else 0)
            elif c < 0:
                direction, share = '砸盘', (abs(c) / abs(neg_sum) * 100 if neg_sum < 0 else 0)
            else:
                direction, share = '平', 0
            f.write(f"{i},{direction},{r['name']},{r['avg_w']:.2f},{c:.3f},{share:.1f}\n")
    print(f"[CSV] {path}", file=sys.stderr)


def _setup_font():
    for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
        if os.path.exists(fp):
            fm.fontManager.addfont(fp)
    plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False


def draw_diverging(names, contribs, weights, title, subtitle, outpath, deltas=None, rets=None,
                   windows=(5, 10, 20)):
    """发散横条图: 正值(拉涨)向右红, 负值(砸盘)向左绿

    deltas: 与 names 同序的「贡献环比变化」(今日−昨日, pt), 可选
    rets:   与 names 同序的「多周期累计涨幅」dict {窗口: 涨幅%}, 元素可为 None, 可选
    windows: 涨幅周期列表(升序, 如 5/10/20 日)
    """
    if not _HAS_MPL:
        return
    _setup_font()
    order = sorted(range(len(names)), key=lambda i: -contribs[i])
    names = [names[i] for i in order]
    contribs = [contribs[i] for i in order]
    weights = [weights[i] for i in order] if weights else [0.0] * len(order)
    deltas = [deltas[i] for i in order] if deltas else None
    rets = [rets[i] for i in order] if rets else None

    c_bg = '#0d1117'
    c_up = '#e0443a'   # 拉涨 = 红
    c_dn = '#21a05f'   # 砸盘 = 绿
    c_txt = '#e8eaed'
    c_sub = '#8b949e'

    n = len(names)
    h = max(7.0, 1.1 + n * 0.34)
    fig, ax = plt.subplots(figsize=(14, h), facecolor=c_bg)
    ax.set_facecolor(c_bg)

    maxabs = max([abs(c) for c in contribs] or [1])
    colors = [c_up if c >= 0 else c_dn for c in contribs]
    ax.barh(range(n), contribs, color=colors, height=0.62, zorder=3, alpha=0.93)
    ax.axvline(0, color='#3d444d', linewidth=1.2, zorder=2)
    ax.set_xlim(-maxabs * 3.7, maxabs * 2.0)
    ax.invert_yaxis()
    ax.set_yticks([])
    ax.set_xticks([])
    for sp in ['top', 'right', 'bottom', 'left']:
        ax.spines[sp].set_visible(False)

    # 左侧多列: 权重%(灰,右对齐) | 行业名(白,粗体) | 5/10/20日涨幅(红涨绿跌)
    #   位置用 maxabs 倍数定位 → 固定像素间距, 给最长负bar的末端标注留足空间
    WINDOW_X = {5: 2.82, 10: 2.44, 20: 2.06}   # 各周期涨幅列左对齐位置(×maxabs, 左侧为负)
    # 列分隔竖线: 行业名|5日、5日|10日、10日|20日 (置于相邻两列空隙中点)
    for sx in (2.87, 2.49, 2.11):
        ax.plot([-maxabs * sx, -maxabs * sx], [-0.5, n - 0.5],
                color='#3d444d', linewidth=0.8, alpha=0.55, zorder=2)
    for i in range(n):
        ax.text(-maxabs * 3.37, i, f'{weights[i]:.1f}%', va='center', ha='right',
                color=c_sub, fontsize=10)
        ax.text(-maxabs * 3.27, i, names[i], va='center', ha='left',
                color=c_txt, fontsize=12, fontweight='bold')
        if rets is not None and rets[i] is not None:
            for w in windows:
                rv = rets[i].get(w)
                if rv is not None:
                    ax.text(-maxabs * WINDOW_X[w], i, f'{w}日{rv:+.1f}%', va='center', ha='left',
                            color=(c_up if rv >= 0 else c_dn), fontsize=8)

    # 条末端: 贡献 pt (粗体彩色) + 环比箭头(↑↓, 较前日增减)
    for i in range(n):
        c = contribs[i]
        x = c + (0.03 * maxabs if c >= 0 else -0.03 * maxabs)
        ha = 'left' if c >= 0 else 'right'
        c_label = '0.00' if abs(c) < 0.005 else f'{c:+.2f}'
        ax.text(x, i, f'{c_label}pt', va='center', ha=ha,
                color=colors[i], fontsize=11, fontweight='bold')
        if deltas is not None:
            d = deltas[i]
            if abs(d) < 0.005:
                s, dcol = '→', c_sub
            else:
                s = f'{"↑" if d > 0 else "↓"}{abs(d):.2f}'
                dcol = c_up if d > 0 else c_dn
            xd = x + (0.42 * maxabs if c >= 0 else -0.42 * maxabs)
            ax.text(xd, i, s, va='center', ha=ha, color=dcol, fontsize=9)

    ax.set_title(title, color=c_txt, fontsize=16, fontweight='bold', pad=16, loc='left')
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes, color='#b8c0cc', fontsize=10.5, va='bottom')

    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    fig.savefig(outpath, dpi=150, facecolor=c_bg, bbox_inches='tight')
    plt.close(fig)
    print(f'[图表] {outpath}', file=sys.stderr)


def save_chart(res, prev_contrib=None, rets=None, windows=(5, 10, 20)):
    """单日板块贡献发散图 (可叠加前日贡献环比 + 多周期累计涨幅)"""
    if not _HAS_MPL:
        return
    rows = res['rows']
    names = [r['name'] for r in rows]
    contribs = [r['contrib'] for r in rows]
    weights = [r['w'] for r in rows]
    deltas = None
    if prev_contrib:
        deltas = [r['contrib'] - prev_contrib.get(r['name'], 0.0) for r in rows]
    rets_list = None
    if rets:
        rets_list = [rets.get(r['name']) for r in rows]
    idx_pct = res.get('idx_pct')
    title = f"{res['name']} ({res['code']}) 板块贡献归因  @ {res['date']}"
    sub_parts = []
    if idx_pct is not None:
        dev = res['total_contrib'] - idx_pct
        sub_parts.append(f"指数涨跌 {idx_pct:+.2f}%   Σ贡献 {res['total_contrib']:+.2f}pt   重构误差 {dev:+.2f}pt")
    sub_parts.append('红=拉涨  绿=砸盘  最左列=权重占比%')
    if deltas is not None:
        sub_parts.append('↑↓=贡献较前日增减(pt)  5/10/20日=板块多周期累计涨幅')
    subtitle = '      '.join(sub_parts)
    outpath = os.path.join(SCRIPT_DIR, 'output', f"{res['code'].split('.')[0]}_{res['date']}_板块贡献.png")
    draw_diverging(names, contribs, weights, title, subtitle, outpath,
                   deltas=deltas, rets=rets_list, windows=windows)


def save_range_chart(name, code, agg, start_date, end_date, n_days):
    """区间累计贡献发散图"""
    if not _HAS_MPL:
        return
    rows = [{'name': l1, 'avg_w': (d['w_sum'] / d['n'] if d['n'] else 0), 'contrib': d['contrib']}
            for l1, d in agg.items()]
    names = [r['name'] for r in rows]
    contribs = [r['contrib'] for r in rows]
    weights = [r['avg_w'] for r in rows]
    title = f"{name} ({code}) 区间板块累计贡献  {n_days} 个交易日"
    code_short = code.split('.')[0]
    outpath = os.path.join(SCRIPT_DIR, 'output', f"{code_short}_{start_date}_{end_date}_区间累计贡献.png")
    draw_diverging(names, contribs, weights, title,
                   f"{start_date} → {end_date}   红=拉涨  绿=砸盘  最左列=平均权重%", outpath)


def print_range_result(name, code, agg, arith_ret, geom_ret, n_days):
    print()
    print('=' * 74)
    print(f"{name} ({code}) 区间板块累计贡献   {n_days} 个交易日")
    print('=' * 74)
    geom_pct = (geom_ret - 1) * 100
    print(f"区间指数涨跌: 算术累计 {arith_ret:+.2f}%   复利累计 {geom_pct:+.2f}%")
    rows = [{'name': l1, 'avg_w': (d['w_sum'] / d['n'] if d['n'] else 0), 'contrib': d['contrib']}
            for l1, d in agg.items()]
    rows.sort(key=lambda x: -x['contrib'])
    total = sum(r['contrib'] for r in rows)
    err = total - geom_pct
    print(f"Σ板块累计贡献: {total:+.2f}pt   重构误差 {err:+.2f}pt")
    print()
    pos_sum = sum(r['contrib'] for r in rows if r['contrib'] > 0)
    neg_sum = sum(r['contrib'] for r in rows if r['contrib'] < 0)
    print(f"{'排名':<4}{'方向':<4}{'行业':<10}{'平均权重':>10}{'累计贡献(pt)':>12}{'占同向力%':>10}")
    print('-' * 74)
    for i, r in enumerate(rows, 1):
        c = r['contrib']
        if c > 0:
            direction, share = '↑', (c / pos_sum * 100 if pos_sum > 0 else 0)
        elif c < 0:
            direction, share = '↓', (abs(c) / abs(neg_sum) * 100 if neg_sum < 0 else 0)
        else:
            direction, share = '·', 0
        print(f"{i:<4}{direction:<4}{r['name']:<10}{r['avg_w']:>9.2f}%{c:>+11.2f}{share:>9.1f}%")
    print('-' * 74)
    print("说明: 累计贡献=区间内每日贡献(前日市值加权×涨跌)算术累加。")
    print("      重构误差=Σ累计贡献−区间复利涨跌, 越小越准。平均权重=区间内每日权重均值。")


def run_range(start_date, end_date, do_sh, do_hs300):
    trade_days = get_trade_days(start_date, end_date)
    if not trade_days:
        raise SystemExit(f'[FATAL] {start_date}→{end_date} 区间内无交易日')
    print(f"[信息] 区间 {trade_days[0]} → {trade_days[-1]} 共 {len(trade_days)} 个交易日", file=sys.stderr)

    industry_map = fetch_industry_map()

    sh_agg = defaultdict(lambda: {'contrib': 0.0, 'w_sum': 0.0, 'n': 0})
    hs_agg = defaultdict(lambda: {'contrib': 0.0, 'w_sum': 0.0, 'n': 0})
    sh_arith = hs_arith = 0.0
    sh_geom = hs_geom = 1.0

    for i, td in enumerate(trade_days):
        parts = [f"[{i + 1}/{len(trade_days)}] {td}"]
        if do_sh:
            res, el = attribution_sh(td, industry_map)
            save_csv(res, subdir='daily')
            for r in res['rows']:
                sh_agg[r['name']]['contrib'] += r['contrib']
                sh_agg[r['name']]['w_sum'] += r['w']
                sh_agg[r['name']]['n'] += 1
            if res['idx_pct'] is not None:
                sh_arith += res['idx_pct']
                sh_geom *= (1 + res['idx_pct'] / 100)
            parts.append(f"上证 {res['idx_pct']:+.2f}%")
        if do_hs300:
            res, el = attribution_hs300(td, industry_map)
            save_csv(res, subdir='daily')
            for r in res['rows']:
                hs_agg[r['name']]['contrib'] += r['contrib']
                hs_agg[r['name']]['w_sum'] += r['w']
                hs_agg[r['name']]['n'] += 1
            if res['idx_pct'] is not None:
                hs_arith += res['idx_pct']
                hs_geom *= (1 + res['idx_pct'] / 100)
            parts.append(f"HS300 {res['idx_pct']:+.2f}%")
        print('  ' + '  '.join(parts), file=sys.stderr)

    if do_sh:
        print_range_result('上证综指', '000001.SH', sh_agg, sh_arith, sh_geom, len(trade_days))
        save_range_csv('000001', sh_agg, start_date, end_date)
        save_range_chart('上证综指', '000001.SH', sh_agg, start_date, end_date, len(trade_days))
    if do_hs300:
        print_range_result('沪深300', '000300.SH', hs_agg, hs_arith, hs_geom, len(trade_days))
        save_range_csv('000300', hs_agg, start_date, end_date)
        save_range_chart('沪深300', '000300.SH', hs_agg, start_date, end_date, len(trade_days))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    flags = [a for a in sys.argv[1:] if a.startswith('-')]
    do_sh = '--hs300' not in flags
    do_hs300 = '--sh' not in flags

    start_date = end_date = None
    for f in flags:
        if f.startswith('--start='):
            start_date = f.split('=', 1)[1]
        elif f.startswith('--end='):
            end_date = f.split('=', 1)[1]

    if start_date or end_date:
        run_range(start_date or end_date, end_date or start_date, do_sh, do_hs300)
        return

    target = args[0] if args else None

    trade_date = find_last_trade_day(target)
    print(f"[信息] 交易日: {trade_date}", file=sys.stderr)

    # 前一个交易日 + 板块多周期累计涨幅 (用于图内对比表达)
    prev_date = find_prev_trade_day(trade_date)
    rets = load_rets(trade_date)
    print(f"[信息] 前一日: {prev_date}   多周期涨幅缓存: {'有' if rets else '无'}", file=sys.stderr)

    industry_map = fetch_industry_map()

    if do_sh:
        res, el = attribution_sh(trade_date, industry_map)
        prev_res, _ = attribution_sh(prev_date, industry_map)
        prev_contrib = {r['name']: r['contrib'] for r in prev_res['rows']}
        print_result(res, el)
        save_csv(res)
        save_chart(res, prev_contrib=prev_contrib, rets=rets)
    if do_hs300:
        res, el = attribution_hs300(trade_date, industry_map)
        prev_res, _ = attribution_hs300(prev_date, industry_map)
        prev_contrib = {r['name']: r['contrib'] for r in prev_res['rows']}
        print_result(res, el)
        save_csv(res)
        save_chart(res, prev_contrib=prev_contrib, rets=rets)


if __name__ == '__main__':
    main()
