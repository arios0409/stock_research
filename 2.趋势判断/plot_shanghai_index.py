#!/usr/bin/env python3
"""
绘制上证指数 三子图：
1. 日K线 + MA10/MA20 + 趋势转折点标注
2. KDJ(14,5,3) + 转折点标注
3. 成交量柱状图

时间: 2025-11 ~ 2026-05-20
"""

import tushare as ts
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch
import os, warnings
warnings.filterwarnings('ignore')

# ============================================================
# 0. 字体配置
# ============================================================
def setup_chinese_font():
    """从 Windows 加载中文字体"""
    font_paths = [
        '/mnt/c/Windows/Fonts/simhei.ttf',
        '/mnt/c/Windows/Fonts/msyh.ttc',
        '/mnt/c/Windows/Fonts/simsun.ttc',
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            fm.fontManager.addfont(fp)
    # 优先 SimHei (黑体)
    plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif', [])
    plt.rcParams['axes.unicode_minus'] = False

setup_chinese_font()

# ============================================================
# 1. 获取数据
# ============================================================
TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
pro = ts.pro_api(TOKEN)

print("正在获取上证指数数据...")
df = pro.index_daily(
    ts_code='000001.SH',
    start_date='20240801',
    end_date='20260520'
)
# 按日期升序排列
df = df.sort_values('trade_date').reset_index(drop=True)
print(f"获取到 {len(df)} 个交易日数据")
print(f"日期范围: {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")

# 转换日期
df['date'] = pd.to_datetime(df['trade_date'])
df = df.set_index('date')

# ============================================================
# 2. 计算指标
# ============================================================

# --- MA10, MA20 ---
df['MA10'] = df['close'].rolling(window=10).mean()
df['MA20'] = df['close'].rolling(window=20).mean()

# --- KDJ(14,5,3) ---
N, M1, M2 = 14, 5, 3

# RSV
df['low_14'] = df['low'].rolling(window=N).min()
df['high_14'] = df['high'].rolling(window=N).max()
df['RSV'] = (df['close'] - df['low_14']) / (df['high_14'] - df['low_14']) * 100
df['RSV'] = df['RSV'].clip(0, 100)  # 防止除零

# K = SMA(RSV, M1, 1)
k_values = []
for i, rsv in enumerate(df['RSV']):
    if pd.isna(rsv):
        k_values.append(np.nan)
    elif i == 0 or np.isnan(k_values[-1]):
        k_values.append(rsv)
    else:
        k_values.append((rsv * 1 + k_values[-1] * (M1 - 1)) / M1)
df['K'] = k_values

# D = SMA(K, M2, 1)
d_values = []
for i, k_val in enumerate(k_values):
    if pd.isna(k_val):
        d_values.append(np.nan)
    elif i == 0 or np.isnan(d_values[-1]):
        d_values.append(k_val)
    else:
        d_values.append((k_val * 1 + d_values[-1] * (M2 - 1)) / M2)
df['D'] = d_values

df['J'] = 3 * df['K'] - 2 * df['D']

# ============================================================
# 3. 检测转折点
# ============================================================

# --- MA10/MA20 趋势转折 ---
# 上升趋势转折: MA10 上穿 MA20 (前一日 MA10 <= MA20, 当日 MA10 > MA20)
# 下降趋势转折: MA10 下穿 MA20 (前一日 MA10 >= MA20, 当日 MA10 < MA20)
ma_trend_up = []    # 上升趋势起点
ma_trend_down = []  # 下降趋势起点

for i in range(1, len(df)):
    if pd.isna(df['MA10'].iloc[i]) or pd.isna(df['MA10'].iloc[i-1]):
        continue
    if pd.isna(df['MA20'].iloc[i]) or pd.isna(df['MA20'].iloc[i-1]):
        continue
    
    # 上穿：前一日 MA10 <= MA20, 当日 MA10 > MA20
    if df['MA10'].iloc[i-1] <= df['MA20'].iloc[i-1] and df['MA10'].iloc[i] > df['MA20'].iloc[i]:
        ma_trend_up.append(df.index[i])
    
    # 下穿：前一日 MA10 >= MA20, 当日 MA10 < MA20
    if df['MA10'].iloc[i-1] >= df['MA20'].iloc[i-1] and df['MA10'].iloc[i] < df['MA20'].iloc[i]:
        ma_trend_down.append(df.index[i])

print(f"\nMA10/MA20 趋势转折:")
print(f"  上升趋势起点 (金叉): {len(ma_trend_up)} 个")
for d in ma_trend_up:
    print(f"    {d.strftime('%Y-%m-%d')}: MA10={df.loc[d,'MA10']:.1f}, MA20={df.loc[d,'MA20']:.1f}")
print(f"  下降趋势起点 (死叉): {len(ma_trend_down)} 个")
for d in ma_trend_down:
    print(f"    {d.strftime('%Y-%m-%d')}: MA10={df.loc[d,'MA10']:.1f}, MA20={df.loc[d,'MA20']:.1f}")

# --- KDJ 转折 ---
# K-D 金叉: K 上穿 D
# K-D 死叉: K 下穿 D
kdj_golden = []   # K上穿D (金叉)
kdj_death = []    # K下穿D (死叉)

for i in range(1, len(df)):
    if pd.isna(df['K'].iloc[i]) or pd.isna(df['K'].iloc[i-1]):
        continue
    if pd.isna(df['D'].iloc[i]) or pd.isna(df['D'].iloc[i-1]):
        continue
    
    # 金叉：前一日 K <= D, 当日 K > D
    if df['K'].iloc[i-1] <= df['D'].iloc[i-1] and df['K'].iloc[i] > df['D'].iloc[i]:
        kdj_golden.append(df.index[i])
    
    # 死叉：前一日 K >= D, 当日 K < D
    if df['K'].iloc[i-1] >= df['D'].iloc[i-1] and df['K'].iloc[i] < df['D'].iloc[i]:
        kdj_death.append(df.index[i])

print(f"\nKDJ(14,5,3) 转折:")
print(f"  K上穿D (金叉): {len(kdj_golden)} 个")
for d in kdj_golden:
    print(f"    {d.strftime('%Y-%m-%d')}: K={df.loc[d,'K']:.1f}, D={df.loc[d,'D']:.1f}")
print(f"  K下穿D (死叉): {len(kdj_death)} 个")
for d in kdj_death:
    print(f"    {d.strftime('%Y-%m-%d')}: K={df.loc[d,'K']:.1f}, D={df.loc[d,'D']:.1f}")

# 额外：KDJ超卖/超买区域
kdj_oversold = df[df['K'] < 20].index.tolist()    # K < 20 超卖
kdj_overbought = df[df['K'] > 80].index.tolist()  # K > 80 超买
print(f"  K<20 超卖天数: {len(kdj_oversold)}")
print(f"  K>80 超买天数: {len(kdj_overbought)}")

# ============================================================
# 4. 绘图
# ============================================================
fig = plt.figure(figsize=(18, 14), facecolor='#0d1117')

# ============ 上子图：价格 + MA ============
ax1 = fig.add_subplot(3, 1, 1, facecolor='#161b22')

# 收盘价线
ax1.plot(df.index, df['close'], color='#e6edf3', linewidth=1.2, label='收盘价', alpha=0.8)

# MA线
ax1.plot(df.index, df['MA10'], color='#f0883e', linewidth=1.5, alpha=0.9, label='MA10')
ax1.plot(df.index, df['MA20'], color='#58a6ff', linewidth=1.5, alpha=0.9, label='MA20')

# --- 标记趋势转折点 ---
# 上升趋势起点 (MA10上穿MA20) → 绿色箭头+标签
for dt in ma_trend_up:
    price = df.loc[dt, 'close']
    ax1.annotate('↑上升趋势',
                 xy=(dt, price),
                 xytext=(dt, price * 0.97),
                 fontsize=9, color='#3fb950', fontweight='bold',
                 ha='center',
                 arrowprops=dict(arrowstyle='->', color='#3fb950', lw=1.5),
                 bbox=dict(boxstyle='round,pad=0.2', facecolor='#0d1117', edgecolor='#3fb950', alpha=0.8))

# 下降趋势起点 (MA10下穿MA20) → 红色箭头+标签
for dt in ma_trend_down:
    price = df.loc[dt, 'close']
    ax1.annotate('↓下降趋势',
                 xy=(dt, price),
                 xytext=(dt, price * 0.97),
                 fontsize=9, color='#f85149', fontweight='bold',
                 ha='center',
                 arrowprops=dict(arrowstyle='->', color='#f85149', lw=1.5),
                 bbox=dict(boxstyle='round,pad=0.2', facecolor='#0d1117', edgecolor='#f85149', alpha=0.8))

ax1.set_title('上证指数 日线 (MA10/MA20 趋势转折)', fontsize=15, color='#e6edf3', fontweight='bold', pad=12)
ax1.legend(loc='upper left', fontsize=9, facecolor='#0d1117', edgecolor='#30363d', labelcolor='#e6edf3')
ax1.set_ylabel('价格', color='#8b949e', fontsize=10)
ax1.tick_params(colors='#8b949e', labelsize=9)
ax1.grid(True, alpha=0.15, color='#30363d')
ax1.set_xlim(df.index[0], df.index[-1])

# ============ 中子图：KDJ ============
ax2 = fig.add_subplot(3, 1, 2, facecolor='#161b22')

ax2.plot(df.index, df['K'], color='#f0883e', linewidth=1.2, label=f'K({M1})', alpha=0.9)
ax2.plot(df.index, df['D'], color='#58a6ff', linewidth=1.2, label=f'D({M2})', alpha=0.9)
ax2.plot(df.index, df['J'], color='#d2a8ff', linewidth=0.8, label='J', alpha=0.6)

# 超卖/超买区域
ax2.axhline(y=80, color='#f85149', linestyle='--', alpha=0.4, linewidth=0.8)
ax2.axhline(y=20, color='#3fb950', linestyle='--', alpha=0.4, linewidth=0.8)
ax2.fill_between(df.index, 80, 100, alpha=0.08, color='#f85149')
ax2.fill_between(df.index, 0, 20, alpha=0.08, color='#3fb950')

# 标注 KDJ 金叉/死叉
for dt in kdj_golden:
    k_val = df.loc[dt, 'K']
    ax2.annotate('金叉',
                 xy=(dt, k_val),
                 xytext=(dt, k_val + 12),
                 fontsize=7.5, color='#3fb950', fontweight='bold',
                 ha='center',
                 arrowprops=dict(arrowstyle='->', color='#3fb950', lw=1.2),
                 bbox=dict(boxstyle='round,pad=0.15', facecolor='#0d1117', edgecolor='#3fb950', alpha=0.7))

for dt in kdj_death:
    k_val = df.loc[dt, 'K']
    ax2.annotate('死叉',
                 xy=(dt, k_val),
                 xytext=(dt, k_val + 12),
                 fontsize=7.5, color='#f85149', fontweight='bold',
                 ha='center',
                 arrowprops=dict(arrowstyle='->', color='#f85149', lw=1.2),
                 bbox=dict(boxstyle='round,pad=0.15', facecolor='#0d1117', edgecolor='#f85149', alpha=0.7))

ax2.set_title(f'KDJ ({N},{M1},{M2}) — 金叉/死叉标注', fontsize=15, color='#e6edf3', fontweight='bold', pad=12)
ax2.legend(loc='upper left', fontsize=9, facecolor='#0d1117', edgecolor='#30363d', labelcolor='#e6edf3')
ax2.set_ylabel('KDJ 值', color='#8b949e', fontsize=10)
ax2.tick_params(colors='#8b949e', labelsize=9)
ax2.grid(True, alpha=0.15, color='#30363d')
ax2.set_ylim(-15, 115)
ax2.set_xlim(df.index[0], df.index[-1])

# ============ 下子图：成交量 ============
ax3 = fig.add_subplot(3, 1, 3, facecolor='#161b22')

# 成交量颜色：涨=红，跌=绿
colors_vol = ['#f85149' if df['close'].iloc[i] >= df['open'].iloc[i] else '#3fb950' for i in range(len(df))]
ax3.bar(df.index, df['vol'] / 1e8, color=colors_vol, alpha=0.65, width=0.7)

ax3.set_title('成交量', fontsize=15, color='#e6edf3', fontweight='bold', pad=12)
ax3.set_ylabel('成交量 (亿手)', color='#8b949e', fontsize=10)
ax3.tick_params(colors='#8b949e', labelsize=9)
ax3.grid(True, alpha=0.15, color='#30363d')
ax3.set_xlim(df.index[0], df.index[-1])

# ============ 全局设置 ============
# X轴日期格式化
for ax in [ax1, ax2, ax3]:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha='right')

plt.tight_layout(pad=2.5)

# 保存
output_path = '/mnt/e/Hermes_workspace/上证指数_MA10_MA20_KDJ_成交量.png'
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print(f"\n✅ 图表已保存: {output_path}")
