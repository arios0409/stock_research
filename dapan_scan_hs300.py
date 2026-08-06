#!/usr/bin/env python3
"""
沪深300趋势扫描 V2 — Pu/Pdw概率交叉版（无状态机，即时应）
"""
import sys, os, json, urllib.request, traceback, re
from datetime import datetime, timedelta
import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator

# ===== 配置 =====
WEBHOOK_KEYS = {
    'bolikeli': '62d8c6d6-df0a-410b-915d-bd8bbdd145a8',   # 伯利克利群
    'dapan':    '8e9dc3b3-a85d-4d32-bcd7-d426f0477ef2',   # 大盘趋势群
}
INDEX_CODE = "000300.SH"
INDEX_NAME = "沪深300"
OUTPUT_SUBDIR = "1a.HS300_trend_detect"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "dapan_scan.log")

# Read token from original script
TUSHARE_TOKEN = "0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60"

os.makedirs(os.path.join(BASE_DIR, OUTPUT_SUBDIR), exist_ok=True)

def log(msg):
    ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts_str}] [HS300v2] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

log("========== 沪深300趋势扫描 V2 开始 ==========")

# Font
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf', '/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False

# ===== 1. Data =====
log(f"拉取{INDEX_NAME}数据...")
pro = ts.pro_api(TUSHARE_TOKEN)
end_date = datetime.now().strftime('%Y%m%d')
df = pro.index_daily(ts_code=INDEX_CODE, start_date="20240801", end_date=end_date)
df = df.sort_values("trade_date").reset_index(drop=True)
log(f"获取到 {len(df)} 条数据，最新: {df['trade_date'].iloc[-1]}")

close = df["close"].values; high = df["high"].values; low = df["low"].values
opens = df["open"].values; vol = df["vol"].values
dates = pd.to_datetime(df["trade_date"]).values
last_data_date = str(df['trade_date'].iloc[-1])
N, M1, M2 = 14, 5, 3

# ===== 2. KDJ =====
k = np.full(len(close), np.nan, dtype=float)
d = np.full(len(close), np.nan, dtype=float)
for i in range(N-1, len(close)):
    hh = np.max(high[i-N+1:i+1]); ll = np.min(low[i-N+1:i+1])
    rsv = 50.0 if hh == ll else (close[i]-ll)/(hh-ll)*100
    if np.isnan(k[i-1]): k[i]=rsv; d[i]=rsv
    else: k[i]=(rsv*1+k[i-1]*(M1-1))/M1; d[i]=(k[i]*1+d[i-1]*(M2-1))/M2

# ===== 3. MACD =====
def ema(data, span):
    result = np.full(len(data), np.nan); ke = 2./(span+1); result[0] = data[0]
    for i in range(1, len(data)): result[i] = data[i]*ke + result[i-1]*(1-ke)
    return result

ema12 = ema(close,12); ema26 = ema(close,26); dif = ema12-ema26; dea = ema(dif,9)
mb = np.zeros(len(close), dtype=bool); ms = np.zeros(len(close), dtype=bool)
for i in range(1, len(close)):
    if not np.isnan(dif[i]) and not np.isnan(dif[i-1]):
        mb[i] = (dif[i-1]<=dea[i-1]) and (dif[i]>dea[i])
        ms[i] = (dif[i-1]>=dea[i-1]) and (dif[i]<dea[i])
mt = np.zeros(len(close))
for i in range(len(close)):
    if not np.isnan(dif[i]) and not np.isnan(dea[i]):
        if dif[i]>dea[i] and (i==0 or dif[i]>dif[i-1]): mt[i]=1
        elif dif[i]>dea[i]: mt[i]=.5
        elif dif[i]<dea[i] and (i==0 or dif[i]<dif[i-1]): mt[i]=-1
        else: mt[i]=-.5

# ===== 4. Volume =====
vol_ma20 = np.full(len(close), np.nan)
for i in range(19, len(close)): vol_ma20[i] = np.mean(vol[i-19:i+1])
vol_ma5 = np.full(len(close), np.nan)
for i in range(4, len(close)): vol_ma5[i] = np.mean(vol[i-4:i+1])
vol_ratio = np.full(len(close), 1.0)
for i in range(len(close)):
    if not np.isnan(vol_ma20[i]) and vol_ma20[i]>0: vol_ratio[i] = vol[i]/vol_ma20[i]
vol_divergence = np.zeros(len(close))
for i in range(20, len(close)):
    ph = np.max(close[i-19:i])
    if close[i]>=ph*.995 and np.max(vol[i-19:i])>0 and vol[i]<np.max(vol[i-19:i])*.65: vol_divergence[i]=1
    pl = np.min(close[i-19:i])
    if close[i]<=pl*1.005 and np.mean(vol[i-19:i])>0 and vol[i]<np.mean(vol[i-19:i])*.6: vol_divergence[i]=-1
vol_trend = np.full(len(close), 0.0)
for i in range(len(close)):
    if not np.isnan(vol_ma5[i]) and not np.isnan(vol_ma20[i]) and vol_ma20[i]>0:
        vol_trend[i] = vol_ma5[i]/vol_ma20[i] - 1

# ===== 5. V3 Probability (same as before) =====
p_up = np.full(len(close), 50.); p_down = np.full(len(close), 50.); p_risk = np.full(len(close), 50.)
up_days = down_days = risk_days = 0

for i in range(N, len(close)):
    prev_up = p_up[i-1]; prev_down = p_down[i-1]; prev_risk = p_risk[i-1]
    is_golden = k[i-1]<=d[i-1] and k[i]>d[i]; is_death = k[i-1]>=d[i-1] and k[i]<d[i]
    high_death = is_death and k[i]>=85; in_down_zone = k[i]<35 and d[i]<40
    low_golden_bonus = is_golden and k[i]<30 and d[i]<30

    up_days = up_days+1 if k[i]>d[i] else 0
    down_days = down_days+1 if in_down_zone else 0
    risk_days = risk_days+1 if (k[i]<d[i] and k[i]>=85) else 0

    vr = vol_ratio[i]; vt = vol_trend[i]; vd = vol_divergence[i]
    mti = mt[i]; mbi = mb[i]; msi = ms[i]

    vbu = 0.; vbd = 0.; vpu = 0.; vpr = 0.
    if vr > 1.3:
        if k[i] > d[i]: vbu = min((vr-1)*12, 18)
        else: vbd = min((vr-1)*10, 15)
    elif vr < .5 and k[i] > d[i]: vpu = -10
    if vd > 0: vpr = 18; vpu -= 8
    elif vd < 0: vbu += 12
    if vt > .15 and k[i] > d[i]: vbu += min(vt*8, 8)
    elif vt < -.25 and k[i] > d[i]: vpu -= 5

    mbu = 0.; mbd = 0.; mbr = 0.
    if is_golden and mbi: mbu = 10
    elif is_golden and mti > 0: mbu = 5
    elif is_death and msi: mbd = 10
    elif is_death and mti < 0: mbd = 5
    if mti > .5: mbu += 3
    elif mti < -.5:
        mbd += 3
        if k[i] >= 70: mbr += 5

    if k[i] > d[i]:
        if low_golden_bonus: base = 80 + vbu + mbu
        elif is_golden: base = 60 + vbu + mbu
        else: base = min(60 + up_days*5 + vbu*.5 + mbu*.5, 92)
        p_up_val = max(base + vpu, 10)
    else:
        p_up_val = 30 if is_death else max(prev_up - (down_days*8 if down_days>0 else 3), 10)

    if in_down_zone: p_down_val = min(55 + down_days*5 + vbd + mbd, 88)
    elif k[i]<d[i] and k[i]<50: p_down_val = min(45+(50-k[i])*1.5 + vbd*.5 + mbd*.5, 80)
    elif high_death: p_down_val = 50 + vbd*.5 + mbd*.5
    elif risk_days >= 1: p_down_val = min(50 + risk_days*3 + mbd*.3, 70)
    elif is_golden: p_down_val = max(prev_down - 15, 10)
    else: p_down_val = max(prev_down - (2 if vr>=.8 else 1.5), 20)

    if high_death: p_risk_val = 65 + vpr*.3 + mbr
    elif risk_days>=1 and k[i]<d[i]: p_risk_val = min(65+risk_days*5 + vpr*.5 + mbr, 88)
    elif k[i]<d[i] and k[i]>=75: p_risk_val = min(45+(k[i]-75)*2 + vpr*.3 + mbr, 70)
    elif in_down_zone: p_risk_val = max(prev_risk - 10, 10)
    elif is_golden: p_risk_val = max(prev_risk - 20, 5)
    else: p_risk_val = max(prev_risk - 2 + vpr*.2, 15)

    p_up[i] = max(10, min(92, p_up_val))
    p_down[i] = max(10, min(88, p_down_val))
    p_risk[i] = max(5, min(88, p_risk_val))

# ===== 6. Direction: Pu > Pdw = UP, Pdw > Pu = DOWN (no state machine) =====
direction = np.full(len(close), 0, dtype=int)  # 1=UP, -1=DOWN
crosses = []  # (idx, direction, event_type)
for i in range(N, len(close)):
    if p_up[i] > p_down[i]:
        direction[i] = 1
        if p_up[i-1] <= p_down[i-1]:  # just crossed up
            crosses.append((i, 1, 'golden'))
    else:
        direction[i] = -1
        if p_up[i-1] >= p_down[i-1]:  # just crossed down
            crosses.append((i, -1, 'death'))

# ===== 7. Chart =====
log("生成趋势图表...")
c_bg = '#0d1117'; c_ax = '#161b22'
c_up = '#00ff00'; c_down = '#ff0000'
c_price = '#ffffff'; c_k = '#ff9900'; c_d = '#33ddff'; c_j = '#dd88ff'
c_grid = '#333333'; c_label = '#dddddd'

M4_DAYS = 80
m4_start = max(N, len(close)-M4_DAYS)
d4 = dates[m4_start:]; c4 = close[m4_start:]
dir4 = direction[m4_start:]

fig = plt.figure(figsize=(20, 14), facecolor=c_bg)
ax1 = fig.add_axes([0.07, 0.58, 0.90, 0.42], facecolor=c_ax)
ax2 = fig.add_axes([0.07, 0.40, 0.90, 0.16], facecolor=c_ax)
ax3 = fig.add_axes([0.07, 0.22, 0.90, 0.16], facecolor=c_ax)
ax4 = fig.add_axes([0.07, 0.02, 0.90, 0.18], facecolor=c_ax)

DFMT = lambda: mdates.DateFormatter('Y%yM%m')

def draw_direction(ax, da, ca, dira, show_label=True):
    ax.plot(da, ca, color=c_price, linewidth=1.6, alpha=0.95)
    i = 0
    while i < len(ca):
        if dira[i] == 0: i += 1; continue
        s = dira[i]; j = i
        while j < len(ca) and dira[j] == s: j += 1
        for idx in range(i, j):
            alpha = 0.15 if s == 1 else 0.12
            if idx < len(ca)-1:
                ax.axvspan(da[idx], da[idx+1], alpha=alpha, color=c_up if s==1 else c_down, linewidth=0, zorder=0)
        if show_label:
            mid = i + (j-i)//2
            if mid < len(ca):
                label = f"↑上升" if s==1 else "↓下跌"
                clr = c_up if s==1 else c_down
                ymax = np.max(ca)
                if j >= len(ca) - 5:
                    ax.text(da[mid], ymax+(ymax-np.min(ca))*0.05, label, color=clr, fontsize=14,
                            fontweight='bold', ha='center', va='bottom',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor=c_bg, edgecolor=clr, alpha=0.95, linewidth=2))
                else:
                    ax.text(da[mid], ymax+(ymax-np.min(ca))*0.02, label, color=clr, fontsize=9,
                            fontweight='bold', ha='center', va='bottom',
                            bbox=dict(boxstyle='round,pad=0.2', facecolor=c_bg, edgecolor=clr, alpha=0.85))
        i = j

# Subplot 1: Price + direction
y1_min, y1_max = np.min(close), np.max(close)
y1_range = y1_max - y1_min
draw_direction(ax1, dates, close, direction, show_label=True)
ax1.set_ylim(y1_min-y1_range*.10, y1_max+y1_range*.10)
ax1.set_ylabel(INDEX_NAME, color=c_label, fontsize=20)
ax1.tick_params(colors=c_label, labelsize=14)
ax1.grid(True, alpha=0.08, color=c_grid)
ax1.set_xlim(dates[0], dates[-1])
ax1.set_xticklabels([])

# Subplot 2: KDJ + crosses
ax2.plot(dates, k, color=c_k, linewidth=1.5, alpha=0.9)
ax2.plot(dates, d, color=c_d, linewidth=1.5, alpha=0.9)
ax2.plot(dates, 3*k-2*d, color=c_j, linewidth=0.8, alpha=0.5)
ax2.axhline(y=85, color=c_down, linestyle='--', alpha=0.4, linewidth=1.0)
ax2.axhline(y=35, color=c_down, linestyle='--', alpha=0.4, linewidth=1.0)

for idx, dr, evt in crosses:
    if evt == 'golden':
        ax2.scatter(dates[idx], k[idx], color=c_up, s=50, marker='^', zorder=6, edgecolors='white', linewidth=0.5)
    elif evt == 'death':
        ax2.scatter(dates[idx], k[idx], color=c_down, s=50, marker='v', zorder=6, edgecolors='white', linewidth=0.5)

ax2.set_ylabel('KDJ', color=c_label, fontsize=16)
ax2.tick_params(colors=c_label, labelsize=12)
ax2.grid(True, alpha=0.12, color=c_grid)
ax2.set_ylim(-10, 115)
ax2.set_xlim(dates[0], dates[-1])
ax2.set_xticklabels([])

# Subplot 3: Probability lines (Pu vs Pdw)
ax3.fill_between(dates[N:], p_up[N:], p_down[N:], where=p_up[N:]>=p_down[N:], color=c_up, alpha=0.15)
ax3.fill_between(dates[N:], p_up[N:], p_down[N:], where=p_up[N:]<p_down[N:], color=c_down, alpha=0.15)
ax3.plot(dates[N:], p_up[N:], color=c_up, linewidth=1.0, alpha=0.8, label='Pu上升')
ax3.plot(dates[N:], p_down[N:], color=c_down, linewidth=1.0, alpha=0.8, label='Pdw下跌')
ax3.axhline(y=50, color=c_grid, linestyle='--', alpha=0.5)
ax3.set_ylabel('概率%', color=c_label, fontsize=14)
ax3.tick_params(colors=c_label, labelsize=11)
ax3.grid(True, alpha=0.08, color=c_grid)
ax3.set_xlim(dates[N], dates[-1])
ax3.legend(loc='upper left', fontsize=9, facecolor=c_ax, edgecolor=c_grid, labelcolor=c_label)

# Subplot 4: Volume
vol_colors = [c_down if close[i] >= opens[i] else c_up for i in range(len(close))]
ax4.bar(dates, vol/1e8, color=vol_colors, alpha=0.6, width=0.7)
ax4.set_ylabel('成交量(亿手)', color=c_label, fontsize=14)
ax4.tick_params(colors=c_label, labelsize=11)
ax4.grid(True, alpha=0.1, color=c_grid)
ax4.set_xlim(dates[0], dates[-1])

for ax in [ax1, ax2, ax3, ax4]:
    ax.set_xlim(dates[0], dates[-1])
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(DFMT())
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=5))
    ax.tick_params(which='minor', colors=c_label, length=3)
plt.setp(ax4.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=11, color=c_label)

chart_path = os.path.join(BASE_DIR, OUTPUT_SUBDIR, f'{last_data_date}_{INDEX_NAME}_趋势图_v2.png')
fig.savefig(chart_path, dpi=150, facecolor=c_bg)
plt.close(fig)
log(f"图表已保存: {chart_path}")

# ===== 8. Message =====
last_idx = len(close)-1
cur_dir = "↑上升" if direction[last_idx] == 1 else "↓下跌"
cur_pu = p_up[last_idx]; cur_pd = p_down[last_idx]
gap = abs(cur_pu - cur_pd)

if direction[last_idx] == 1:
    advice = f"Pu({cur_pu:.0f}%) > Pdw({cur_pd:.0f}%) 差值{gap:.0f}%，上升趋势" if gap >= 10 else f"Pu略高于Pdw，上升信号偏弱({gap:.0f}%)，注意确认"
else:
    advice = f"Pdw({cur_pd:.0f}%) > Pu({cur_pu:.0f}%) 差值{gap:.0f}%，下跌趋势，观望" if gap >= 10 else f"Pdw略高于Pu，下跌信号偏弱({gap:.0f}%)，关注反转"

msg = f"""【{INDEX_NAME} Pu/Pdw概率交叉】{last_data_date}
当前方向: {cur_dir}
Pu(上升概率) {cur_pu:.0f}%  |  Pdw(下跌概率) {cur_pd:.0f}%
{advice}"""

# ===== 9. Send =====
def post(webhook_key, payload):
    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}'
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}

def upload_file(webhook_key, file_path):
    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={webhook_key}&type=file'
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        file_content = f.read()
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    ).encode('utf-8') + file_content + f'\r\n--{boundary}--\r\n'.encode('utf-8')
    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read().decode('utf-8'))
        return result.get('media_id', '') if result.get('errcode') == 0 else ''
    except Exception as e:
        log(f'上传异常: {e}')
        return ''

for name, key in WEBHOOK_KEYS.items():
    label = '伯利克利' if name == 'bolikeli' else '大盘趋势'
    log(f"发送到 {label}...")
    mid = upload_file(key, chart_path)
    if mid:
        r = post(key, {'msgtype': 'file', 'file': {'media_id': mid}})
        log(f'  图表: {r}')
    else:
        log(f'  图表上传失败')
    r = post(key, {'msgtype': 'markdown', 'markdown': {'content': msg}})
    log(f'  文字: {r}')

log("========== 沪深300趋势扫描 V2 完成 ==========")
