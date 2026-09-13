#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轮动市反转 · 大盘方向过滤 回测
================================
验证: 给「轮动市做反转」加一道「大盘方向」闸, 能否过滤掉 2021/2022 熊市接飞刀的亏损。

逻辑:
  原始 = 轮动市(10日IC<-0.1) → 做40日反转(买40日跌幅最深 top5)
  过滤 = 轮动市 且 大盘方向向上(dapan_direction==1) → 才做反转, 否则空仓

数据:
  上证指数 OHLC+量 用 tushare index_daily 拉取, 缓存到 output/sh_index_daily.csv
  板块涨跌幅用 output/sector_ret_cache.csv

用法: python3 backtest_direction_filter.py
"""

import os
import sys
import re
import json
import urllib.request
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
import dapan_direction

API_URL = 'http://api.tushare.pro'
ROT_THRESHOLD = 0.10
IC_WINDOW = 10
REV_WINDOW = 40
TOPN = 5


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


def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields:
        payload['fields'] = fields
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    result = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if result.get('code') != 0:
        raise RuntimeError(f'{api_name}: {result.get("msg")}')
    return result.get('data')


def load_sh_index():
    """拉上证指数 OHLC+量, 缓存到 output/sh_index_daily.csv"""
    cache = os.path.join(SCRIPT_DIR, 'output', 'sh_index_daily.csv')
    if os.path.exists(cache):
        df = pd.read_csv(cache)
        if len(df) > 0:
            return df
    # 多拉 40 天保证 direction 前 14 天预热充足
    data = api_call('index_daily', ts_code='000001.SH',
                    start_date='20200801', end_date='20260911',
                    fields='trade_date,close,high,low,vol')
    rows = sorted(data['items'], key=lambda x: x[0])
    df = pd.DataFrame(rows, columns=['trade_date', 'close', 'high', 'low', 'vol'])
    for c in ['close', 'high', 'low', 'vol']:
        df[c] = pd.to_numeric(df[c])
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    df.to_csv(cache, index=False)
    print(f'[缓存] 上证指数 {len(df)} 天 → {cache}', file=sys.stderr)
    return df


def rank_ic(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    # 1. 上证指数 + 大盘方向
    sh = load_sh_index()
    direction, p_up, p_down = dapan_direction.compute_direction(
        sh['close'].values, sh['high'].values, sh['low'].values, sh['vol'].values,
        return_probs=True)
    dir_map = dict(zip(sh['trade_date'].astype(str), direction))
    pdown_map = dict(zip(sh['trade_date'].astype(str), p_down))
    pup_map = dict(zip(sh['trade_date'].astype(str), p_up))

    # 2. 板块数据 + 轮动状态
    df = pd.read_csv(os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv'), index_col=0)
    df.index = df.index.astype(str)
    arr = df.values
    r = arr / 100.0
    n_days, n_sec = df.shape
    dir_arr = np.array([dir_map.get(td, 0) for td in df.index])
    pdown_arr = np.array([pdown_map.get(td, 50.0) for td in df.index])

    ic = np.full(n_days, np.nan)
    for t in range(1, n_days):
        ic[t] = rank_ic(arr[t], arr[t - 1])
    ic_ma = pd.Series(ic).rolling(IC_WINDOW, min_periods=IC_WINDOW).mean().values
    is_rot = ic_ma < -ROT_THRESHOLD
    is_up = dir_arr == 1          # 大盘明确向上
    is_down = dir_arr == -1       # 大盘明确向下
    is_safe = pdown_arr < 70      # 下跌概率 < 70% = 非熊市(避开下跌概率高的时段)

    # 3. 反转持仓
    ret_rev = df.rolling(REV_WINDOW, min_periods=REV_WINDOW).sum()
    full = pd.DataFrame(True, index=df.index, columns=df.columns)

    def pick(mask, sort_col, topn=TOPN):
        w = np.zeros_like(arr)
        for t in range(n_days):
            row = mask.iloc[t]
            if not row.any():
                continue
            idx = row[row].index
            sel = sort_col.iloc[t].loc[idx].sort_values().head(topn).index
            w[t, [df.columns.get_loc(s) for s in sel]] = 1.0 / len(sel)
        return w

    w_rev = pick(full, ret_rev)

    def daily_ret(w):
        wp = np.roll(w, 2, axis=0)
        wp[0] = 0.0
        wp[1] = 0.0
        return (wp * r).sum(axis=1)

    strategies = {
        '原始·轮动市反转(无过滤)': daily_ret(w_rev * is_rot[:, None]),
        '过滤·轮动+大盘向上才反转': daily_ret(w_rev * (is_rot & is_up)[:, None]),
        '过滤·下跌概率<70%才反转': daily_ret(w_rev * (is_rot & is_safe)[:, None]),
    }

    years = df.index.str[:4].values
    ylist = sorted(set(years))

    print('=' * 78)
    print(f'轮动市反转 · 大盘方向过滤回测  {df.index[0]} → {df.index[-1]}')
    print('=' * 78)
    print(f'大盘方向分布: 上升 {int(is_up.sum())} 天 / 下跌 {int(is_down.sum())} 天 / 无判定 {int((dir_arr==0).sum())} 天')
    print(f'轮动市: {int(is_rot.sum())} 天, 其中下跌概率<70% {int((is_rot&is_safe).sum())} 天, 被过滤(下跌概率≥70%) {int((is_rot&~is_safe).sum())} 天')
    print()
    print('分年收益(轮动市反转, 只算持仓期, T+1尾盘买入):')
    print(f"{'年份':<7}" + ''.join(f'{k:>28}' for k in strategies))
    for y in ylist:
        idx = np.where(years == y)[0]
        row = []
        for k in strategies:
            yy = strategies[k][idx]
            nav = np.cumprod(1 + yy)
            row.append(f'{nav[-1]*100-100:>+27.1f}%')
        print(f'{y:<7}' + ''.join(row))
    print()
    print('6年累计(复利):')
    for k in strategies:
        nav = np.cumprod(1 + strategies[k])
        print(f'  {k}: {nav[-1]*100-100:+.1f}%')


if __name__ == '__main__':
    main()
