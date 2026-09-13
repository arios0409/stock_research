#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取个股 OHLCV → 聚合 29 个申万一级行业的 OHLCV 缓存 (简单平均口径, 与 sector_ret_cache 一致)
用于板块级别的大盘扫描 V6 斜率信号回测。
"""
import os
import sys
import time
import pickle
import numpy as np
import pandas as pd

import rotation_regime as rr

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(SCRIPT_DIR, 'output', 'sector_ohlcv.pkl')
CACHE_PATH = os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv')


def main():
    t0 = time.time()

    # 1. 交易日 (与 sector_ret_cache 一致)
    ret_df = pd.read_csv(CACHE_PATH, index_col=0)
    ret_df.index = ret_df.index.astype(str)
    trade_days = list(ret_df.index)
    print(f'[1/4] 交易日 {trade_days[0]} → {trade_days[-1]} 共 {len(trade_days)} 天', file=sys.stderr)

    # 2. 行业映射
    print('[2/4] 拉取行业映射...', file=sys.stderr)
    rows = rr.fetch_all('stock_basic', fields='ts_code,industry', list_status='L')
    ind_map = {}
    for r in rows:
        sub = (r.get('industry') or '').strip()
        if sub:
            ind_map[r['ts_code']] = rr.SUB_TO_L1.get(sub, rr.SUB_TO_L1_DEFAULT)
    print(f'  行业映射 {len(ind_map)} 只股票', file=sys.stderr)

    # 3. 增量缓存加载
    cache = None
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, 'rb') as f:
            cache = pickle.load(f)
        print(f'  [缓存] 已有 {len(cache)} 个行业, 覆盖 {list(cache.values())[0].shape[0] if cache else 0} 天', file=sys.stderr)

    # 4. 逐日拉 OHLCV 聚合
    print('[3/4] 逐日拉个股 OHLCV 聚合行业...', file=sys.stderr)
    # 数据结构: sector_ohlcv[sector] = DataFrame(index=date, columns=[open,high,low,close,vol])
    if cache is None:
        sector_ohlcv = {}
        missing = trade_days
    else:
        sector_ohlcv = cache
        # 检查哪些日期缺失 (以任意一个行业为准)
        any_sec = list(cache.keys())[0]
        have_days = set(cache[any_sec].index)
        missing = [td for td in trade_days if td not in have_days]

    print(f'  缺失 {len(missing)} 天', file=sys.stderr)

    # 预收集: 每行业每天的 5 字段累加 + 计数
    from collections import defaultdict
    acc = defaultdict(lambda: defaultdict(lambda: [0.0]*5))  # [sector][date] = [open,high,low,close,vol] 累加
    cnt = defaultdict(lambda: defaultdict(int))

    for i, td in enumerate(missing):
        if i % 20 == 0:
            print(f'  {i+1}/{len(missing)} ({td})', file=sys.stderr)
        rows = rr.fetch_all('daily', fields='ts_code,open,high,low,close,vol', trade_date=td)
        if not rows:
            time.sleep(0.05)
            continue
        df = pd.DataFrame(rows)
        for c in ['open', 'high', 'low', 'close', 'vol']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df['l1'] = df['ts_code'].map(ind_map)
        df = df.dropna(subset=['open', 'high', 'low', 'close', 'vol', 'l1'])
        if df.empty:
            time.sleep(0.05)
            continue
        g = df.groupby('l1')[['open', 'high', 'low', 'close', 'vol']].sum()
        n = df.groupby('l1').size()
        for sec in g.index:
            acc[sec][td] = g.loc[sec].tolist()
            cnt[sec][td] = n.loc[sec]
        time.sleep(0.05)

    # 汇总成均值
    for sec in acc:
        for td, vals in acc[sec].items():
            vals = [v / cnt[sec][td] for v in vals]
            if sec not in sector_ohlcv:
                sector_ohlcv[sec] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'vol'])
            sector_ohlcv[sec].loc[td] = vals

    # 排序 index 并只保留 trade_days
    for sec in sector_ohlcv:
        sector_ohlcv[sec] = sector_ohlcv[sec].reindex(trade_days)

    print('[4/4] 保存缓存...', file=sys.stderr)
    with open(OUT_PATH, 'wb') as f:
        pickle.dump(sector_ohlcv, f)
    print(f'  保存 {OUT_PATH} ({len(sector_ohlcv)} 行业)', file=sys.stderr)
    print(f'完成, 耗时 {(time.time()-t0)/60:.1f} 分钟', file=sys.stderr)


if __name__ == '__main__':
    main()
