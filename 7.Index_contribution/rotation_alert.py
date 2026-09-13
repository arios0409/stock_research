#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轮动策略提示 (在大盘扫描 V6 之后运行)
=====================================
根据市场状态(10日IC) + Pu斜率过滤, 给出操作建议 + 板块贡献图 + 发送企业微信。

状态分支:
  持续市(10日IC > +0.1)        → 追动量, 20日涨幅 top5
  轮动市(10日IC < -0.1):
    斜率过滤通过(斜率>0 或 Pu>60) → 做反转, 40日跌幅 top5
    斜率过滤不通过               → 空仓, 不发送
  中性市(其余)                 → 躺平, 提示「躺平，尽量买小权重」

板块贡献图: 沪深300 + 上证 (调用 index_contribution.py 生成)

用法: python3 rotation_alert.py [--no-send]
"""

import os
import sys
import json
import base64
import hashlib
import urllib.request
import subprocess
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
import dapan_direction

# ===== 参数 (与 backtest_rotation.py 一致) =====
IC_WINDOW = 10
ROT_THRESHOLD = 0.10
TREND_THRESHOLD = 0.10
TOPN = 5
MOM_WINDOW = 20      # 动量窗口
REV_WINDOW = 40      # 反转窗口
SLOPE_WINDOW = 5     # Pu 斜率窗口
PU_LEVEL = 60        # Pu 水平阈值

# ===== 企业微信 webhook (与 dapan_scan_auto.py 一致) =====
WEBHOOK_KEYS = {
    'bolikeli': '62d8c6d6-df0a-410b-915d-bd8bbdd145a8',   # 伯利克利群
    'dapan':    '8e9dc3b3-a85d-4d32-bcd7-d426f0477ef2',   # 大盘趋势群
}


def rank_ic(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def load_pu(df_index):
    """读 sh_index_daily.csv 算 Pu, 对齐到板块数据日期, 返回 pu 数组"""
    sh_path = os.path.join(SCRIPT_DIR, 'output', 'sh_index_daily.csv')
    sh = pd.read_csv(sh_path)
    _, p_up, _ = dapan_direction.compute_direction(
        sh['close'].values, sh['high'].values, sh['low'].values, sh['vol'].values,
        return_probs=True)
    pu_map = dict(zip(sh['trade_date'].astype(str), p_up))
    return np.array([pu_map.get(td, 50.0) for td in df_index])


def post(webhook_key, payload):
    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}'
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}


def send_markdown(webhook_key, content):
    return post(webhook_key, {'msgtype': 'markdown', 'markdown': {'content': content}})


def send_image(webhook_key, file_path):
    if not os.path.exists(file_path):
        return {'errcode': -1, 'errmsg': f'图片不存在: {file_path}'}
    with open(file_path, 'rb') as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode()
    md5 = hashlib.md5(raw).hexdigest()
    return post(webhook_key, {'msgtype': 'image', 'image': {'base64': b64, 'md5': md5}})


def main():
    # ===== 1. 读板块数据 =====
    cache = os.path.join(SCRIPT_DIR, 'output', 'sector_ret_cache.csv')
    df = pd.read_csv(cache, index_col=0)
    df.index = df.index.astype(str)
    arr = df.values
    n_days, n_sec = df.shape
    trade_date = df.index[-1]

    # ===== 2. 10日IC + 状态 =====
    ic_daily = np.full(n_days, np.nan)
    for t in range(1, n_days):
        ic_daily[t] = rank_ic(arr[t], arr[t - 1])
    ic_ma = pd.Series(ic_daily).rolling(IC_WINDOW, min_periods=IC_WINDOW).mean().values
    cur_ic = ic_ma[-1]
    is_trend = cur_ic > TREND_THRESHOLD
    is_rot = cur_ic < -ROT_THRESHOLD

    # ===== 3. Pu 斜率过滤 =====
    pu = load_pu(df.index)
    cur_pu = pu[-1]
    cur_slope = pu[-1] - pu[-1 - SLOPE_WINDOW] if n_days > SLOPE_WINDOW else 0.0
    rev_pass = (cur_slope > 0) or (cur_pu > PU_LEVEL)

    # ===== 4. 分支生成建议 =====
    if is_trend:
        state = '持续市'
        ret = df.rolling(MOM_WINDOW, min_periods=MOM_WINDOW).sum().iloc[-1]
        top = ret.sort_values(ascending=False).head(TOPN)
        action = '追动量，买20日涨幅 top5'
        sectors = [(s, ret[s]) for s in top.index]
    elif is_rot:
        if not rev_pass:
            # 空仓: 轮动市但斜率过滤不通过
            print(f'[轮动策略] {trade_date} 轮动市(IC {cur_ic:+.3f}) 但斜率过滤不通过 '
                  f'(Pu {cur_pu:.0f}, 斜率 {cur_slope:+.0f}) → 空仓, 不发送', file=sys.stderr)
            return
        state = '轮动市'
        ret = df.rolling(REV_WINDOW, min_periods=REV_WINDOW).sum().iloc[-1]
        top = ret.sort_values(ascending=True).head(TOPN)
        action = '做反转，买40日跌幅 top5 (Pu斜率回升)'
        sectors = [(s, ret[s]) for s in top.index]
    else:
        state = '中性市'
        action = '躺平，尽量买小权重'
        sectors = []

    # ===== 5. 生成板块贡献图 (沪深300 + 上证) =====
    subprocess.run([sys.executable, os.path.join(SCRIPT_DIR, 'index_contribution.py'),
                    trade_date], cwd=SCRIPT_DIR, check=False)
    chart_sh = os.path.join(SCRIPT_DIR, 'output', f'000001_{trade_date}_板块贡献.png')
    chart_hs = os.path.join(SCRIPT_DIR, 'output', f'000300_{trade_date}_板块贡献.png')

    # ===== 6. 文字消息 =====
    lines = [f'【轮动策略提示】{trade_date}',
             f'市场状态: <font color=\"info\">{state}</font> (10日IC {cur_ic:+.3f})',
             f'打法: {action}']
    if sectors:
        lines.append('')
        for i, (s, ret) in enumerate(sectors, 1):
            lines.append(f'{i}. {s} ({ret:+.1f}%)')
    msg = '\n'.join(lines)

    # ===== 7. 发送 =====
    if '--no-send' in sys.argv:
        print(msg)
        print(f'[--no-send] 贡献图: {chart_sh}')
        print(f'[--no-send] 贡献图: {chart_hs}')
    else:
        for key in WEBHOOK_KEYS.values():
            send_markdown(key, msg)
            send_image(key, chart_sh)
            send_image(key, chart_hs)
        print('[发送完成]', file=sys.stderr)

    print(f'[轮动策略] {trade_date} {state}: {action}', file=sys.stderr)


if __name__ == '__main__':
    main()
