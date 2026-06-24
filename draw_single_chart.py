"""
为单只股票绘制K线图（PNG格式）
用法: python draw_single_chart.py <ts_code> [output_path]
"""
import urllib.request, json, os, sys, time, math

TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'

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

def get_daily(ts_code, start_date, end_date):
    result = api_call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
    if not result or 'fields' not in result or 'items' not in result: return None
    fields = result['fields']
    df = [dict(zip(fields, item)) for item in result['items']]
    df.sort(key=lambda x: x['trade_date'])
    return df

def get_stock_name(ts_code):
    result = api_call('stock_basic', ts_code=ts_code, fields='ts_code,name')
    if result and 'items' in result and result['items']:
        return result['items'][0][1]
    return ts_code

def draw_candlestick_png(df, ts_code, stock_name, pattern_info, save_path):
    """绘制K线图PNG"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    from matplotlib.patches import Rectangle
    import matplotlib_fontja  # enables IPAexGothic CJK font
    
    plt.rcParams['font.family'] = 'IPAexGothic'
    plt.rcParams['axes.unicode_minus'] = False
    
    n = len(df)
    
    # Parse data
    dates = [d['trade_date'] for d in df]
    opens = [float(d['open']) for d in df]
    highs = [float(d['high']) for d in df]
    lows = [float(d['low']) for d in df]
    closes = [float(d['close']) for d in df]
    volumes = [float(d['vol']) for d in df]
    
    # Create figure with subplots
    fig = plt.figure(figsize=(14, 8), facecolor='#1a1a2e')
    
    # Price chart (top)
    ax1 = plt.subplot2grid((5, 1), (0, 0), rowspan=4, facecolor='#1a1a2e')
    # Volume chart (bottom)
    ax2 = plt.subplot2grid((5, 1), (4, 0), rowspan=1, facecolor='#1a1a2e', sharex=ax1)
    
    # --- Draw candlesticks ---
    width = 0.6
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = '#ef5350' if c >= o else '#26a69a'  # red up, green down (China style)
        edge = '#ff8a80' if c >= o else '#80cbc4'
        
        # Wick (high-low line)
        ax1.plot([i, i], [l, h], color=edge, linewidth=0.8, solid_capstyle='round')
        # Body
        body_h = abs(c - o)
        body_y = min(o, c)
        ax1.add_patch(Rectangle((i - width/2, body_y), width, body_h,
                                 facecolor=color, edgecolor=edge, linewidth=0.5, zorder=3))
    
    # --- Triangle pattern highlight ---
    tri_start = pattern_info.get('tri_start')
    tri_end = pattern_info.get('tri_end')
    if tri_start and tri_end:
        start_i = None
        end_i = None
        for i, d in enumerate(dates):
            if d == tri_start: start_i = i
            if d == tri_end: end_i = i
        if start_i is not None and end_i is not None:
            ax1.axvspan(start_i - 0.5, end_i + 0.5, alpha=0.12, color='#ffab40')
            ax1.annotate('三角收敛区间', xy=((start_i + end_i) / 2, ax1.get_ylim()[1]),
                        fontsize=8, color='#ffab40', ha='center', va='bottom',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='#1a1a2e', edgecolor='#ffab40', alpha=0.8))
    
    # --- Breakout marker ---
    breakout_date = pattern_info.get('breakout_date')
    breakout_price = pattern_info.get('breakout_price')
    if breakout_date and breakout_price:
        for i, d in enumerate(dates):
            if d == breakout_date:
                ax1.annotate(f'突破\n{breakout_price}', xy=(i, breakout_price),
                           fontsize=8, color='#ffab40', ha='center', va='bottom',
                           arrowprops=dict(arrowstyle='->', color='#ffab40', lw=1.2),
                           xytext=(0, 15), textcoords='offset points')
                break
    
    # --- Target price ---
    target_price = pattern_info.get('target_price')
    if target_price and target_price < max(highs) * 1.15:
        ax1.axhline(y=target_price, color='#ce93d8', linestyle='--', linewidth=1, alpha=0.7)
        ax1.text(n - 1, target_price, f' 目标 {target_price}', fontsize=8, color='#ce93d8',
                va='center', ha='left')
    
    # --- Current price ---
    ax1.axhline(y=closes[-1], color='#64b5f6', linestyle=':', linewidth=1, alpha=0.7)
    ax1.text(n - 1, closes[-1], f' 现价 {closes[-1]:.2f}', fontsize=8, color='#64b5f6',
            va='center', ha='left')
    
    # --- Axis styling ---
    ax1.set_xlim(-1, n)
    price_margin = (max(highs) - min(lows)) * 0.05
    ax1.set_ylim(min(lows) - price_margin, max(highs) + price_margin)
    ax1.tick_params(colors='#b0b0b0', labelsize=8)
    ax1.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.2f'))
    ax1.grid(True, alpha=0.15, color='#ffffff')
    
    # --- Volume bars ---
    for i in range(n):
        color = '#ef535066' if closes[i] >= opens[i] else '#26a69a66'
        ax2.bar(i, volumes[i] / 10000, width=width, color=color, edgecolor=color, linewidth=0.3)
    
    ax2.set_ylabel('量(万手)', fontsize=8, color='#888888')
    ax2.tick_params(colors='#b0b0b0', labelsize=7)
    ax2.grid(True, alpha=0.15, color='#ffffff')
    
    # --- Date labels ---
    step = max(1, n // 6)
    tick_positions = list(range(0, n, step))
    tick_labels = [f"{dates[i][4:6]}/{dates[i][6:]}" for i in tick_positions]
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels, fontsize=7, color='#b0b0b0')
    
    # --- Title ---
    score = pattern_info.get('score', '')
    title = f"{stock_name} ({ts_code})  三角收敛上涨中继"
    if score:
        title += f"  评分:{score}"
    fig.suptitle(title, fontsize=14, color='#e0e0e0', y=0.98, fontweight='bold')
    
    # --- Info text ---
    info_lines = []
    if pattern_info.get('win_rate'):
        info_lines.append(f"胜率: {pattern_info['win_rate']}%")
    if pattern_info.get('symmetry'):
        info_lines.append(f"对称度: {pattern_info['symmetry']}%")
    if pattern_info.get('tri_days'):
        info_lines.append(f"收敛天数: {pattern_info['tri_days']}")
    if pattern_info.get('breakout_pct'):
        info_lines.append(f"突破后涨幅: {pattern_info['breakout_pct']}%")
    if pattern_info.get('target_pct'):
        info_lines.append(f"目标涨幅: {pattern_info['target_pct']}%")
    
    if info_lines:
        info_text = ' | '.join(info_lines)
        fig.text(0.5, 0.01, info_text, fontsize=9, color='#a0a0a0', ha='center',
                bbox=dict(boxstyle='round,pad=0.4', facecolor='#16213e', edgecolor='#333366', alpha=0.8))
    
    plt.tight_layout(rect=[0, 0.04, 1, 0.95])
    fig.savefig(save_path, dpi=150, facecolor='#1a1a2e', edgecolor='none', bbox_inches='tight')
    plt.close(fig)
    print(f"已保存: {save_path}")


if __name__ == '__main__':
    ts_code = sys.argv[1] if len(sys.argv) > 1 else '300852.SZ'
    
    # Pattern info from scan results (三角收敛上涨中继)
    pattern_info = {
        'tri_start': '20260430',
        'tri_end': '20260608',
        'tri_days': 24,
        'breakout_date': '20260615',
        'breakout_price': 58.97,
        'target_price': 72.62,
        'score': '83.8/100',
        'win_rate': 75,
        'symmetry': 71,
        'breakout_pct': 1.3,
        'target_pct': 23.1,
    }
    
    # Fetch data - go back to Feb 2026 for full context
    print(f"获取 {ts_code} 日线数据...")
    df = get_daily(ts_code, start_date='20260201', end_date='20260622')
    if not df:
        print("获取数据失败！")
        sys.exit(1)
    
    print(f"获取到 {len(df)} 条日线数据 ({df[0]['trade_date']} ~ {df[-1]['trade_date']})")
    
    # Get stock name
    stock_name = get_stock_name(ts_code)
    print(f"股票名称: {stock_name}")
    
    # Output path
    default_out = os.path.expanduser(f'~/storage/shared/Hermes_output/300852_四会富仕_K线图.png')
    save_path = sys.argv[2] if len(sys.argv) > 2 else default_out
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    draw_candlestick_png(df, ts_code, stock_name, pattern_info, save_path)
