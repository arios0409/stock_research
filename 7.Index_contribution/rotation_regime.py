#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行情轮动性评估 (Rotation Regime Detector)
==========================================
判断当前市场是「轮动市」(板块快速切换) 还是「持续市」(主线明确)。

核心指标: 横截面动量的日度 Rank IC
  每天 31 个申万一级行业的涨跌幅 → 排名 → 算「今天排名 vs 昨天排名」的 Spearman 相关系数
  正 IC = 强者恒强(持续)，负 IC = 涨跌切换(轮动)

状态判定 (IC 的 N 日均值):
  IC_N < -ROT_THRESHOLD  → 轮动市 (绿)
  IC_N > +TREND_THRESHOLD → 持续市 (红)
  中间                    → 中性 (黄)

用法:
  python3 rotation_regime.py            # 拉最近 LOOKBACK_DAYS 天, 画图 + 输出结论
  调参: 改顶部 IC_WINDOW / ROT_THRESHOLD / TREND_THRESHOLD / LOOKBACK_DAYS
"""

import urllib.request, json, time, sys, os, re
import numpy as np
import pandas as pd
import dapan_direction
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
from datetime import datetime, timedelta
from collections import defaultdict

# ============ 可调参数 ============
IC_WINDOWS = [7, 10, 20]  # IC 均值窗口(交易日) —— 多窗口对比
MAIN_WINDOW = 10          # 主判定窗口(状态机/输出结论用)
ROT_THRESHOLD = 0.10      # IC < -阈值 → 轮动(绿)
TREND_THRESHOLD = 0.10    # IC > +阈值 → 持续(红)
LOOKBACK_DAYS = 800       # 画图回看交易日数 (约3年)

# ============ 配置 ============
API_URL = 'http://api.tushare.pro'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)


def _load_token():
    for p in [os.path.join(BASE_DIR, 'dapan_scan_auto.py'),
              os.path.join(BASE_DIR, '2.Industry_sector_select', 'hot_sectors_scanner.py')]:
        try:
            with open(p, encoding='utf-8') as f:
                m = re.search(r'TUSHARE_TOKEN\s*=\s*["\']([0-9a-fA-F]{20,})["\']', f.read())
                if m:
                    return m.group(1)
        except Exception:
            pass
    raise SystemExit('[FATAL] 未找到 TUSHARE_TOKEN')


TUSHARE_TOKEN = _load_token()

# ============ 申万二级 → 申万一级 映射 ============
SUB_TO_L1 = {
    '种植业': '农林牧渔', '渔业': '农林牧渔', '林业': '农林牧渔',
    '饲料': '农林牧渔', '农业综合': '农林牧渔',
    '食品': '食品饮料', '乳制品': '食品饮料', '白酒': '食品饮料',
    '啤酒': '食品饮料', '红黄酒': '食品饮料', '软饮料': '食品饮料',
    '纺织': '纺织服饰', '服饰': '纺织服饰',
    '造纸': '轻工制造', '家居用品': '轻工制造', '文教休闲': '轻工制造',
    '广告包装': '轻工制造', '纺织机械': '轻工制造', '轻工机械': '轻工制造',
    '医疗保健': '医药生物', '化学制药': '医药生物', '生物制药': '医药生物',
    '中成药': '医药生物', '医药商业': '医药生物',
    '火力发电': '公用事业', '水力发电': '公用事业', '新型电力': '公用事业',
    '水务': '公用事业', '供气供热': '公用事业', '环境保护': '公用事业',
    '公路': '交通运输', '路桥': '交通运输', '公共交通': '交通运输',
    '铁路': '交通运输', '空运': '交通运输', '机场': '交通运输',
    '港口': '交通运输', '水运': '交通运输', '仓储物流': '交通运输',
    '区域地产': '房地产', '全国地产': '房地产', '园区开发': '房地产',
    '房产服务': '房地产',
    '百货': '商贸零售', '商贸代理': '商贸零售', '其他商业': '商贸零售',
    '超市连锁': '商贸零售', '批发业': '商贸零售', '商品城': '商贸零售',
    '电器连锁': '商贸零售',
    '旅游景点': '社会服务', '旅游服务': '社会服务', '酒店餐饮': '社会服务',
    '综合类': '综合',
    '水泥': '建筑材料', '玻璃': '建筑材料', '陶瓷': '建筑材料',
    '其他建材': '建筑材料',
    '建筑工程': '建筑装饰', '装修装饰': '建筑装饰',
    '电气设备': '电力设备', '电器仪表': '电力设备',
    '航空': '国防军工', '船舶': '国防军工', '运输设备': '国防军工',
    '化工机械': '国防军工', '农用机械': '国防军工',
    '软件服务': '计算机', 'IT设备': '计算机', '互联网': '计算机',
    '影视音像': '传媒', '出版业': '传媒',
    '通信设备': '通信', '电信运营': '通信',
    '银行': '银行',
    '证券': '非银金融', '保险': '非银金融', '多元金融': '非银金融',
    '汽车整车': '汽车', '汽车配件': '汽车', '汽车服务': '汽车',
    '摩托车': '汽车',
    '专用机械': '机械设备', '机械基件': '机械设备', '机床制造': '机械设备',
    '工程机械': '机械设备',
    '铜': '有色金属', '铝': '有色金属', '铅锌': '有色金属',
    '黄金': '有色金属', '小金属': '有色金属', '矿物制品': '有色金属',
    '煤炭开采': '煤炭', '焦炭加工': '煤炭',
    '石油开采': '石油石化', '石油加工': '石油石化', '石油贸易': '石油石化',
    '普钢': '钢铁', '钢加工': '钢铁', '特种钢': '钢铁',
    '化工原料': '基础化工', '塑料': '基础化工', '橡胶': '基础化工',
    '农药化肥': '基础化工', '染料涂料': '基础化工', '化纤': '基础化工',
    '日用化工': '基础化工',
    '元器件': '电子', '半导体': '电子',
    '家用电器': '家用电器',
}
SUB_TO_L1_DEFAULT = '其他'


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


def find_last_trade_day():
    for offset in range(15):
        ds = (datetime.now() - timedelta(days=offset)).strftime('%Y%m%d')
        data = api_call('daily', trade_date=ds, limit=2, fields='ts_code,trade_date')
        if data and data.get('items'):
            return ds
        time.sleep(0.12)
    raise SystemExit('[FATAL] 未找到交易日')


def rank_ic(a, b):
    """a, b 为两天的行业涨跌幅向量, 算 Spearman 排名相关系数"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    t_start = time.time()

    # 1. 行业映射
    print('[1/5] 拉取行业映射...', file=sys.stderr)
    rows = fetch_all('stock_basic', fields='ts_code,industry', list_status='L')
    ind_map = {}
    for r in rows:
        sub = (r.get('industry') or '').strip()
        if sub:
            ind_map[r['ts_code']] = SUB_TO_L1.get(sub, SUB_TO_L1_DEFAULT)
    print(f'  行业映射 {len(ind_map)} 只股票', file=sys.stderr)

    # 2. 交易日列表
    print('[2/5] 获取交易日列表...', file=sys.stderr)
    last_day = find_last_trade_day()
    start_probe = (datetime.strptime(last_day, '%Y%m%d') - timedelta(days=int(LOOKBACK_DAYS * 1.8) + 20)).strftime('%Y%m%d')
    cal = api_call('trade_cal', exchange='SSE', start_date=start_probe, end_date=last_day,
                   fields='cal_date,is_open')
    trade_days = sorted(r['cal_date'] for r in parse_data(cal) if str(r.get('is_open', '')) == '1')
    trade_days = trade_days[-LOOKBACK_DAYS:]
    print(f'  交易日 {trade_days[0]} → {trade_days[-1]} 共 {len(trade_days)} 天', file=sys.stderr)

    # 3. 逐日拉全市场涨跌 + 聚合行业涨跌 (增量缓存)
    print('[3/5] 聚合行业涨跌...', file=sys.stderr)
    CACHE_PATH = os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv')
    ret_df = None
    cached = None
    if os.path.exists(CACHE_PATH) and '--refresh' not in sys.argv:
        cached = pd.read_csv(CACHE_PATH, index_col=0)
        cached.index = cached.index.astype(str)
        if all(td in cached.index for td in trade_days):
            ret_df = cached.reindex(trade_days)
            print('  [缓存] 复用 sector_ret_cache.csv', file=sys.stderr)

    if ret_df is None:
        # 增量更新: 只拉缓存缺失的交易日
        missing = [td for td in trade_days if cached is None or td not in cached.index]
        print(f'  [增量] 拉取 {len(missing)} 个缺失交易日', file=sys.stderr)
        sector_ret = {}
        for i, td in enumerate(missing):
            if i % 20 == 0:
                print(f'  {i + 1}/{len(missing)} ({td})', file=sys.stderr)
            rows = fetch_all('daily', fields='ts_code,pct_chg', trade_date=td)
            df = pd.DataFrame(rows)
            if df.empty:
                continue
            df['pct_chg'] = pd.to_numeric(df['pct_chg'], errors='coerce')
            df['l1'] = df['ts_code'].map(ind_map)
            df = df.dropna(subset=['pct_chg', 'l1'])
            sector_ret[td] = df.groupby('l1')['pct_chg'].mean().to_dict()
            time.sleep(0.05)
        new_df = pd.DataFrame.from_dict(sector_ret, orient='index')
        # 完整缓存 = 旧缓存 + 新数据 (保留全部历史, 不截断)
        full_cache = pd.concat([cached, new_df]) if cached is not None else new_df
        full_cache = full_cache[~full_cache.index.duplicated(keep='last')].sort_index()
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        full_cache.to_csv(CACHE_PATH)
        ret_df = full_cache.reindex(trade_days)  # 计算/画图用最近 LOOKBACK_DAYS 天
        print('  [缓存] 已更新 sector_ret_cache.csv (保留完整历史)', file=sys.stderr)

    top1_name = ret_df.idxmax(axis=1).to_dict()
    top1_ret = ret_df.max(axis=1).to_dict()
    print(f'  矩阵: {ret_df.shape[0]} 天 × {ret_df.shape[1]} 个行业', file=sys.stderr)

    # 4. 上证指数
    print('[4/5] 拉取上证指数...', file=sys.stderr)
    idx = api_call('index_daily', ts_code='000001.SH',
                   start_date=trade_days[0], end_date=trade_days[-1],
                   fields='trade_date,close,high,low,vol')
    idx_rows = parse_data(idx)
    sh_close = {r['trade_date']: float(r['close']) for r in idx_rows}
    sh_high = {r['trade_date']: float(r['high']) for r in idx_rows}
    sh_low = {r['trade_date']: float(r['low']) for r in idx_rows}
    sh_vol = {r['trade_date']: float(r['vol']) for r in idx_rows}
    closes = [sh_close.get(td, np.nan) for td in trade_days]
    highs = [sh_high.get(td, np.nan) for td in trade_days]
    lows = [sh_low.get(td, np.nan) for td in trade_days]
    vols = [sh_vol.get(td, np.nan) for td in trade_days]

    # 5. 算 IC + 状态
    print('[5/5] 计算 IC 与状态...', file=sys.stderr)
    arr = ret_df.values  # (T, 31)
    ic_daily = np.full(len(trade_days), np.nan)
    for t in range(1, len(trade_days)):
        if not np.isnan(arr[t]).all() and not np.isnan(arr[t - 1]).all():
            ic_daily[t] = rank_ic(arr[t], arr[t - 1])

    ic_ma_dict = {}
    for w in IC_WINDOWS:
        ic_ma_dict[w] = pd.Series(ic_daily).rolling(w, min_periods=w).mean().values
    ic_ma = ic_ma_dict[MAIN_WINDOW]  # 主窗口用于状态判定

    state = np.zeros(len(trade_days), dtype=int)  # 1=轮动(绿), -1=持续(红), 0=中性(黄)
    for t in range(len(trade_days)):
        v = ic_ma[t]
        if np.isnan(v):
            state[t] = 0
        elif v < -ROT_THRESHOLD:
            state[t] = 1
        elif v > TREND_THRESHOLD:
            state[t] = -1
        else:
            state[t] = 0

    # 大盘方向 (复刻 dapan_scan V3)
    direction = dapan_direction.compute_direction(
        np.array(closes), np.array(highs), np.array(lows), np.array(vols))

    # ===== 画图 =====
    c_bg = '#0d1117'; c_ax = '#161b22'
    c_rot = '#00ff00'      # 轮动 = 绿
    c_trd = '#ff0000'      # 持续 = 红
    c_neu = '#ffcc00'      # 中性 = 黄
    c_price = '#ffffff'; c_grid = '#333333'; c_label = '#dddddd'
    c_ic = '#888888'   # 日度IC散点(灰, 弱化噪音)

    from matplotlib import font_manager as fm
    for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
        if os.path.exists(fp):
            fm.fontManager.addfont(fp)
    plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False

    dates = pd.to_datetime(trade_days).values

    def state_color(s):
        return c_rot if s == 1 else (c_trd if s == -1 else c_neu)

    def draw_spans(ax, d, c, st):
        ax.plot(d, c, color=c_price, linewidth=1.6, alpha=0.95)
        i = 0
        while i < len(c):
            if st[i] == 0:
                i += 1
                continue
            s = st[i]; j = i
            while j < len(c) and st[j] == s:
                j += 1
            for idx in range(i, j):
                if idx < len(c) - 1:
                    ax.axvspan(d[idx], d[idx + 1], alpha=0.18 if s == 1 else 0.14,
                               color=state_color(s), linewidth=0, zorder=0)
            mid = i + (j - i) // 2
            if mid < len(c):
                label = '轮动' if s == 1 else '持续'
                ymax = np.nanmax(c)
                ymin = np.nanmin(c)
                fs = 14 if j >= len(c) - 5 else 9
                ax.text(d[mid], ymax + (ymax - ymin) * 0.04, label, color=state_color(s),
                        fontsize=fs, fontweight='bold', ha='center', va='bottom',
                        bbox=dict(boxstyle='round,pad=0.25', facecolor=c_bg,
                                  edgecolor=state_color(s), alpha=0.9, linewidth=2 if fs == 14 else 1))
            i = j

    fig = plt.figure(figsize=(20, 16), facecolor=c_bg)
    ax1 = fig.add_axes([0.07, 0.79, 0.90, 0.16], facecolor=c_ax)   # 大盘方向
    ax2 = fig.add_axes([0.07, 0.61, 0.90, 0.16], facecolor=c_ax)   # 20日轮动
    ax3 = fig.add_axes([0.07, 0.43, 0.90, 0.16], facecolor=c_ax)   # 10日轮动
    ax4 = fig.add_axes([0.07, 0.25, 0.90, 0.16], facecolor=c_ax)   # 7日轮动
    ax5 = fig.add_axes([0.07, 0.03, 0.90, 0.19], facecolor=c_ax)   # IC曲线

    DATE_FMT = mdates.DateFormatter('%Y%m')

    c_arr = np.array(closes)

    def style_ax(ax, label, color=c_label, grid_alpha=0.08):
        y0, y1 = np.nanmin(c_arr), np.nanmax(c_arr)
        yr = y1 - y0
        ax.set_ylim(y0 - yr * 0.10, y1 + yr * 0.12)
        ax.set_ylabel(label, color=color, fontsize=13, fontweight='bold')
        ax.tick_params(colors=c_label, labelsize=11)
        ax.grid(True, alpha=grid_alpha, color=c_grid)
        ax.set_xlim(dates[0], dates[-1])
        ax.xaxis.set_major_formatter(DATE_FMT)
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
        ax.tick_params(which='minor', colors=c_label, length=3)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=11, color=c_label)

    def draw_rot(ax, rot_arr, color, label):
        """上证 + 单一窗口轮动区间 (axvspan 覆盖价格线)"""
        ax.plot(dates, c_arr, color=c_price, linewidth=1.4, alpha=0.95)
        i = 0
        while i < len(rot_arr):
            if not rot_arr[i]:
                i += 1
                continue
            j = i
            while j < len(rot_arr) and rot_arr[j]:
                j += 1
            ax.axvspan(dates[i], dates[min(j, len(dates) - 1)], color=color,
                       alpha=0.25, linewidth=0, zorder=0)
            i = j
        style_ax(ax, label, color)

    # 子图1: 大盘方向 (绿↑上升 / 红↓下跌, 复刻 dapan_scan 面板1)
    ax1.plot(dates, c_arr, color=c_price, linewidth=1.4, alpha=0.95)
    i = 0
    while i < len(c_arr):
        if direction[i] == 0:
            i += 1
            continue
        s = direction[i]
        j = i
        while j < len(c_arr) and direction[j] == s:
            j += 1
        for idx in range(i, j):
            if idx < len(c_arr) - 1:
                ax1.axvspan(dates[idx], dates[idx + 1], alpha=0.15 if s == 1 else 0.12,
                            color='#00ff00' if s == 1 else '#ff0000', linewidth=0, zorder=0)
        i = j
    style_ax(ax1, '大盘方向')

    # 子图2: 20日轮动 (浅绿)
    draw_rot(ax2, ic_ma_dict[20] < -ROT_THRESHOLD, '#00ff00', '20日轮动')
    # 子图3: 10日轮动 (蓝)
    draw_rot(ax3, ic_ma_dict[10] < -ROT_THRESHOLD, '#3388ff', '10日轮动')
    # 子图4: 7日轮动 (红)
    draw_rot(ax4, ic_ma_dict[7] < -ROT_THRESHOLD, '#ff4444', '7日轮动')

    # 子图5: IC 曲线
    ax5.axhline(y=0, color=c_label, alpha=0.4, linewidth=0.8)
    ax5.axhline(y=-ROT_THRESHOLD, color=c_rot, linestyle='--', alpha=0.6, linewidth=1.0)
    ax5.axhline(y=TREND_THRESHOLD, color=c_trd, linestyle='--', alpha=0.6, linewidth=1.0)
    ax5.scatter(dates, ic_daily, color=c_ic, s=10, alpha=0.35, label='日度IC')
    window_colors = ['#33ddff', '#ffee00', '#ff9900']  # 短→长窗口配色
    for i, w in enumerate(IC_WINDOWS):
        lw = 2.4 if w == IC_WINDOWS[-1] else 1.4
        ax5.plot(dates, ic_ma_dict[w], color=window_colors[i % len(window_colors)],
                 linewidth=lw, label=f'{w}日均值IC')
    ax5.fill_between(dates, ic_ma, 0, where=(ic_ma < 0), color=c_rot, alpha=0.08, interpolate=True)
    ax5.fill_between(dates, ic_ma, 0, where=(ic_ma > 0), color=c_trd, alpha=0.08, interpolate=True)
    ax5.set_ylabel('IC', color=c_label, fontsize=13)
    ax5.tick_params(colors=c_label, labelsize=11)
    ax5.grid(True, alpha=0.12, color=c_grid)
    ax5.set_xlim(dates[0], dates[-1])
    ax5.xaxis.set_major_formatter(DATE_FMT)
    ax5.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax5.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
    ax5.tick_params(which='minor', colors=c_label, length=3)
    plt.setp(ax5.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=11, color=c_label)
    ax5.legend(loc='upper left', fontsize=10, facecolor=c_ax, labelcolor=c_label)

    outdir = os.path.join(SCRIPT_DIR, 'output')
    os.makedirs(outdir, exist_ok=True)
    png = os.path.join(outdir, f'rotation_regime_{last_day}.png')
    fig.savefig(png, dpi=150, facecolor=c_bg)
    plt.close(fig)
    print(f'[图表] {png}', file=sys.stderr)

    # ===== 输出结论 =====
    cur_ic = ic_daily[-1]
    cur_state = state[-1]
    state_name = {1: '轮动市', -1: '持续市', 0: '中性'}[cur_state]
    print()
    print('=' * 60)
    print(f'行情轮动性评估  @ {last_day}  (阈值=±{ROT_THRESHOLD})')
    print('=' * 60)
    print(f'当前状态: {state_name}   (绿=轮动, 红=持续, 黄=中性)')
    print(f'日度 IC: {cur_ic:+.3f}')
    for w in IC_WINDOWS:
        print(f'  {w:>2}日均值 IC: {ic_ma_dict[w][-1]:+.3f}')
    print(f'阈值: 轮动 < {-ROT_THRESHOLD}  |  持续 > +{TREND_THRESHOLD}')
    # 近期状态分布
    recent = state[-20:]
    n_rot = int((recent == 1).sum())
    n_trd = int((recent == -1).sum())
    n_neu = int((recent == 0).sum())
    print(f'近20日状态: 轮动 {n_rot} 天 / 持续 {n_trd} 天 / 中性 {n_neu} 天')
    print(f'耗时 {time.time() - t_start:.1f}s')


if __name__ == '__main__':
    main()
