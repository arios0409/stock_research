
import tushare as ts
import pandas as pd
import numpy as np

TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
pro = ts.pro_api(TOKEN)

print("正在获取上证指数数据...")
df = pro.index_daily(ts_code='000001.SH', start_date='20251101', end_date='20260520')
df = df.sort_values('trade_date').reset_index(drop=True)
df['date'] = pd.to_datetime(df['trade_date'])

N, M1, M2 = 14, 5, 3

# 计算RSV
low_n = df['low'].rolling(N).min()
high_n = df['high'].rolling(N).max()
rsv = (df['close'] - low_n) / (high_n - low_n) * 100
rsv = rsv.clip(0, 100)

def sma_tdx(data, n, m):
    """通达信SMA实现: 从第一个有效值开始"""
    result = np.full_like(data, np.nan, dtype=float)
    first_valid = None
    for i in range(len(data)):
        if pd.notna(data[i]):
            first_valid = i
            result[i] = data[i]
            break
    if first_valid is None:
        return result
    for i in range(first_valid + 1, len(data)):
        if pd.isna(data[i]):
            continue
        result[i] = (data[i] * m + result[i-1] * (n - m)) / n
    return result

# ========= 方法1: 通式SMA（从第一个有效RSV开始）=========
k1 = sma_tdx(rsv.values, M1, 1)
d1 = sma_tdx(k1, M2, 1)
j1 = 3 * k1 - 2 * d1

# ========= 方法2: K[0]=50, D[0]=50 初始化 =========
k2 = np.full(len(rsv), np.nan)
d2 = np.full(len(rsv), np.nan)

# 找到第一个有效RSV
first_idx = None
for i in range(len(rsv)):
    if pd.notna(rsv.iloc[i]):
        first_idx = i
        break

if first_idx is not None:
    k2[first_idx] = rsv.iloc[first_idx]  # 第一个K = RSV
    d2[first_idx] = k2[first_idx]        # 第一个D = K
    # 另一种常见：K=50, D=50
    # k2[first_idx] = 50
    # d2[first_idx] = 50
    
    for i in range(first_idx + 1, len(rsv)):
        k2[i] = (rsv.iloc[i] * 1 + k2[i-1] * (M1 - 1)) / M1
        d2[i] = (k2[i] * 1 + d2[i-1] * (M2 - 1)) / M2

j2 = 3 * k2 - 2 * d2

# ========= 方法3: 第一个K/D都初始化为50 =========
k3 = np.full(len(rsv), np.nan)
d3 = np.full(len(rsv), np.nan)

if first_idx is not None:
    k3[first_idx] = 50
    d3[first_idx] = 50
    for i in range(first_idx + 1, len(rsv)):
        k3[i] = (rsv.iloc[i] * 1 + k3[i-1] * (M1 - 1)) / M1
        d3[i] = (k3[i] * 1 + d3[i-1] * (M2 - 1)) / M2

j3 = 3 * k3 - 2 * d3

# ========= 输出对比: 初始期 =========
# 从第一个有全部数据的日期开始看
start_check = first_idx if first_idx is not None else 13

print(f"\n=== KDJ(14,5,3) 三种实现对比 ===")
print(f"第一个有效RSV在索引 {first_idx}, 日期 {df['date'].iloc[first_idx].strftime('%Y-%m-%d')}")
print(f"\n{'日期':<14} {'RSV':>8} {'K1(通式)':>10} {'D1(通式)':>10} {'J1':>10} {'K2(RSV起)':>10} {'D2(RSV起)':>10} {'K3(50起)':>10} {'D3(50起)':>10}")
print("-" * 100)

# 输出前20个有效值
count = 0
for i in range(len(df)):
    if pd.notna(k1[i]) and count < 30:
        print(f"{df['date'].iloc[i].strftime('%Y-%m-%d'):<14} {rsv.iloc[i]:>8.2f} {k1[i]:>10.2f} {d1[i]:>10.2f} {j1[i]:>10.2f} {k2[i]:>10.2f} {d2[i]:>10.2f} {k3[i]:>10.2f} {d3[i]:>10.2f}")
        count += 1

# 输出最近10个值
print(f"\n--- 最近10个交易日 ---")
print(f"{'日期':<14} {'RSV':>8} {'K1(通式)':>10} {'D1(通式)':>10} {'J1':>10} {'K2(RSV起)':>10} {'D2(RSV起)':>10} {'K3(50起)':>10} {'D3(50起)':>10}")
print("-" * 100)

for i in range(len(df)-10, len(df)):
    if pd.notna(k1[i]):
        print(f"{df['date'].iloc[i].strftime('%Y-%m-%d'):<14} {rsv.iloc[i]:>8.2f} {k1[i]:>10.2f} {d1[i]:>10.2f} {j1[i]:>10.2f} {k2[i]:>10.2f} {d2[i]:>10.2f} {k3[i]:>10.2f} {d3[i]:>10.2f}")

# 比较金叉死叉差异
print(f"\n=== 三种实现的金叉/死叉对比 ===")
for impl_name, k_arr, d_arr in [
    ("方法1(通式SMA)", k1, d1),
    ("方法2(RSV起)", k2, d2),
    ("方法3(50起)", k3, d3),
]:
    golden = []
    death = []
    for i in range(1, len(k_arr)):
        if pd.isna(k_arr[i]) or pd.isna(k_arr[i-1]):
            continue
        if pd.isna(d_arr[i]) or pd.isna(d_arr[i-1]):
            continue
        if k_arr[i-1] <= d_arr[i-1] and k_arr[i] > d_arr[i]:
            golden.append(df['date'].iloc[i].strftime('%Y-%m-%d'))
        if k_arr[i-1] >= d_arr[i-1] and k_arr[i] < d_arr[i]:
            death.append(df['date'].iloc[i].strftime('%Y-%m-%d'))
    print(f"\n{impl_name}:")
    print(f"  金叉: {', '.join(golden)}")
    print(f"  死叉: {', '.join(death)}")
