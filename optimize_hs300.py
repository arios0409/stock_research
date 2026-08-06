#!/usr/bin/env python3
"""沪深300 KDJ V3 参数优化"""
import numpy as np, tushare as ts, itertools
from datetime import datetime

TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)

df_raw = pro.index_daily(ts_code="000300.SH", start_date="20220101", end_date="20260626")
df_raw = df_raw.sort_values("trade_date").reset_index(drop=True)
close = df_raw.close.values; high = df_raw.high.values; low = df_raw.low.values
opens = df_raw.open.values; vol = df_raw.vol.values
dates_raw = df_raw.trade_date.values

def ema(data, span):
    r = np.full(len(data), np.nan); ke = 2. / (span + 1); r[0] = data[0]
    for i in range(1, len(data)): r[i] = data[i] * ke + r[i-1] * (1 - ke)
    return r

def backtest(N=14, M1=5, M2=3, HYST=3.0, CONFIRM_MIN=1, MIN_HOLD=0, VOL_THRESH=1.3):
    """返回 (total_return, win_rate, sharpe, max_dd, n_trades)"""
    # KDJ
    k = np.full(len(close), np.nan); d = np.full(len(close), np.nan)
    for i in range(N-1, len(close)):
        hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
        rsv = 50.0 if hh == ll else (close[i] - ll) / (hh - ll) * 100
        if np.isnan(k[i-1]): k[i] = rsv; d[i] = rsv
        else: k[i] = (rsv * 1 + k[i-1] * (M1-1)) / M1; d[i] = (k[i] * 1 + d[i-1] * (M2-1)) / M2
    
    # MACD
    ema12 = ema(close, 12); ema26 = ema(close, 26)
    dif = ema12 - ema26; dea = ema(dif, 9)
    mb = np.zeros(len(close), dtype=bool); ms = np.zeros(len(close), dtype=bool)
    for i in range(1, len(close)):
        if not np.isnan(dif[i]) and not np.isnan(dif[i-1]):
            mb[i] = (dif[i-1] <= dea[i-1]) and (dif[i] > dea[i])
            ms[i] = (dif[i-1] >= dea[i-1]) and (dif[i] < dea[i])
    mt = np.zeros(len(close))
    for i in range(len(close)):
        if not np.isnan(dif[i]) and not np.isnan(dea[i]):
            if dif[i] > dea[i] and (i == 0 or dif[i] > dif[i-1]): mt[i] = 1.
            elif dif[i] > dea[i]: mt[i] = .5
            elif dif[i] < dea[i] and (i == 0 or dif[i] < dif[i-1]): mt[i] = -1.
            else: mt[i] = -.5
    
    # Volume
    vm20 = np.full(len(close), np.nan); vm5 = np.full(len(close), np.nan)
    for i in range(19, len(close)): vm20[i] = np.mean(vol[i-19:i+1])
    for i in range(4, len(close)): vm5[i] = np.mean(vol[i-4:i+1])
    vr = np.full(len(close), 1.); vt = np.full(len(close), 0.)
    for i in range(len(close)):
        if not np.isnan(vm20[i]) and vm20[i] > 0: vr[i] = vol[i] / vm20[i]
        if not np.isnan(vm5[i]) and not np.isnan(vm20[i]) and vm20[i] > 0: vt[i] = vm5[i]/vm20[i] - 1.
    vd = np.zeros(len(close))
    for i in range(20, len(close)):
        ph = np.max(close[i-19:i])
        if close[i] >= ph * .995 and np.max(vol[i-19:i]) > 0 and vol[i] < np.max(vol[i-19:i]) * .65: vd[i] = 1.
        pl = np.min(close[i-19:i])
        if close[i] <= pl * 1.005 and np.mean(vol[i-19:i]) > 0 and vol[i] < np.mean(vol[i-19:i]) * .6: vd[i] = -1.
    
    # V3 probability
    pu = np.full(len(close), 50.); pdw = np.full(len(close), 50.); pr_ = np.full(len(close), 50.)
    ud = dd = rd = 0
    for i in range(N, len(close)):
        pup = pu[i-1]; pdp = pdw[i-1]; prp = pr_[i-1]
        ig = k[i-1] <= d[i-1] and k[i] > d[i]; id_ = k[i-1] >= d[i-1] and k[i] < d[i]
        hd = id_ and k[i] >= 85; dz = k[i] < 35 and d[i] < 40; lgb = ig and k[i] < 30 and d[i] < 30
        ud = ud + 1 if k[i] > d[i] else 0; dd = dd + 1 if dz else 0; rd = rd + 1 if (k[i] < d[i] and k[i] >= 85) else 0
        vri = vr[i]; vti = vt[i]; vdi = vd[i]; mti = mt[i]; mbi = mb[i]; msi = ms[i]
        vbu = 0.; vbd = 0.; vpu = 0.; vpr = 0.
        if vri > VOL_THRESH:
            if k[i] > d[i]: vbu = min((vri-1.)*12, 18)
            else: vbd = min((vri-1.)*10, 15)
        elif vri < .5 and k[i] > d[i]: vpu = -10
        if vdi > 0: vpr = 18; vpu -= 8
        elif vdi < 0: vbu += 12
        if vti > .15 and k[i] > d[i]: vbu += min(vti*8, 8)
        elif vti < -.25 and k[i] > d[i]: vpu -= 5
        mbu = 0.; mbd = 0.; mbr = 0.
        if ig and mbi: mbu = 10
        elif ig and mti > 0: mbu = 5
        elif id_ and msi: mbd = 10
        elif id_ and mti < 0: mbd = 5
        if mti > .5: mbu += 3
        elif mti < -.5: mbd += 3
        if k[i] >= 70 and mti < -.5: mbr += 5
        if k[i] > d[i]:
            if lgb: base = 80 + vbu + mbu
            elif ig: base = 60 + vbu + mbu
            else: base = min(60 + ud*5 + vbu*.5 + mbu*.5, 92)
            puv = max(base + vpu, 10)
        else: puv = 30 if id_ else max(pup - (dd*8 if dd > 0 else 3), 10)
        if dz: pdv = min(55 + dd*5 + vbd + mbd, 88)
        elif k[i] < d[i] and k[i] < 50: pdv = min(45 + (50-k[i])*1.5 + vbd*.5 + mbd*.5, 80)
        elif hd: pdv = 50 + vbd*.5 + mbd*.5
        elif rd >= 1: pdv = min(50 + rd*3 + mbd*.3, 70)
        elif ig: pdv = max(pdp - 15, 10)
        else: pdv = max(pdp - (2 if vri >= .8 else 1.5), 20)
        if hd: prv = 65 + vpr*.3 + mbr
        elif rd >= 1 and k[i] < d[i]: prv = min(65 + rd*5 + vpr*.5 + mbr, 88)
        elif k[i] < d[i] and k[i] >= 75: prv = min(45 + (k[i]-75)*2 + vpr*.3 + mbr, 70)
        elif dz: prv = max(prp - 10, 10)
        elif ig: prv = max(prp - 20, 5)
        else: prv = max(prp - 2 + vpr*.2, 15)
        pu[i] = max(10, min(92, puv)); pdw[i] = max(10, min(88, pdv)); pr_[i] = max(5, min(88, prv))
    
    # State
    state = np.full(len(close), 0, dtype=int); pc = 0; ps = 0; pnc = 0
    for i in range(N, len(close)):
        pui = pu[i]; pdi = pdw[i]; pri = pr_[i]
        if pui > pri + HYST and pui > pdi + HYST: rs = 1
        elif pri > pui + HYST and pri > pdi + HYST: rs = 2
        elif pdi > pui + HYST and pdi > pri + HYST: rs = 3
        else: rs = pc
        ig2 = k[i-1] <= d[i-1] and k[i] > d[i] if i > 0 else False
        ihd = (k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85) if i > 0 else False
        vri = vr[i]; vdi = vd[i]
        hcb = (ig2 and vri > VOL_THRESH) or (ig2 and mb[i]) or (vdi < 0) or (pui > 70 and vri > 1.2)
        hcbe = (ihd and vri > VOL_THRESH) or (ihd and ms[i]) or (vdi > 0 and k[i] > 70)
        cd = CONFIRM_MIN if (rs == 1 and hcb) or ((rs == 3 or rs == 2) and (hcbe or ihd)) else max(CONFIRM_MIN + 1, 2)
        if rs != ps: ps = rs; pnc = 1
        else: pnc += 1
        if pnc >= cd: state[i] = ps; pc = ps
        else: state[i] = pc
    
    # Trading
    INIT = 100000; eq = np.full(len(close), np.nan); eq[N] = INIT
    cash = INIT; sh = 0; ip = False; tr = []; hold_days = 0; entry_idx = 0
    
    for i in range(N+1, len(close)):
        s = state[i]
        if not ip:
            if s == 1 and state[i-1] != 1:
                ip = True; ep = close[i]; sh = cash / close[i]; cash = 0
                hold_days = 0; entry_idx = i
        else:
            hold_days += 1
            # 最小持仓 + 卖出信号
            if hold_days >= MIN_HOLD and (s == 2 or s == 3):
                ip = False
                r = (close[i] - ep) / ep * 100; tr.append(r)
                cash = sh * close[i]; sh = 0
        eq[i] = sh * close[i] if ip else cash
    
    if ip:
        r = (close[-1] - ep) / ep * 100; tr.append(r)
        eq[-1] = sh * close[-1]
    
    for i in range(N+1, len(close)):
        if np.isnan(eq[i]): eq[i] = eq[i-1]
    
    final = eq[-1]; tot = (final - INIT) / INIT * 100
    wt = [t for t in tr if t > 0]; lt = [t for t in tr if t <= 0]
    
    pk = eq[N]; mxdd = 0
    for i in range(N, len(close)):
        if eq[i] > pk: pk = eq[i]
        ddv = (pk - eq[i]) / pk * 100
        if ddv > mxdd: mxdd = ddv
    
    # Sharpe
    dr = []
    for i in range(N+1, len(close)):
        if eq[i-1] > 0: dr.append((eq[i] - eq[i-1]) / eq[i-1])
    sh = np.mean(dr) / np.std(dr) * np.sqrt(252) if dr and np.std(dr) > 0 else -999
    
    return tot, len(wt)/len(tr)*100 if tr else 0, sh, mxdd, len(tr)

# ===== 参数扫描 =====
print("沪深300 KDJ V3 参数优化")
print(f"数据: {dates_raw[0]} ~ {dates_raw[-1]} ({len(dates_raw)}条)")
print()

# Baseline
b = backtest()
print(f"基准 (N=14 HYST=3): 总{b[0]:+.1f}% 胜率{b[1]:.0f}% 夏普{b[2]:.2f} 回撤{b[3]:.1f}% {b[4]}笔")
print()

# 扫描
results = []
params_to_try = []

# N variations
for N in [7, 9, 10, 12, 14, 16]:
    for HYST in [2.0, 2.5, 3.0, 3.5, 4.0]:
        for CONFIRM_MIN in [1, 2]:
            for MIN_HOLD in [0, 2, 3, 5]:
                params_to_try.append((N, HYST, CONFIRM_MIN, MIN_HOLD))

print(f"共 {len(params_to_try)} 组参数...")

best = None; best_score = -999
for N, HYST, CM, MH in params_to_try:
    try:
        tot, wr, sh, mxdd, nt = backtest(N=N, HYST=HYST, CONFIRM_MIN=CM, MIN_HOLD=MH)
        # Score: prefer high return, high sharpe, low drawdown
        score = tot * 0.5 + sh * 10 - mxdd * 0.3 + wr * 0.1
        results.append((score, tot, wr, sh, mxdd, nt, N, HYST, CM, MH))
        if score > best_score:
            best_score = score; best = (score, tot, wr, sh, mxdd, nt, N, HYST, CM, MH)
    except:
        continue

# Sort and show top 10
results.sort(key=lambda x: -x[0])
print(f"\nTop 10:")
print(f"{'排名':<5} {'收益':<8} {'胜率':<7} {'夏普':<7} {'回撤':<7} {'笔数':<5} {'N':<4} {'HYST':<6} {'确认':<5} {'持仓':<5}")
print("-" * 75)
for i, (s, tot, wr, sh, mxdd, nt, N, HYST, CM, MH) in enumerate(results[:10]):
    print(f"{i+1:<5} {tot:+6.1f}% {wr:5.0f}% {sh:+6.2f} {mxdd:5.1f}% {nt:4d}  {N:<4} {HYST:<6} {CM:<5} {MH:<5}")

print(f"\n最优参数: N={best[6]} HYST={best[7]} CONFIRM_MIN={best[8]} MIN_HOLD={best[9]}")
print(f"结果: 总收益{best[1]:+.1f}% 胜率{best[2]:.0f}% 夏普{best[3]:.2f} 回撤{best[4]:.1f}% {best[5]}笔")
