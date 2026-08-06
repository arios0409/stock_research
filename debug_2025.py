#!/usr/bin/env python3
"""沪深300 2025年逐笔分析"""
import numpy as np, tushare as ts

TOKEN="0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"
pro = ts.pro_api(TOKEN)
df_raw = pro.index_daily(ts_code="000300.SH", start_date="20220101", end_date="20260626")
df_raw = df_raw.sort_values("trade_date").reset_index(drop=True)
close = df_raw.close.values; high = df_raw.high.values; low = df_raw.low.values
vol = df_raw.vol.values; dates = df_raw.trade_date.values

ma20 = np.full(len(close), np.nan)
for i in range(19, len(close)): ma20[i] = np.mean(close[i-19:i+1])

def ema(data, span):
    r = np.full(len(data), np.nan); ke = 2./(span+1); r[0] = data[0]
    for i in range(1, len(data)): r[i] = data[i]*ke + r[i-1]*(1-ke)
    return r

N, M1, M2, HYST, CM = 12, 5, 3, 2.5, 1
k = np.full(len(close), np.nan); d = np.full(len(close), np.nan)
for i in range(N-1, len(close)):
    hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
    rsv = 50.0 if hh == ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i] = rsv; d[i] = rsv
    else: k[i] = (rsv*1 + k[i-1]*(M1-1))/M1; d[i] = (k[i]*1 + d[i-1]*(M2-1))/M2

ema12 = ema(close,12); ema26 = ema(close,26); dif = ema12-ema26; dea = ema(dif,9)
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

vm20 = np.full(len(close), np.nan); vm5 = np.full(len(close), np.nan)
for i in range(19, len(close)): vm20[i] = np.mean(vol[i-19:i+1])
for i in range(4, len(close)): vm5[i] = np.mean(vol[i-4:i+1])
vr = np.full(len(close), 1.); vt = np.full(len(close), 0.)
for i in range(len(close)):
    if not np.isnan(vm20[i]) and vm20[i] > 0: vr[i] = vol[i]/vm20[i]
    if not np.isnan(vm5[i]) and not np.isnan(vm20[i]) and vm20[i] > 0: vt[i] = vm5[i]/vm20[i] - 1.
vd = np.zeros(len(close))
for i in range(20, len(close)):
    ph = np.max(close[i-19:i])
    if close[i] >= ph*.995 and np.max(vol[i-19:i]) > 0 and vol[i] < np.max(vol[i-19:i])*.65: vd[i] = 1.
    pl = np.min(close[i-19:i])
    if close[i] <= pl*1.005 and np.mean(vol[i-19:i]) > 0 and vol[i] < np.mean(vol[i-19:i])*.6: vd[i] = -1.

pu = np.full(len(close), 50.); pdw = np.full(len(close), 50.); pr = np.full(len(close), 50.)
ud = dd = rd = 0
for i in range(N, len(close)):
    pup = pu[i-1]; pdp = pdw[i-1]; prp = pr[i-1]
    ig = k[i-1] <= d[i-1] and k[i] > d[i]; id_ = k[i-1] >= d[i-1] and k[i] < d[i]
    hd = id_ and k[i] >= 85; dz = k[i] < 35 and d[i] < 40; lgb = ig and k[i] < 30 and d[i] < 30
    ud = ud+1 if k[i] > d[i] else 0; dd = dd+1 if dz else 0; rd = rd+1 if (k[i] < d[i] and k[i] >= 85) else 0
    vri = vr[i]; vti = vt[i]; vdi = vd[i]; mti = mt[i]; mbi = mb[i]; msi = ms[i]
    vbu = 0.; vbd = 0.; vpu = 0.; vpr = 0.
    if vri > 1.3:
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
    pu[i] = max(10, min(92, puv)); pdw[i] = max(10, min(88, pdv)); pr[i] = max(5, min(88, prv))

state = np.full(len(close), 0, dtype=int); pc = 0; ps = 0; pnc = 0
for i in range(N, len(close)):
    pui = pu[i]; pdi = pdw[i]; pri = pr[i]
    if pui > pri + HYST and pui > pdi + HYST: rs = 1
    elif pri > pui + HYST and pri > pdi + HYST: rs = 2
    elif pdi > pui + HYST and pdi > pri + HYST: rs = 3
    else: rs = pc
    ig2 = k[i-1] <= d[i-1] and k[i] > d[i] if i > 0 else False
    ihd = (k[i-1] >= d[i-1] and k[i] < d[i] and k[i] >= 85) if i > 0 else False
    vri = vr[i]; vdi = vd[i]
    hcb = (ig2 and vri > 1.3) or (ig2 and mb[i]) or (vdi < 0) or (pui > 70 and vri > 1.2)
    hcbe = (ihd and vri > 1.3) or (ihd and ms[i]) or (vdi > 0 and k[i] > 70)
    cd = CM if (rs == 1 and hcb) or ((rs == 3 or rs == 2) and (hcbe or ihd)) else max(CM+1, 2)
    if rs != ps: ps = rs; pnc = 1
    else: pnc += 1
    if pnc >= cd: state[i] = ps; pc = ps
    else: state[i] = pc

# Run with and without MA20 filter for 2025
print("2025年沪深300交易对比:\n")

for use_ma, label in [(False, "无MA过滤"), (True, "MA20过滤")]:
    print(f"--- {label} ---")
    INIT = 100000; cash = INIT; sh = 0; ip = False
    yearly_ret = 0
    for i in range(N+1, len(close)):
        s = state[i]
        if dates[i].startswith("2025") and not ip:
            # start of year tracking
            if yearly_ret == 0 and cash > 0:
                yr_start_val = cash
        
        if not ip:
            can_buy = s == 1 and state[i-1] != 1
            if use_ma and can_buy:
                can_buy = not np.isnan(ma20[i]) and close[i] > ma20[i]
            if can_buy:
                ip = True; ep = close[i]; sh = cash / close[i]; cash = 0
                if dates[i].startswith("2025"):
                    print(f"  买 {dates[i]} @{close[i]:.0f} K{k[i]:.0f} D{d[i]:.0f} pu{pu[i]:.0f}%")
        else:
            if s == 2 or s == 3:
                ip = False; r = (close[i]-ep)/ep*100; cash = sh*close[i]; sh = 0
                if dates[i].startswith("2025"):
                    print(f"  卖 {dates[i]} @{close[i]:.0f} {r:+.1f}%")
        
        if dates[i].startswith("2025"):
            val = sh * close[i] if ip else cash
            if yearly_ret == 0 and cash > 0:
                yr_start_val = val
                yearly_ret = 1
    
    # Get 2025 last value
    yr_last = 0
    for i in range(len(close)-1, -1, -1):
        if dates[i].startswith("2025"):
            if ip: yr_last = sh * close[i]
            else: yr_last = cash
            break
    
    if yr_start_val > 0:
        yr_ret = (yr_last - yr_start_val) / yr_start_val * 100
        print(f"  2025收益: {yr_ret:+.1f}%")
    
    # Check missed rally period
    # Find 2025 high
    s2025 = next(i for i, d in enumerate(dates) if d.startswith("2025"))
    e2025 = next((i for i, d in enumerate(dates) if d.startswith("2026")), len(dates)-1)
    idx_hi = np.max(close[s2025:e2025])
    idx_lo = np.min(close[s2025:e2025])
    hi_date = dates[s2025 + np.argmax(close[s2025:e2025])]
    print(f"  指数: {close[s2025]:.0f}->{close[e2025-1]:.0f} 高{idx_hi:.0f}({hi_date}) 低{idx_lo:.0f}")
    print()
