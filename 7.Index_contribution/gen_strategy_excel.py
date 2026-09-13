#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 2025-2026 大盘扫描 + 当日策略 Excel
列: 日期 | 上证涨跌% | 上升概率Pu% | 下降概率Pd% | Pu5日斜率 | 大盘方向 | 10日IC | 轮动状态 | 操作策略
"""
import os
import sys
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, 'output')
sys.path.insert(0, SCRIPT_DIR)
import dapan_direction

IC_WINDOW = 10
ROT_THRESHOLD = 0.10
TREND_THRESHOLD = 0.10
SLOPE_WINDOW = 5
PU_LEVEL = 60


def rank_ic(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    # ===== 1. 上证 Pu/Pd =====
    sh = pd.read_csv(os.path.join(OUT_DIR, 'sh_index_daily.csv'))
    sh['trade_date'] = sh['trade_date'].astype(str)
    _, p_up, p_down = dapan_direction.compute_direction(
        sh['close'].values, sh['high'].values, sh['low'].values, sh['vol'].values,
        return_probs=True)
    sh['pu'] = p_up
    sh['pd'] = p_down
    sh['ret'] = sh['close'].pct_change() * 100

    # ===== 2. 板块 10日IC =====
    ret = pd.read_csv(os.path.join(OUT_DIR, 'sector_ret_cache.csv'), index_col=0)
    ret.index = ret.index.astype(str)
    arr = ret.values
    n = len(arr)
    ic = np.full(n, np.nan)
    for t in range(1, n):
        ic[t] = rank_ic(arr[t], arr[t - 1])
    ic_ma = pd.Series(ic).rolling(IC_WINDOW, min_periods=IC_WINDOW).mean().values

    # ===== 3. 对齐并逐日生成 =====
    # 用 sh 的日期作为主轴 (Pu/Pd 需要 sh 的 OHLCV), 再对齐板块 IC
    ret_map = dict(zip(ret.index, range(len(ret))))
    ic_map = dict(zip(ret.index, ic_ma))
    # 20日/40日累计涨幅矩阵 (用于选板块)
    ret20 = ret.rolling(20, min_periods=20).sum()
    ret40 = ret.rolling(40, min_periods=40).sum()

    rows = []
    for i in range(len(sh)):
        td = sh['trade_date'].iloc[i]
        if td < '20250101':
            continue
        pu = sh['pu'].iloc[i]
        pd_ = sh['pd'].iloc[i]
        ret_pct = sh['ret'].iloc[i]
        # 斜率
        slope = pu - sh['pu'].iloc[i - SLOPE_WINDOW] if i >= SLOPE_WINDOW else np.nan
        # 方向 (V6 斜率信号)
        if np.isnan(slope):
            direction = '—'
        else:
            direction = '上升' if (slope > 0 or pu > PU_LEVEL) else '下跌'
        # 轮动 IC (对齐 sector_ret_cache)
        cur_ic = ic_map.get(td, np.nan)
        ri = ret_map.get(td)
        sectors_str = ''
        if np.isnan(cur_ic):
            regime = '—'
            strategy = '—'
            state_tag = '—'
        else:
            is_trend = cur_ic > TREND_THRESHOLD
            is_rot = cur_ic < -ROT_THRESHOLD
            if is_trend:
                regime = '持续市'
                strategy = '追动量，买20日涨幅 top5'
                state_tag = f'{direction}持续' if direction != '—' else '持续'
                if ri is not None:
                    top5 = ret20.iloc[ri].sort_values(ascending=False).head(5)
                    sectors_str = '、'.join(top5.index)
            elif is_rot:
                regime = '轮动市'
                rev_pass = (slope > 0) or (pu > PU_LEVEL) if not np.isnan(slope) else False
                if rev_pass:
                    strategy = '做反转，买40日跌幅 top5'
                    state_tag = f'{direction}轮动' if direction != '—' else '轮动'
                    if ri is not None:
                        top5 = ret40.iloc[ri].sort_values(ascending=True).head(5)
                        sectors_str = '、'.join(top5.index)
                else:
                    strategy = '空仓，不操作'
                    state_tag = f'{direction}轮动' if direction != '—' else '轮动'
            else:
                regime = '中性市'
                strategy = '躺平，尽量买小权重'
                state_tag = '中性'
        rows.append({
            '日期': td,
            '上证涨跌%': round(ret_pct, 2) if not np.isnan(ret_pct) else None,
            '上升概率Pu%': round(pu, 1),
            '下降概率Pd%': round(pd_, 1),
            'Pu5日斜率': round(slope, 1) if not np.isnan(slope) else None,
            '大盘方向': direction,
            '10日IC': round(cur_ic, 3) if not np.isnan(cur_ic) else None,
            '轮动状态': regime,
            '状态+打法': state_tag,
            '操作策略': strategy,
            '对应板块': sectors_str,
        })

    df = pd.DataFrame(rows)
    out = os.path.join(OUT_DIR, '大盘扫描策略_2025-2026_v2.xlsx')
    with pd.ExcelWriter(out, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='大盘扫描策略')
        ws = writer.sheets['大盘扫描策略']
        # 表头加粗 + 冻结首行 + 列宽
        from openpyxl.styles import Font, PatternFill
        header_font = Font(bold=True, color='FFFFFF')
        header_fill = PatternFill('solid', fgColor='4472C4')
        for c in ws[1]:
            c.font = header_font
            c.fill = header_fill
        ws.freeze_panes = 'A2'
        for col, w in zip('ABCDEFGHIJK', [12, 12, 14, 14, 12, 10, 10, 10, 12, 24, 32]):
            ws.column_dimensions[col].width = w
    print(f'[Excel] {out}')
    print(f'  行数: {len(df)}  ({df["日期"].iloc[0]} ~ {df["日期"].iloc[-1]})')
    print(f'  策略分布:')
    print(df['操作策略'].value_counts().to_string())


if __name__ == '__main__':
    main()
