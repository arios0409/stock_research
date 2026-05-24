"""
双底突破形态回测脚本
回测区间: 2026-01-20 至 2026-03-10
功能:
  - 逐日运行双底扫描
  - 买入符合条件的股票，持有至3月10日
  - 画出收益变化曲线和上证指数曲线（上下两个子图）
"""

import urllib.request
import json
import time
import os
import sys

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
BACKTEST_START = '20260120'
BACKTEST_END = '20260310'
SCAN_LOOKBACK_START = '20250601'  # 扫描时往前取数据

# ============ Tushare API ============

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields: payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') != 0: return None
        return result.get('data', {})
    except Exception: return None

def get_stock_list():
    result = api_call('stock_basic', fields='ts_code,symbol,name,industry,list_status')
    if not result or 'fields' not in result or 'items' not in result: return []
    fields = result['fields']
    return [dict(zip(fields, item)) for item in result['items'] if dict(zip(fields, item)).get('list_status') == 'L']

def get_daily_data(ts_code, start_date, end_date):
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result: return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df

# ============ 技术指标 ============

def calc_macd(closes):
    n = len(closes)
    def ema(data, span):
        k = 2.0 / (span + 1); result = [data[0]]
        for i in range(1, len(data)): result.append(data[i] * k + result[-1] * (1 - k))
        return result
    ema12, ema26 = ema(closes, 12), ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(n)]
    dea = ema(dif, 9)
    return [2 * (dif[i] - dea[i]) for i in range(n)]

def calc_ma(data, period):
    n = len(data)
    result = [None] * n
    for i in range(period - 1, n):
        result[i] = sum(data[i - period + 1: i + 1]) / period
    return result

def calc_rsi(closes, period=14):
    n = len(closes); rsi = [50.0] * n
    if n < period + 1: return rsi
    gains, losses = [], []
    for i in range(1, n):
        diff = closes[i] - closes[i-1]; gains.append(max(0, diff)); losses.append(max(0, -diff))
    avg_gain = sum(gains[:period]) / period; avg_loss = sum(losses[:period]) / period
    for i in range(period, n - 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i-1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i-1]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi

# ============ 双底检测 (与原扫描器一致) ============

def detect_double_bottom(df, window_bottom=22, window_breakout=8, double_bottom_start=None):
    n = len(df)
    if n < window_bottom * 2 + 1: return []
    
    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    dates = [d['trade_date'] for d in df]
    macd = calc_macd(closes)
    rsi = calc_rsi(closes)
    vol_ma20 = calc_ma(volumes, 20)
    
    lows = []
    for i in range(window_bottom, n - window_bottom):
        price = closes[i]
        if all(closes[j] > price for j in range(max(0, i-window_bottom), min(n, i+window_bottom+1)) if j != i):
            lows.append((i, price, volumes[i]))
    
    highs = []
    for i in range(window_breakout, n - window_breakout):
        price = closes[i]
        if all(closes[j] < price for j in range(max(0, i-window_breakout), min(n, i+window_breakout+1)) if j != i):
            highs.append((i, price))
    
    if len(lows) < 2 or len(highs) < 1: return []
    
    results = []
    for i in range(len(lows) - 1):
        l1_idx, l1_price, l1_vol = lows[i]
        l2_idx, l2_price, l2_vol = lows[i + 1]
        
        gap = l2_idx - l1_idx
        if gap < 15 or gap > 150: continue
        
        if abs(l1_price - l2_price) / min(l1_price, l2_price) > 0.05: continue
        
        necks = [h for h in highs if l1_idx < h[0] < l2_idx]
        if not necks: continue
        n_idx, n_price = max(necks, key=lambda x: x[1])
        
        neck_height_pct = (n_price - min(l1_price, l2_price)) / min(l1_price, l2_price)
        if neck_height_pct < 0.10: continue
        
        if double_bottom_start and dates[l1_idx] < double_bottom_start: continue
        
        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:
                if vol_ma20[j] is None or volumes[j] < vol_ma20[j] * 1.5:
                    continue
                fake_break = False
                for k in range(j + 1, min(j + 4, n)):
                    if closes[k] < n_price * 0.98:
                        fake_break = True
                        break
                if fake_break:
                    continue
                break_idx = j
                break
        
        if break_idx is None: continue
        
        results.append({
            'left_idx': l1_idx, 'left_price': l1_price,
            'right_idx': l2_idx, 'right_price': l2_price,
            'neck_idx': n_idx, 'neck_price': n_price,
            'break_idx': break_idx, 'break_date': dates[break_idx],
            'gap': gap,
            'left_vol': l1_vol, 'right_vol': l2_vol,
            'left_macd': macd[l1_idx], 'right_macd': macd[l2_idx],
            'left_rsi': rsi[l1_idx], 'right_rsi': rsi[l2_idx],
            'height_pct': neck_height_pct,
            'break_vol_ratio': volumes[break_idx] / vol_ma20[break_idx] if vol_ma20[break_idx] and vol_ma20[break_idx] > 0 else 1.0,
        })
    
    return results

def score_pattern(df, pattern):
    score = 0
    current_price = float(df[-1]['close'])
    n = len(df)
    
    neck_price = pattern['neck_price']
    if current_price <= neck_price: return -1, []
    
    dist = (current_price - neck_price) / neck_price
    if dist > 0.05: return -1, []
    
    min_bottom = min(pattern['left_price'], pattern['right_price'])
    target = neck_price + (neck_price - min_bottom)
    space_to_target = (target - current_price) / current_price
    if space_to_target < 0.08: return -1, []
    
    break_idx = pattern['break_idx']
    days_since_break = n - 1 - break_idx
    if days_since_break <= 3: score += 25
    elif days_since_break <= 5: score += 20
    elif days_since_break <= 10: score += 15
    else: score += 5
    
    if pattern['left_vol'] > 0:
        vol_ratio = pattern['right_vol'] / pattern['left_vol']
        if vol_ratio < 0.3: score += 20
        elif vol_ratio < 0.5: score += 18
        elif vol_ratio < 0.7: score += 12
    
    gap = pattern['gap']
    if gap >= 30: score += 15
    elif gap >= 20: score += 10
    
    if pattern['right_macd'] > pattern['left_macd'] and pattern['left_price'] >= pattern['right_price']:
        score += 15
    elif pattern['right_macd'] > pattern['left_macd']:
        score += 10
    
    if pattern['right_price'] > pattern['left_price']:
        score += 10
    elif abs(pattern['right_price'] - pattern['left_price']) / pattern['left_price'] < 0.01:
        score += 8
    
    h = pattern['height_pct']
    if 0.10 <= h <= 0.25: score += 10
    elif 0.08 <= h < 0.10: score += 7
    
    if pattern['right_rsi'] > pattern['left_rsi'] and pattern['left_price'] >= pattern['right_price']:
        score += 5
    
    return score, []

# ============ 回测逻辑 ============

def run_backtest():
    print("=" * 60)
    print("双底突破回测: 2026-01-20 至 2026-03-10")
    print("=" * 60)
    
    # 获取股票列表
    print("\n获取股票列表...")
    stocks = get_stock_list()
    stock_map = {s['ts_code']: s['name'] for s in stocks}
    
    hs300 = api_call('index_weight', index_code='399300.SZ', fields='con_code')
    zz500 = api_call('index_weight', index_code='000905.SH', fields='con_code')
    
    scan_codes = set()
    if hs300 and 'items' in hs300:
        scan_codes.update(item[0] for item in hs300['items'])
    if zz500 and 'items' in zz500:
        scan_codes.update(item[0] for item in zz500['items'])
    scan_codes = [c for c in scan_codes if c in stock_map]
    print(f"  扫描 {len(scan_codes)} 只股票 (HS300+ZZ500)")
    
    # 获取所有交易日 (用上证指数日历)
    print("\n获取交易日历...")
    cal_data = api_call('trade_cal', exchange='SSE', start_date='20260115', end_date='20260315')
    if not cal_data or 'items' not in cal_data:
        print("ERROR: 无法获取交易日历")
        return
    cal_fields = cal_data['fields']
    cal_rows = [dict(zip(cal_fields, item)) for item in cal_data['items']]
    cal_rows.sort(key=lambda x: x['cal_date'])
    trade_days = [r['cal_date'] for r in cal_rows if r.get('is_open', 1) == 1]
    
    # 过滤回测区间
    backtest_days = [d for d in trade_days if BACKTEST_START <= d <= BACKTEST_END]
    print(f"  回测交易日: {len(backtest_days)} 天 ({backtest_days[0]} ~ {backtest_days[-1]})")
    
    # 预取上证指数日线
    print("\n预取上证指数数据...")
    sh_index = get_daily_data('000001.SH', start_date='20260115', end_date='20260315')
    sh_price_map = {}
    if sh_index:
        for d in sh_index:
            sh_price_map[d['trade_date']] = float(d['close'])
    
    # 缓存股票日线数据 (一次获取, 多次使用)
    print("\n预取股票日线数据 (可能需要几分钟)...")
    stock_cache = {}
    for idx, code in enumerate(scan_codes):
        if idx % 50 == 0: print(f"  进度: {idx}/{len(scan_codes)}")
        df = get_daily_data(code, start_date=SCAN_LOOKBACK_START, end_date='20260315')
        if df and len(df) >= 60:
            stock_cache[code] = df
        time.sleep(0.12)
    
    print(f"\n  缓存了 {len(stock_cache)} 只股票")
    
    # 回测
    # 策略: 每个扫描日发现的双底股票, 当日收盘价买入, 持有到3月10日
    # 每日调仓: 新的信号加入, 旧信号继续持有
    # 等权分配资金
    
    print(f"\n逐日回测扫描...")
    
    daily_returns = []  # [(date, portfolio_return, sh_return)]
    holdings = {}  # code -> {buy_price, buy_date, name}
    
    sh_start_price = None
    
    for day_idx, scan_date in enumerate(backtest_days):
        if day_idx % 5 == 0:
            print(f"  扫描 {scan_date} (第 {day_idx+1}/{len(backtest_days)} 天)")
        
        # 对每只股票, 检查是否在这一天产生新的双底突破信号
        # 方法: 把数据截到 scan_date, 然后运行检测
        
        # 先检查是否有上证指数数据
        if scan_date in sh_price_map:
            if sh_start_price is None:
                sh_start_price = sh_price_map[scan_date]
            sh_return = (sh_price_map[scan_date] - sh_start_price) / sh_start_price
        else:
            sh_return = daily_returns[-1][2] if daily_returns else 0
        
        # 扫描新信号
        for code, df in stock_cache.items():
            # 截断到 scan_date
            cutoff = None
            for i, d in enumerate(df):
                if d['trade_date'] > scan_date:
                    cutoff = i
                    break
            if cutoff is None:
                df_slice = df
            else:
                df_slice = df[:cutoff]
            
            if len(df_slice) < 60:
                continue
            
            # 检查这一天是否是最新一天
            if df_slice[-1]['trade_date'] != scan_date:
                continue
            
            patterns = detect_double_bottom(df_slice, window_bottom=22, window_breakout=8,
                                            double_bottom_start='20250601')
            
            for p in patterns:
                score, _ = score_pattern(df_slice, p)
                if score >= 40 and p['break_idx'] == len(df_slice) - 1:
                    # 突破日正好是今天, 买入
                    if code not in holdings:
                        buy_price = float(df_slice[-1]['close'])
                        name = stock_map.get(code, code)
                        holdings[code] = {
                            'buy_price': buy_price,
                            'buy_date': scan_date,
                            'name': name,
                            'score': score,
                        }
        
        # 计算当日组合收益 (等权)
        if holdings:
            total_return = 0
            count = 0
            for code, h in holdings.items():
                if code in stock_cache:
                    # 找 scan_date 的收盘价
                    for d in stock_cache[code]:
                        if d['trade_date'] == scan_date:
                            current_price = float(d['close'])
                            ret = (current_price - h['buy_price']) / h['buy_price']
                            total_return += ret
                            count += 1
                            break
            portfolio_return = total_return / count if count > 0 else 0
        else:
            portfolio_return = 0
        
        daily_returns.append((scan_date, portfolio_return, sh_return))
    
    # 输出结果
    print(f"\n{'='*60}")
    print(f"回测完成! 共 {len(daily_returns)} 个交易日")
    
    # 总结
    final_port_ret = daily_returns[-1][1]
    final_sh_ret = daily_returns[-1][2]
    print(f"  最终组合收益: {final_port_ret*100:.2f}%")
    print(f"  同期上证指数: {final_sh_ret*100:.2f}%")
    print(f"  超额收益: {(final_port_ret - final_sh_ret)*100:.2f}%")
    
    # 统计持仓
    if holdings:
        print(f"\n最终持仓 {len(holdings)} 只:")
        for code, h in sorted(holdings.items(), key=lambda x: x[1]['score'], reverse=True):
            if code in stock_cache:
                for d in stock_cache[code]:
                    if d['trade_date'] == BACKTEST_END:
                        end_price = float(d['close'])
                        ret = (end_price - h['buy_price']) / h['buy_price']
                        print(f"  {h['name']} ({code}) 买入@{h['buy_price']:.2f} 现价@{end_price:.2f} 收益{ret*100:.1f}% 评分{h['score']}")
                        break
    
    return daily_returns, sh_price_map

def draw_chart(daily_returns, output_path=None):
    """用纯 SVG 画上下两个子图"""
    if not daily_returns:
        print("没有数据可画")
        return
    
    if output_path is None:
        output_path = os.path.expanduser('~/double_bottom_backtest_chart.svg')
    
    W, H = 1000, 700
    margin = {'top': 40, 'right': 60, 'bottom': 50, 'left': 70}
    
    # 上下两个子图
    chart_w = W - margin['left'] - margin['right']
    top_chart_h = 260
    bottom_chart_h = 260
    gap = 40
    
    top_chart_y = margin['top']
    bottom_chart_y = margin['top'] + top_chart_h + gap
    
    dates = [r[0] for r in daily_returns]
    port_rets = [r[1] * 100 for r in daily_returns]  # 百分比
    sh_rets = [r[2] * 100 for r in daily_returns]
    
    n = len(dates)
    
    # 范围
    all_vals = port_rets + sh_rets
    min_val = min(min(all_vals), -1) - 1
    max_val = max(max(all_vals), 1) + 1
    
    # 也单独算上证的范围给下子图
    sh_min = min(sh_rets) - 0.5
    sh_max = max(sh_rets) + 0.5
    
    def px(i): return margin['left'] + (i / (n - 1)) * chart_w
    def py_top(val): return top_chart_y + top_chart_h - ((val - min_val) / (max_val - min_val)) * top_chart_h
    def py_bot(val): return bottom_chart_y + bottom_chart_h - ((val - sh_min) / (sh_max - sh_min)) * bottom_chart_h
    
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
           '<defs><style>text { font-family: "Droid Sans Fallback", "Noto Sans SC", "WenQuanYi Micro Hei", "Microsoft YaHei", sans-serif; }</style></defs>',
           f'<rect width="{W}" height="{H}" fill="#0d1117"/>',
           f'<text x="{W/2}" y="24" text-anchor="middle" font-size="18" fill="#e6edf3" font-weight="bold">双底突破策略回测 (2026-01-20 ~ 2026-03-10)</text>']
    
    # ===== 上图: 收益变化 =====
    svg.append(f'<text x="{margin["left"]}" y="{top_chart_y - 8}" font-size="13" fill="#58a6ff" font-weight="bold">组合收益率 (%) vs 上证指数收益率 (%)</text>')
    
    # 网格 - 上图
    for i in range(6):
        val = min_val + (max_val - min_val) / 5 * i
        yy = py_top(val)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-8}" y="{yy+4}" text-anchor="end" font-size="10" fill="#8b949e">{val:.1f}%</text>')
    
    # 零线
    if min_val < 0 < max_val:
        yy0 = py_top(0)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy0}" x2="{W-margin["right"]}" y2="{yy0}" stroke="#484f58" stroke-width="1" stroke-dasharray="3,3"/>')
    
    # 日期标签 - 上图底部
    step = max(1, n // 10)
    for i in range(0, n, step):
        ds = dates[i]
        label = f"{ds[4:6]}/{ds[6:8]}"
        svg.append(f'<text x="{px(i)}" y="{top_chart_y + top_chart_h + 14}" text-anchor="middle" font-size="9" fill="#8b949e">{label}</text>')
    
    # 上证指数线 (上图)
    sh_pts = ' '.join(f'{px(i)} {py_top(sh_rets[i])}' for i in range(n))
    svg.append(f'<path d="M {sh_pts}" stroke="#f97316" stroke-width="1.5" fill="none" opacity="0.6"/>')
    
    # 组合收益线 (上图)
    port_pts = ' '.join(f'{px(i)} {py_top(port_rets[i])}' for i in range(n))
    svg.append(f'<path d="M {port_pts}" stroke="#3fb950" stroke-width="2" fill="none"/>')
    
    # 面积填充
    area_pts = f'{px(0)} {py_top(0)} ' + ' '.join(f'{px(i)} {py_top(port_rets[i])}' for i in range(n)) + f' {px(n-1)} {py_top(0)}'
    svg.append(f'<path d="M {area_pts}" fill="#3fb950" opacity="0.08"/>')
    
    # 图例 - 上图
    legend_x = W - margin['right'] - 160
    legend_y = top_chart_y + 10
    svg.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x+20}" y2="{legend_y}" stroke="#3fb950" stroke-width="2"/>')
    svg.append(f'<text x="{legend_x+25}" y="{legend_y+4}" font-size="10" fill="#c9d1d9">组合收益</text>')
    svg.append(f'<line x1="{legend_x}" y1="{legend_y+16}" x2="{legend_x+20}" y2="{legend_y+16}" stroke="#f97316" stroke-width="1.5" opacity="0.6"/>')
    svg.append(f'<text x="{legend_x+25}" y="{legend_y+20}" font-size="10" fill="#c9d1d9">上证指数</text>')
    
    # ===== 下图: 上证指数 =====
    svg.append(f'<text x="{margin["left"]}" y="{bottom_chart_y - 8}" font-size="13" fill="#f97316" font-weight="bold">上证指数收益率 (%)</text>')
    
    # 网格 - 下图
    for i in range(6):
        val = sh_min + (sh_max - sh_min) / 5 * i
        yy = py_bot(val)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy}" x2="{W-margin["right"]}" y2="{yy}" stroke="#21262d" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-8}" y="{yy+4}" text-anchor="end" font-size="10" fill="#8b949e">{val:.1f}%</text>')
    
    if sh_min < 0 < sh_max:
        yy0 = py_bot(0)
        svg.append(f'<line x1="{margin["left"]}" y1="{yy0}" x2="{W-margin["right"]}" y2="{yy0}" stroke="#484f58" stroke-width="1" stroke-dasharray="3,3"/>')
    
    # 日期标签 - 下图底部
    for i in range(0, n, step):
        ds = dates[i]
        label = f"{ds[4:6]}/{ds[6:8]}"
        svg.append(f'<text x="{px(i)}" y="{bottom_chart_y + bottom_chart_h + 14}" text-anchor="middle" font-size="9" fill="#8b949e">{label}</text>')
    
    # 上证指数面积
    sh_area = f'{px(0)} {py_bot(0)} ' + ' '.join(f'{px(i)} {py_bot(sh_rets[i])}' for i in range(n)) + f' {px(n-1)} {py_bot(0)}'
    svg.append(f'<path d="M {sh_area}" fill="#f97316" opacity="0.12"/>')
    
    sh_line = ' '.join(f'{px(i)} {py_bot(sh_rets[i])}' for i in range(n))
    svg.append(f'<path d="M {sh_line}" stroke="#f97316" stroke-width="2" fill="none"/>')
    
    # 最终收益标签
    final_port = port_rets[-1]
    final_sh = sh_rets[-1]
    
    svg.append(f'<text x="{W-margin["right"]}" y="{py_top(final_port)+4}" text-anchor="end" font-size="11" fill="#3fb950" font-weight="bold">组合 {final_port:.2f}%</text>')
    svg.append(f'<text x="{W-margin["right"]}" y="{py_bot(final_sh)+4}" text-anchor="end" font-size="11" fill="#f97316" font-weight="bold">上证 {final_sh:.2f}%</text>')
    
    svg.append('</svg>')
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(svg))
    
    print(f"\n图表已保存: {output_path}")
    return output_path

if __name__ == '__main__':
    results = run_backtest()
    if results:
        daily_returns, sh_map = results
        draw_chart(daily_returns)
