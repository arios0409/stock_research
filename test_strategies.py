#!/usr/bin/env python3
"""沪深300策略变体测试"""
import numpy as np, tushare as ts, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Read token from existing working file
with open('dapan_scan_auto.py') as f:
    import re
    m = re.search(r'TUSHARE_TOKEN\s*=\s*"([^"]+)"', f.read())
    TOKEN = m.group(1) if m else sys.exit("Token not found")

pro = ts.pro_api(TOKEN)
df_raw = pro.index_daily(ts_code="000300.SH", start_date="20220101", end_date="20260626")
df_raw = df_raw.sort_values("trade_date").reset_index(drop=True)
close = df_raw.close.values; high = df_raw.high.values; low = df_raw.low.values
vol = df_raw.vol.values; dates = df_raw.trade_date.values

def ema(data, span):
    r = np.full(len(data), np.nan); ke = 2./(span+1); r[0] = data[0]
    for i in range(1, len(data)): r[i] = data[i]*ke + r[i-1]*(1-ke)
    return r

def run(N=12, HYST=2.5, sell_risk=False, trail_pct=0):
    k = np.full(len(close), np.nan); d = np.full(len(close), np.nan)
    for i in range(N-1, len(close)):
        hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
        rsv = 50.0 if hh == ll else (close[i]-ll)/(hh-ll)*100
        if np.isnan(k[i-1]): k[i] = rsv; d[i] = rsv
        else: k[i] = (rsv*1 + k[i-1]*4)/5; d[i] = (k[i]*1 + d[i-1]*2)/3
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
        if not np.isnan(vm5[i]) and not np.isnan(vm20[i]) and vm20[i] > 0: vt[i] = vm5[i]/vm20[i]-1.
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
        cd = 1 if (rs == 1 and hcb) or ((rs == 3 or rs == 2) and (hcbe or ihd)) else 2
        if rs != ps: ps = rs; pnc = 1
        else: pnc += 1
        if pnc >= cd: state[i] = ps; pc = ps
        else: state[i] = pc
    
    INIT = 100000; eq = np.full(len(close), np.nan); eq[N] = INIT
    cash = INIT; sh = 0; ip = False; tr = []; high_se = 0
    for i in range(N+1, len(close)):
        s = state[i]
        if not ip:
            if s == 1 and state[i-1] != 1:
                ip = True; ep = close[i]; sh = cash/close[i]; cash = 0; high_se = close[i]
        else:
            high_se = max(high_se, close[i])
            do_sell = False
            if sell_risk:
                do_sell = (s == 2 or s == 3)
            else:
                do_sell = (s == 3)
            if trail_pct > 0 and close[i] <= high_se * (1 - trail_pct/100):
                do_sell = True
            if do_sell:
                ip = False; r = (close[i]-ep)/ep*100; tr.append(r)
                cash = sh*close[i]; sh = 0
        eq[i] = sh*close[i] if ip else cash
    
    if ip: r = (close[-1]-ep)/ep*100; tr.append(r); eq[-1] = sh*close[-1]
    for i in range(N+1, len(close)):
        if np.isnan(eq[i]): eq[i] = eq[i-1]
    
    final = eq[-1]; tot = (final-INIT)/INIT*100
    bh = (close[-1] - close[N]) / close[N] * 100
    wt = [t for t in tr if t > 0]; lt = [t for t in tr if t <= 0]
    pk = eq[N]; mxdd = 0
    for i in range(N, len(close)):
        if eq[i] > pk: pk = eq[i]
        ddv = (pk - eq[i]) / pk * 100
        if ddv > mxdd: mxdd = ddv
    dr = []
    for i in range(N+1, len(close)):
        if eq[i-1] > 0: dr.append((eq[i]-eq[i-1])/eq[i-1])
    shp = np.mean(dr)/np.std(dr)*np.sqrt(252) if dr and np.std(dr) > 0 else -999
    yret = []
    for yr in [2022,2023,2024,2025,2026]:
        s_ = next((i for i,d in enumerate(dates) if d.startswith(str(yr))), N)
        e_ = next((i for i,d in enumerate(dates) if d.startswith(str(yr+1))), len(dates)-1)
        if eq[s_] > 0: yret.append((eq[e_-1]-eq[s_])/eq[s_]*100)
    return tot, bh, len(wt)/len(tr)*100 if tr else 0, shp, mxdd, len(tr), yret

# Test
strategies = [
    ('原始(卖风险+下跌)', 12, 2.5, True, 0),
    ('只卖下跌', 12, 2.5, False, 0),
    ('只卖下跌+5%移动止盈', 12, 2.5, False, 5),
    ('只卖下跌+8%移动止盈', 12, 2.5, False, 8),
    ('只卖下跌+10%移动止盈', 12, 2.5, False, 10),
]

print(f"{'策略':<25} {'总收益':>8} {'BH':>8} {'胜率':>6} {'夏普':>6} {'回撤':>6} {'笔数':>5}")
print("-" * 75)
for label, N, HYST, sr, tp in strategies:
    tot, bh, wr, shp, mxdd, nt, yr = run(N, HYST, sr, tp)
    print(f"{label:<25} {tot:+7.1f}% {bh:+6.1f}% {wr:5.0f}% {shp:+5.2f} {mxdd:5.1f}% {nt:4d}")
    print(f"  {'逐年:':<23} {' | '.join(f'{r:+5.1f}%' for r in yr)}")
