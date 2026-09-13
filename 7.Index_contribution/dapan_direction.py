#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大盘方向判定 (复刻 dapan_scan_auto.py 的 V3 概率系统)
====================================================
从 dapan_scan_auto.py 提取的 KDJ(14,5,3) + MACD(12,26,9) + 成交量 → Pu/Pdw 概率 → 方向判定。
纯函数, 可被 rotation_regime.py 等复用, 不发送企业微信, 不改动生产脚本。

方向: Pu > Pdw = 上升(1), 否则 = 下跌(-1)。前 N(14) 天为 0(无判定)。
"""

import numpy as np


def compute_direction(close, high, low, vol, return_probs=False):
    """复刻 dapan_scan V3 方向判定。

    参数: close/high/low/vol 为 numpy 数组 (按时间升序, 长度一致)。
          return_probs=True 时返回 (direction, p_down) 元组, p_down 为下跌概率(10~88)。
    返回: direction 数组 (1=上升, -1=下跌, 0=无判定)。
    """
    close = np.asarray(close, dtype=float)
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    vol = np.asarray(vol, dtype=float)

    N, M1, M2 = 14, 5, 3

    # ===== KDJ(14,5,3) =====
    k = np.full(len(close), np.nan)
    d = np.full(len(close), np.nan)
    for i in range(N - 1, len(close)):
        hh = np.max(high[i - N + 1:i + 1])
        ll = np.min(low[i - N + 1:i + 1])
        rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
        if np.isnan(k[i - 1]):
            k[i] = rsv
            d[i] = rsv
        else:
            k[i] = (rsv * 1 + k[i - 1] * (M1 - 1)) / M1
            d[i] = (k[i] * 1 + d[i - 1] * (M2 - 1)) / M2

    # ===== MACD(12,26,9) =====
    def ema(data, span):
        result = np.full(len(data), np.nan, dtype=float)
        kk = 2.0 / (span + 1)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = data[i] * kk + result[i - 1] * (1 - kk)
        return result

    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    dif = ema12 - ema26
    dea = ema(dif, 9)

    macd_bullish = np.zeros(len(close), dtype=bool)
    macd_bearish = np.zeros(len(close), dtype=bool)
    for i in range(1, len(close)):
        if not np.isnan(dif[i]) and not np.isnan(dif[i - 1]):
            macd_bullish[i] = (dif[i - 1] <= dea[i - 1]) and (dif[i] > dea[i])
            macd_bearish[i] = (dif[i - 1] >= dea[i - 1]) and (dif[i] < dea[i])

    macd_trend = np.zeros(len(close), dtype=float)
    for i in range(len(close)):
        if not np.isnan(dif[i]) and not np.isnan(dea[i]):
            if dif[i] > dea[i] and (i == 0 or dif[i] > dif[i - 1]):
                macd_trend[i] = 1.0
            elif dif[i] > dea[i]:
                macd_trend[i] = 0.5
            elif dif[i] < dea[i] and (i == 0 or dif[i] < dif[i - 1]):
                macd_trend[i] = -1.0
            else:
                macd_trend[i] = -0.5

    # ===== 成交量特征 =====
    vol_ma20 = np.full(len(close), np.nan)
    for i in range(19, len(close)):
        vol_ma20[i] = np.mean(vol[i - 19:i + 1])
    vol_ma5 = np.full(len(close), np.nan)
    for i in range(4, len(close)):
        vol_ma5[i] = np.mean(vol[i - 4:i + 1])

    vol_ratio = np.full(len(close), 1.0)
    for i in range(len(close)):
        if not np.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
            vol_ratio[i] = vol[i] / vol_ma20[i]

    vol_divergence = np.zeros(len(close), dtype=float)
    for i in range(20, len(close)):
        price_high_20 = np.max(close[i - 19:i])
        if close[i] >= price_high_20 * 0.995:
            recent_vol_max = np.max(vol[i - 19:i])
            if recent_vol_max > 0 and vol[i] < recent_vol_max * 0.65:
                vol_divergence[i] = 1.0
        price_low_20 = np.min(close[i - 19:i])
        if close[i] <= price_low_20 * 1.005:
            recent_vol_avg = np.mean(vol[i - 19:i])
            if recent_vol_avg > 0 and vol[i] < recent_vol_avg * 0.6:
                vol_divergence[i] = -1.0

    vol_trend = np.full(len(close), 0.0)
    for i in range(len(close)):
        if not np.isnan(vol_ma5[i]) and not np.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
            vol_trend[i] = (vol_ma5[i] / vol_ma20[i]) - 1.0

    # ===== 概率系统 V3 =====
    p_up = np.full(len(close), 50.0)
    p_down = np.full(len(close), 50.0)
    p_risk = np.full(len(close), 50.0)
    up_days = down_days = risk_days = 0

    for i in range(N, len(close)):
        prev_up = p_up[i - 1]
        prev_down = p_down[i - 1]
        prev_risk = p_risk[i - 1]
        is_golden = k[i - 1] <= d[i - 1] and k[i] > d[i]
        is_death = k[i - 1] >= d[i - 1] and k[i] < d[i]
        high_death = is_death and k[i] >= 85
        in_down_zone = k[i] < 35 and d[i] < 40
        low_golden_bonus = is_golden and k[i] < 30 and d[i] < 30

        up_days = up_days + 1 if k[i] > d[i] else 0
        down_days = down_days + 1 if in_down_zone else 0
        risk_days = risk_days + 1 if (k[i] < d[i] and k[i] >= 85) else 0

        vr = vol_ratio[i]
        vt = vol_trend[i]
        vd = vol_divergence[i]
        mt = macd_trend[i]
        mb = macd_bullish[i]
        ms = macd_bearish[i]

        vol_boost_up = 0.0
        vol_boost_down = 0.0
        vol_penalty_up = 0.0
        vol_penalty_risk = 0.0

        if vr > 1.3:
            if k[i] > d[i]:
                vol_boost_up = min((vr - 1.0) * 12, 18)
            else:
                vol_boost_down = min((vr - 1.0) * 10, 15)
        elif vr < 0.5:
            if k[i] > d[i]:
                vol_penalty_up = -10

        if vd > 0:
            vol_penalty_risk = 18
            vol_penalty_up -= 8
        elif vd < 0:
            vol_boost_up += 12

        if vt > 0.15 and k[i] > d[i]:
            vol_boost_up += min(vt * 8, 8)
        elif vt < -0.25 and k[i] > d[i]:
            vol_penalty_up -= 5

        macd_boost_up = 0.0
        macd_boost_down = 0.0
        macd_boost_risk = 0.0

        if is_golden and mb:
            macd_boost_up = 10
        elif is_golden and mt > 0:
            macd_boost_up = 5
        elif is_death and ms:
            macd_boost_down = 10
        elif is_death and mt < 0:
            macd_boost_down = 5

        if mt > 0.5:
            macd_boost_up += 3
        elif mt < -0.5:
            macd_boost_down += 3
            if k[i] >= 70:
                macd_boost_risk += 5

        # P_UP
        if k[i] > d[i]:
            if low_golden_bonus:
                base = 80 + vol_boost_up + macd_boost_up
            elif is_golden:
                base = 60 + vol_boost_up + macd_boost_up
            else:
                base = min(60 + up_days * 5 + vol_boost_up * 0.5 + macd_boost_up * 0.5, 92)
            p_up_val = max(base + vol_penalty_up, 10)
        else:
            if is_death:
                p_up_val = 30
            else:
                p_up_val = max(prev_up - (down_days * 8 if down_days > 0 else 3), 10)

        # P_DOWN
        if in_down_zone:
            p_down_val = min(55 + down_days * 5 + vol_boost_down + macd_boost_down, 88)
        elif k[i] < d[i] and k[i] < 50:
            p_down_val = min(45 + (50 - k[i]) * 1.5 + vol_boost_down * 0.5 + macd_boost_down * 0.5, 80)
        elif high_death:
            p_down_val = 50 + vol_boost_down * 0.5 + macd_boost_down * 0.5
        elif risk_days >= 1:
            p_down_val = min(50 + risk_days * 3 + macd_boost_down * 0.3, 70)
        elif is_golden:
            p_down_val = max(prev_down - 15, 10)
        else:
            decay = 2 if vr >= 0.8 else 1.5
            p_down_val = max(prev_down - decay, 20)

        # P_RISK
        if high_death:
            p_risk_val = 65 + vol_penalty_risk * 0.3 + macd_boost_risk
        elif risk_days >= 1 and k[i] < d[i]:
            p_risk_val = min(65 + risk_days * 5 + vol_penalty_risk * 0.5 + macd_boost_risk, 88)
        elif k[i] < d[i] and k[i] >= 75:
            p_risk_val = min(45 + (k[i] - 75) * 2 + vol_penalty_risk * 0.3 + macd_boost_risk, 70)
        elif in_down_zone:
            p_risk_val = max(prev_risk - 10, 10)
        elif is_golden:
            p_risk_val = max(prev_risk - 20, 5)
        else:
            p_risk_val = max(prev_risk - 2 + vol_penalty_risk * 0.2, 15)

        p_up[i] = max(10, min(92, p_up_val))
        p_down[i] = max(10, min(88, p_down_val))
        p_risk[i] = max(5, min(88, p_risk_val))

    # ===== 方向判定 (Pu > Pdw = 上升) =====
    direction = np.zeros(len(close), dtype=int)
    for i in range(N, len(close)):
        if p_up[i] > p_down[i]:
            direction[i] = 1
        else:
            direction[i] = -1

    if return_probs:
        return direction, p_up, p_down
    return direction
