"""
双底形态回测脚本 - 胜率分析
功能：扫描指定时间窗口的双底突破，计算1个月内达成目标的概率，绘制胜率-时间曲线。
"""

import urllib.request, json, os, time, math

TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'

# 扫描窗口
SCAN_START = '20260120'
SCAN_END = '20260220'
# 回测需要的历史数据范围
DATA_START = '20240601'
DATA_END = '20260400'  # 覆盖SCAN_END + 30天观测期
OBS_DAYS = 30  # 观测期(交易日)

def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields: payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read().decode('utf-8'))
    if result.get('code') != 0: return None
    return result.get('data', {})

def get_daily(ts_code, start_date, end_date):
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result: return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df

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
    n = len(data); result = [None] * n
    for i in range(period - 1, n): result[i] = sum(data[i - period + 1: i + 1]) / period
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

def detect_db_at_date(df, scan_date_idx):
    """检查在 scan_date_idx 这一天是否有新的双底突破形成"""
    # 简化逻辑：我们只关心突破发生在 scan_date_idx 的模式
    # 扫描范围限制在 scan_date_idx 之前
    n = scan_date_idx + 1
    sub_df = df[:n]
    closes = [float(d['close']) for d in sub_df]
    volumes = [float(d['vol']) for d in sub_df]
    dates = [d['trade_date'] for d in sub_df]
    
    if n < 60: return None
    
    window_bottom = 22
    window_breakout = 8
    
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
            
    if len(lows) < 2: return None
    
    for i in range(len(lows) - 1):
        l1_idx, l1_price, l1_vol = lows[i]
        l2_idx, l2_price, l2_vol = lows[i+1]
        
        if l2_idx - l1_idx < 15 or l2_idx - l1_idx > 150: continue
        if abs(l1_price - l2_price) / min(l1_price, l2_price) > 0.05: continue
        
        necks = [h for h in highs if l1_idx < h[0] < l2_idx]
        if not necks: continue
        n_idx, n_price = max(necks, key=lambda x: x[1])
        
        neck_height_pct = (n_price - min(l1_price, l2_price)) / min(l1_price, l2_price)
        if neck_height_pct < 0.10: continue
        
        pre_left_high = max(closes[max(0, l1_idx-100):l1_idx]) if l1_idx > 0 else 0
        if pre_left_high < n_price * 0.95: continue
        
        left_drop = pre_left_high - l1_price
        db_height = n_price - min(l1_price, l2_price)
        if left_drop < db_height * 2: continue
        
        # 检查突破
        break_idx = None
        for j in range(l2_idx, n):
            if closes[j] > n_price * 1.01:
                vol_ma20 = calc_ma(volumes, 20)
                if vol_ma20[j] is None or volumes[j] < vol_ma20[j] * 1.5: continue
                fake = False
                for k in range(j + 1, min(j + 4, n)):
                    if closes[k] < n_price * 0.98: fake = True; break
                if fake: continue
                break_idx = j
                break
        
        # 只有今天刚好突破，或者前几天突破今天确认(为了容错)
        if break_idx is None: continue
        days_since_break = (n - 1) - break_idx
        
        # 过滤已经涨太多的
        min_bottom = min(l1_price, l2_price)
        target = n_price + (n_price - min_bottom)
        cp = float(df[-1]['close'])
        if cp > target * 1.2: continue 
        
        return {
            'break_idx': break_idx, 'neck_price': n_price, 'target': target,
            'left_price': l1_price, 'right_price': l2_price
        }
    return None

def backtest_stock(code, name, df, scan_dates):
    """对单只股票回测"""
    results = []
    for s_date in scan_dates:
        if s_date not in [d['trade_date'] for d in df]: continue
        s_idx = df.index(next(d for d in df if d['trade_date'] == s_date))
        
        # 获取足够的后续数据
        if s_idx + OBS_DAYS >= len(df): continue
        
        pattern = detect_db_at_date(df, s_idx)
        if pattern:
            break_idx = pattern['break_idx']
            target = pattern['target']
            
            # 观测期内的最高价
            future_high = max(float(df[k]['high']) for k in range(break_idx, min(len(df), break_idx + OBS_DAYS)))
            hit = future_high >= target
            results.append({'date': s_date, 'hit': hit, 'days_to_hit': None})
            if hit:
                # 精确天数
                for d in range(break_idx, min(len(df), break_idx + OBS_DAYS)):
                    if float(df[d]['high']) >= target:
                        results[-1]['days_to_hit'] = d - break_idx
                        break
    return results

def draw_chart(winrate_curve, total_signals, save_path):
    W, H = 900, 600
    margin = {'top': 60, 'right': 50, 'bottom': 80, 'left': 70}
    cw, ch = W - margin['left'] - margin['right'], H - margin['top'] - margin['bottom']
    
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" fill="#1a1a2e"/>',
           f'<text x="{W/2}" y="30" text-anchor="middle" font-size="18" fill="#e0e0e0" font-weight="bold">双底突破回测: 胜率-时间曲线</text>',
           f'<text x="{W/2}" y="55" text-anchor="middle" font-size="14" fill="#888">扫描窗口: {SCAN_START} ~ {SCAN_END} | 观测期: {OBS_DAYS}天 | 总信号: {total_signals}</text>']
    
    # 网格
    for i in range(6):
        y = margin['top'] + (i / 5) * ch
        val = 1.0 - (i / 5)
        svg.append(f'<line x1="{margin["left"]}" y1="{y}" x2="{W-margin["right"]}" y2="{y}" stroke="#333" stroke-width="0.5"/>')
        svg.append(f'<text x="{margin["left"]-8}" y="{y+4}" text-anchor="end" font-size="12" fill="#888">{val:.0%}</text>')
    
    max_days = len(winrate_curve)
    for i in range(0, max_days + 1, max(1, max_days // 10)):
        x = margin['left'] + (i / max_days) * cw
        svg.append(f'<text x="{x}" y="{margin["top"]+ch+20}" text-anchor="middle" font-size="11" fill="#888">Day {i}</text>')
    
    # 曲线
    if winrate_curve:
        pts = []
        for d, wr in enumerate(winrate_curve):
            x = margin['left'] + (d / max_days) * cw
            y = margin['top'] + (1 - wr) * ch
            pts.append(f'{x} {y}')
        
        # 填充区域
        fill_pts = ' '.join(pts)
        svg.append(f'<path d="M {margin["left"]} {margin["top"]+ch} L {" ".join(f"{margin["left"] + (d/max_days)*cw} {margin["top"] + (1-wr)*ch}" for d,wr in enumerate(winrate_curve))} L {margin["left"]+cw} {margin["top"]+ch} Z" fill="#4CAF50" opacity="0.1"/>')
        
        # 连线
        path_d = 'M ' + ' L '.join(pts)
        svg.append(f'<path d="{path_d}" stroke="#4CAF50" stroke-width="3" fill="none"/>')
        
        # 关键点标注
        for d_idx in [0, 4, 9, 19, 29]:
            if d_idx < len(winrate_curve):
                x = margin['left'] + (d_idx / max_days) * cw
                y = margin['top'] + (1 - winrate_curve[d_idx]) * ch
                svg.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#fff"/>')
                svg.append(f'<text x="{x}" y="{y-10}" text-anchor="middle" font-size="11" fill="#fff">{winrate_curve[d_idx]:.1%}</text>')
    
    svg.append('</svg>')
    with open(save_path.replace('.png', '.svg'), 'w') as f: f.write('\n'.join(svg))
    os.system(f'magick "{save_path.replace(".png", ".svg")}" "{save_path}" 2>&1')

def main():
    print("获取股票列表...")
    stocks = api_call('stock_basic', fields='ts_code,symbol,name,list_status')
    if not stocks or 'fields' not in stocks: return
    stock_map = {}
    for item in stocks['items']:
        s = dict(zip(stocks['fields'], item))
        if s.get('list_status') == 'L':
            stock_map[s['ts_code']] = s['name']
    
    idx_res = api_call('index_weight', index_code='399300.SZ', fields='con_code')
    hs300 = set(i[0] for i in idx_res['items']) if idx_res else set()
    idx_res2 = api_call('index_weight', index_code='000905.SH', fields='con_code')
    zz500 = set(i[0] for i in idx_res2['items']) if idx_res2 else set()
    scan_codes = sorted((hs300 | zz500) & set(stock_map.keys()))
    
    print(f"生成扫描日期列表 {SCAN_START} ~ {SCAN_END}...")
    all_data = {}
    scan_dates = []
    
    # 预取所有股票数据
    print("预取全市场数据...")
    for i, code in enumerate(scan_codes):
        if i % 50 == 0: print(f"  {i}/{len(scan_codes)}")
        df = get_daily(code, DATA_START, DATA_END)
        if df and len(df) > 100:
            all_data[code] = df
            # 收集扫描窗口内的日期
            for d in df:
                if SCAN_START <= d['trade_date'] <= SCAN_END:
                    if d['trade_date'] not in scan_dates: scan_dates.append(d['trade_date'])
        time.sleep(0.1)
    
    scan_dates.sort()
    print(f"共 {len(scan_dates)} 个扫描日, {len(all_data)} 只股票有数据")
    
    # 回测
    print("开始回测...")
    total_signals = 0
    hits_by_day = {}
    
    # 简单统计: 每个信号观测是否达成
    all_outcomes = [] # list of (hit, days_to_hit)
    
    for i, code in enumerate(all_data):
        df = all_data[code]
        res = backtest_stock(code, stock_map[code], df, scan_dates)
        for r in res:
            total_signals += 1
            if r['hit']:
                d = r['days_to_hit']
                all_outcomes.append((True, d))
            else:
                all_outcomes.append((False, None))
    
    print(f"总信号: {total_signals}")
    
    # 计算胜率曲线
    curve = []
    for day in range(OBS_DAYS + 1):
        hits = sum(1 for hit, d in all_outcomes if hit and d is not None and d <= day)
        curve.append(hits / total_signals if total_signals else 0)
    
    print("绘图...")
    draw_chart(curve, total_signals, '/data/data/com.termux/files/home/storage/shared/termux/db_winrate_backtest.png')
    print("完成! 图片保存于 ~/storage/shared/termux/db_winrate_backtest.png")

if __name__ == '__main__':
    main()
