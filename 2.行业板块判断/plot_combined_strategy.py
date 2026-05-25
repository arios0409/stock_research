#!/usr/bin/env python3
"""
三合一策略图：大盘趋势 + 资金曲线 + 持仓板块
规则：↑上升选Top3，⚠风险/↓下降空仓，↓下降P_down>70%提前平仓
"""
import sys, os, time
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
from matplotlib.patches import FancyBboxPatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hot_sectors_scanner as hs

# ===== 配置 =====
START_DATE = '20250101'
END_DATE = '20260430'
FORWARD_DAYS = 3
TOP_N = 3
TRADING_DAYS_PER_YEAR = 245

# ===== 字体 =====
for fp in ['/mnt/c/Windows/Fonts/simhei.ttf','/mnt/c/Windows/Fonts/msyh.ttc']:
    if os.path.exists(fp): fm.fontManager.addfont(fp)
plt.rcParams['font.sans-serif'] = ['SimHei'] + plt.rcParams.get('font.sans-serif',[])
plt.rcParams['axes.unicode_minus'] = False

# ===== 配色 =====
c_bg = '#0d1117'; c_ax = '#161b22'
c_up = '#00ff00'; c_risk = '#ffff00'; c_down = '#ff0000'
c_price = '#ffffff'; c_grid = '#333333'; c_label = '#dddddd'

# ============================================================
# 数据获取
# ============================================================

def get_trade_days(start, end, limit=400):
    all_days = []
    dt = datetime.strptime(end, '%Y%m%d')
    checked = 0
    while checked < limit:
        td = (dt - timedelta(days=checked)).strftime('%Y%m%d')
        if td < str(int(start)-1): break
        data = hs.api_call('daily', trade_date=td, limit=1, fields='ts_code,trade_date')
        if data and data.get('items'): all_days.append(td)
        checked += 1
        time.sleep(0.15)
    return sorted(set(all_days))


def prefetch_all(trade_days):
    print(f'预取 {len(trade_days)} 天数据...', file=sys.stderr)
    idx_data = hs.api_call('index_daily', ts_code='000001.SH',
                          start_date=trade_days[0], end_date=trade_days[-1],
                          fields='trade_date,open,high,low,close,vol')
    idx_rows = hs.parse_data(idx_data)
    idx_map = {}  # {date: {close, high, low, vol}}
    for r in (idx_rows or []):
        idx_map[r['trade_date']] = {
            'close': float(r['close']), 'high': float(r['high']),
            'low': float(r['low']), 'vol': float(r.get('vol', 0))
        }
    
    daily = {}
    money = {}
    for i, td in enumerate(trade_days):
        d = hs.api_call('daily', trade_date=td, limit=5000, fields='ts_code,pct_chg')
        daily[td] = {r['ts_code']: float(r['pct_chg']) for r in (hs.parse_data(d) or [])}
        m = hs.api_call('moneyflow', trade_date=td,
                       fields='ts_code,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount')
        mf = {}
        for r in (hs.parse_data(m) or []):
            c = r['ts_code']
            ba = float(r.get('buy_lg_amount',0)) + float(r.get('buy_elg_amount',0))
            sa = float(r.get('sell_lg_amount',0)) + float(r.get('sell_elg_amount',0))
            t = ba + sa
            net = float(r.get('net_mf_amount', 0) or 0)
            mf[c] = {'net_rate': net/t*100 if t>0 else 0}
        money[td] = mf
        if (i+1)%30 == 0: print(f'  [{i+1}/{len(trade_days)}]', file=sys.stderr)
        time.sleep(0.15)
    return idx_map, daily, money


# ============================================================
# 大盘趋势 + 概率系统
# ============================================================

def compute_market_system(idx_map, trade_days):
    """计算大盘的KDJ概率系统，返回状态和概率"""
    dates = sorted(d for d in trade_days if d in idx_map)
    closes = np.array([idx_map[d]['close'] for d in dates])
    highs = np.array([idx_map[d]['high'] for d in dates])
    lows = np.array([idx_map[d]['low'] for d in dates])
    
    N, M1, M2 = 14, 5, 3
    k = np.full(len(closes), np.nan)
    d_vals = np.full(len(closes), np.nan)
    p_up = np.full(len(closes), 50.0)
    p_down = np.full(len(closes), 50.0)
    p_risk = np.full(len(closes), 50.0)
    states = np.full(len(closes), 0)
    
    up_days = down_days = risk_days = 0
    for i in range(N-1, len(closes)):
        hh = np.max(highs[i-N+1:i+1])
        ll = np.min(lows[i-N+1:i+1])
        rsv = 50.0 if hh == ll else (closes[i]-ll)/(hh-ll)*100
        if np.isnan(k[i-1]): k[i]=rsv; d_vals[i]=rsv
        else:
            k[i]=(rsv*1+k[i-1]*(M1-1))/M1
            d_vals[i]=(k[i]*1+d_vals[i-1]*(M2-1))/M2
        
        is_g = k[i-1] <= d_vals[i-1] and k[i] > d_vals[i]
        is_d = k[i-1] >= d_vals[i-1] and k[i] < d_vals[i]
        hd = is_d and k[i] >= 85; dz = k[i] < 35 and d_vals[i] < 40
        
        up_days = up_days+1 if k[i] > d_vals[i] else 0
        down_days = down_days+1 if dz else 0
        risk_days = risk_days+1 if (k[i] < d_vals[i] and k[i] >= 85) else 0
        
        if k[i] > d_vals[i]:
            p_up[i] = 80 if (is_g and k[i]<30 and d_vals[i]<30) else (60 if is_g else min(60+up_days*5, 92))
        else:
            p_up[i] = 30 if is_d else max(p_up[i-1]-(down_days*8 if down_days>0 else 3), 10)
        
        if dz: p_down[i] = min(55+down_days*5, 88)
        elif k[i] < d_vals[i] and k[i] < 50: p_down[i] = min(45+(50-k[i])*1.5, 80)
        elif hd: p_down[i] = 50
        elif risk_days >= 1: p_down[i] = min(50+risk_days*3, 70)
        elif is_g: p_down[i] = max(p_down[i-1]-15, 10)
        else: p_down[i] = max(p_down[i-1]-2, 20)
        
        if hd: p_risk[i] = 65
        elif risk_days >= 1 and k[i] < d_vals[i]: p_risk[i] = min(65+risk_days*5, 88)
        elif k[i] < d_vals[i] and k[i] >= 75: p_risk[i] = min(45+(k[i]-75)*2, 65)
        elif dz: p_risk[i] = max(p_risk[i-1]-10, 10)
        elif is_g: p_risk[i] = max(p_risk[i-1]-20, 5)
        else: p_risk[i] = max(p_risk[i-1]-2, 15)
        
        s = 1 if (p_up[i] > p_risk[i] and p_up[i] > p_down[i]) else \
            2 if (p_risk[i] > p_up[i] and p_risk[i] > p_down[i]) else \
            3 if (p_down[i] > p_up[i] and p_down[i] > p_risk[i]) else 0
        states[i] = s
    
    # 组装返回
    result = {}
    for i, d in enumerate(dates):
        result[d] = {
            'close': closes[i], 'high': highs[i], 'low': lows[i],
            'k': k[i] if not np.isnan(k[i]) else 50,
            'd': d_vals[i] if not np.isnan(d_vals[i]) else 50,
            'p_up': p_up[i], 'p_down': p_down[i], 'p_risk': p_risk[i],
            'state': states[i],
        }
    return result, dates


# ============================================================
# 策略模拟
# ============================================================

def simulate_strategy(market, eval_days, ext_days, daily, ind_stocks, s2i):
    """模拟策略，返回每日持仓和NAV"""
    print('模拟策略...', file=sys.stderr)
    
    # 预计算所有评分
    scored_cache = {}
    print('  预计算评分...', file=sys.stderr)
    for i, ed in enumerate(eval_days):
        scored = score_day(ed, ext_days, daily, ind_stocks, s2i)
        scored_cache[ed] = scored
        if (i+1)%50 == 0: print(f'  [{i+1}/{len(eval_days)}]', file=sys.stderr)
    
    # 逐日模拟
    positions = []  # [(entry_date, sectors, exit_date)]
    active_position = None  # {entry_date, sectors, exit_date, day_count}
    
    daily_nav = [1.0]  # 起始净值
    daily_holdings = {}  # {date: [(sector, weight)]}
    daily_pnl = {}  # {date: return_pct}
    position_log = []  # [(entry, exit, sectors)]
    
    # 按交易日推进
    for i, ed in enumerate(eval_days):
        m = market.get(ed)
        if not m: continue
        
        state = m['state']
        p_down_val = m['p_down']
        
        # 检查是否需要提前平仓
        if active_position and state == 3 and p_down_val > 70:
            # 紧急卖出
            entry, sectors, exit_date, day_cnt = active_position
            # 计算已持有天数的收益
            held_days = eval_days[max(0, i-day_cnt):i]
            rets = []
            for hd in held_days:
                for sec, w in sectors:
                    r = sector_daily_ret(sec, hd, daily, ind_stocks)
                    if r is not None: rets.append(r * w)
            if rets:  # 退出日的收益计入
                pass
            position_log.append((entry, ed, [s[0] for s in sectors], '早退'))
            active_position = None
        
        # 更新持仓收益
        if active_position:
            entry, sectors, exit_date, day_cnt = active_position
            day_cnt += 1
            
            # 计算当日收益
            ret = 0
            held = []
            for sec, w in sectors:
                r = sector_daily_ret(sec, ed, daily, ind_stocks)
                if r is not None:
                    ret += r * w
                    held.append((sec, w))
            
            daily_pnl[ed] = ret
            daily_nav.append(daily_nav[-1] * (1 + ret/100))
            daily_holdings[ed] = held
            
            # 检查是否到期
            if day_cnt >= FORWARD_DAYS:
                position_log.append((entry, ed, [s[0] for s in sectors], '到期'))
                active_position = None
            else:
                active_position = (entry, sectors, exit_date, day_cnt)
        else:
            daily_nav.append(daily_nav[-1])  # 无持仓，净值不变
            daily_holdings[ed] = []
            daily_pnl[ed] = 0
        
        # 新开仓: 只在上升趋势
        if state == 1 and active_position is None:
            scored = scored_cache.get(ed, [])
            if scored:
                top = scored[:TOP_N]
                sectors = [(s['name'], 1.0/TOP_N) for s in top]
                active_position = (ed, sectors, None, 0)
                # 开仓当天不产生收益（T日收盘买入）
    
    return daily_nav, daily_pnl, daily_holdings, position_log


def sector_daily_ret(ind, date, daily, ind_stocks):
    """行业某日等权收益"""
    codes = ind_stocks.get(ind, [])
    snap = daily.get(date, {})
    rets = [snap[c] for c in codes if c in snap]
    return sum(rets)/len(rets) if rets else None


def score_day(ed, days, daily, ind_stocks, s2i):
    idx = days.index(ed)
    hist = days[max(0, idx-25):idx+1]
    snap = daily.get(ed, {})
    if not snap: return []
    
    # 构建industry_stats
    stats = {}
    for ind, codes in ind_stocks.items():
        rets = [snap[c] for c in codes if c in snap]
        if rets:
            stats[ind] = {
                'avg_ret': sum(rets)/len(rets),
                'up_ratio': sum(1 for r in rets if r>0)/len(rets)*100,
                'stock_count': len(codes),
            }
    if not stats: return []
    
    # RPS
    multi = {}
    for ind in stats:
        r5, r20 = [], []
        for i, hd in enumerate(reversed(hist)):
            s = daily.get(hd, {})
            rets = [s[c] for c in ind_stocks.get(ind, []) if c in s]
            if rets:
                avg = sum(rets)/len(rets)
                if i < 5: r5.append(avg)
                if i < 20: r20.append(avg)
        multi[ind] = {'ret_5d': sum(r5), 'ret_20d': sum(r20)}
    
    vol = {ind: 1.0 for ind in stats}
    lu = defaultdict(list)
    for c, p in snap.items():
        ind = s2i.get(c)
        if ind and p >= 9.5: lu[ind].append(c)
    
    return hs.score_hot_sectors(stats, multi, vol, lu, 0, {})


# ============================================================
# 绘图
# ============================================================

def plot_chart(market, market_dates, daily_nav, daily_pnl, daily_holdings, 
               position_log, eval_days, ext_days, daily, ind_stocks, s2i):
    print('绘图...', file=sys.stderr)
    
    fig = plt.figure(figsize=(22, 14), facecolor=c_bg)
    
    # 布局: 50% / 25% / 25%
    ax1 = fig.add_axes([0.07, 0.48, 0.90, 0.48], facecolor=c_ax)
    ax2 = fig.add_axes([0.07, 0.26, 0.90, 0.20], facecolor=c_ax)
    ax3 = fig.add_axes([0.07, 0.04, 0.90, 0.20], facecolor=c_ax)
    
    mdates_list = [datetime.strptime(d, '%Y%m%d') for d in market_dates if d in market]
    close_vals = [market[d]['close'] for d in market_dates if d in market]
    state_vals = [market[d]['state'] for d in market_dates if d in market]
    
    # ===== 子图1：大盘+趋势 =====
    ax1.plot(mdates_list, close_vals, color=c_price, linewidth=1.3, alpha=0.85)
    
    # 状态背景
    i = 0
    while i < len(state_vals):
        if state_vals[i] == 0: i+=1; continue
        s = state_vals[i]; j = i
        while j < len(state_vals) and state_vals[j] == s: j+=1
        color = {1:c_up, 2:c_risk, 3:c_down}.get(s, c_bg)
        # 用概率调alpha
        d = market_dates[i]
        m = market.get(d)
        if s == 1: prob = m['p_up']
        elif s == 2: prob = m['p_risk']
        else: prob = m['p_down']
        alpha = 0.06 + (prob-50)/38*0.34
        alpha = max(0.04, min(0.45, alpha))
        ax1.axvspan(mdates_list[i], mdates_list[min(j-1, len(mdates_list)-1)], 
                    alpha=alpha, color=color, zorder=0)
        mid = (i+j)//2
        if mid < len(mdates_list):
            sn = {1:'↑上升', 2:'⚠风险', 3:'↓下降'}
            ax1.text(mdates_list[mid], max(close_vals)*1.01, f'{sn[s]} {prob:.0f}%',
                    color=color, fontsize=8, fontweight='bold', ha='center', va='bottom',
                    bbox=dict(boxstyle='round,pad=0.15', facecolor=c_bg, edgecolor=color, alpha=0.8))
        i = j
    
    ax1.set_ylim(2500, max(close_vals)*1.08)
    ax1.set_ylabel('上证指数', color=c_label)
    ax1.tick_params(colors=c_label, labelsize=8)
    ax1.grid(True, alpha=0.1, color=c_grid)
    ax1.set_xlim(mdates_list[0], mdates_list[-1])
    ax1.set_xticklabels([])
    ax1.set_title('上证指数 + KDJ概率趋势系统', fontsize=14, color=c_label, fontweight='bold')
    
    # ===== 子图2：资金曲线 =====
    # [BUG FIX] 之前 nav_dates = mdates_list[:len(daily_nav)] 会选中缓冲期(12月)的日期
    # 但 daily_nav 对应的是 eval_days (1月起)，导致净值曲线左移约30天
    # 现在精确对齐: NAV[0]=1.0→首日, NAV[k+1]→eval_days[k]在mdates_list中的位置
    eval_set = set(eval_days)
    nav_dates = [mdates_list[0]]  # 初始净值放在第一个日期
    eval_idx = 0
    for md in mdates_list[1:]:
        if len(nav_dates) >= len(daily_nav):
            break
        if eval_idx < len(eval_days) and md.strftime('%Y%m%d') == eval_days[eval_idx]:
            nav_dates.append(md)
            eval_idx += 1
    
    ax2.plot(nav_dates, daily_nav, color='#00ff66', linewidth=1.8, alpha=0.9)
    ax2.fill_between(nav_dates, 1.0, daily_nav, alpha=0.08, color='#00ff66', 
                     where=(np.array(daily_nav) >= 1.0))
    ax2.axhline(y=1.0, color='#8b949e', linestyle='--', alpha=0.3, linewidth=0.6)
    
    # 构建日期→daily_nav索引映射（用于持仓标注和提前平仓）
    date_to_nav = {}
    for k, ed in enumerate(eval_days):
        idx = k + 1
        if idx < len(daily_nav):
            date_to_nav[ed] = idx
    
    # 标注持仓期（浅色竖条）
    for entry, exit_d, sectors, reason in position_log:
        if entry in market_dates and exit_d in market_dates:
            ei = market_dates.index(entry)
            xi = market_dates.index(exit_d)
            ax2.axvspan(mdates_list[ei], mdates_list[min(xi, len(mdates_list)-1)], 
                       alpha=0.06, color='#00ff66', zorder=0)
    
    # 标注提前平仓（用日期→NAV索引精确映射）
    for entry, exit_d, sectors, reason in position_log:
        if reason == '早退' and exit_d in market_dates:
            xi = market_dates.index(exit_d)
            nav_i = date_to_nav.get(exit_d, 0)
            ax2.scatter(mdates_list[xi], daily_nav[min(nav_i, len(daily_nav)-1)], 
                       color=c_down, s=40, marker='v', zorder=6, edgecolors='white', linewidth=0.5)
    
    final_nav = daily_nav[-1] if daily_nav else 1.0
    total_ret = (final_nav - 1.0) * 100
    years = len(eval_days) / TRADING_DAYS_PER_YEAR
    annual_ret = (final_nav ** (1/years) - 1) * 100 if years > 0 else 0
    
    ax2.set_title(f'策略净值  {total_ret:+.1f}%  年化{annual_ret:+.1f}%', 
                 fontsize=14, color=c_label, fontweight='bold')
    ax2.set_ylabel('净值', color=c_label)
    ax2.tick_params(colors=c_label, labelsize=8)
    ax2.grid(True, alpha=0.1, color=c_grid)
    ax2.set_xlim(mdates_list[0], mdates_list[-1])
    ax2.set_xticklabels([])
    
    # ===== 子图3：持仓板块 =====
    # 用颜色块显示持仓
    sector_colors = {}
    color_pool = ['#ff6b6b','#ffa502','#2ed573','#1e90ff','#a55eea',
                  '#ff4757','#ff6348','#7bed9f','#70a1ff','#eccc68']
    
    # 收集所有持仓行业
    all_held = set()
    for ed in eval_days:
        for sec, _ in daily_holdings.get(ed, []):
            all_held.add(sec)
    all_held = sorted(all_held)
    
    for idx, sec in enumerate(all_held):
        sector_colors[sec] = color_pool[idx % len(color_pool)]
    
    # 绘制持仓块
    y_pos = {sec: i for i, sec in enumerate(all_held)}
    y_center = len(all_held) / 2
    
    for ed in eval_days:
        held = daily_holdings.get(ed, [])
        if held and ed in market_dates:
            ei = market_dates.index(ed)
            for sec, w in held:
                color = sector_colors.get(sec, '#666666')
                ax3.bar(mdates_list[ei], 1, width=0.7, bottom=y_pos[sec], 
                       color=color, alpha=0.8, edgecolor='none')
    
    ax3.set_ylim(-0.5, len(all_held))
    ax3.set_yticks(range(len(all_held)))
    ax3.set_yticklabels(all_held, fontsize=6, color=c_label)
    ax3.set_title('持仓板块', fontsize=14, color=c_label, fontweight='bold')
    ax3.set_xlim(mdates_list[0], mdates_list[-1])
    ax3.tick_params(colors=c_label, labelsize=8)
    ax3.grid(True, alpha=0.1, color=c_grid, axis='x')
    
    # X轴
    for ax in [ax2, ax3]:
        ax.set_xlim(mdates_list[0], mdates_list[-1])
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8, color=c_label)
    
    output = '/mnt/e/Hermes_workspace/stock_research/2.行业板块判断/策略三合一.png'
    fig.savefig(output, dpi=150, facecolor=c_bg)
    plt.close(fig)
    print(f'✅ 已保存: {output}')


# ============================================================
# 主流程
# ============================================================

def main():
    print('=== 策略三合一图 ===')
    
    # 交易日
    print('\n[1] 交易日...', file=sys.stderr)
    all_days = get_trade_days(START_DATE, END_DATE)
    buff = get_trade_days('20241201', '20241231')
    ext_days = sorted(set(buff + all_days))
    eval_days = sorted(d for d in all_days if d >= START_DATE)
    print(f'  {len(eval_days)}评估日', file=sys.stderr)
    
    # 预取
    print('\n[2] 预取数据...', file=sys.stderr)
    idx_map, daily, money = prefetch_all(ext_days)
    
    # 大盘趋势
    print('\n[3] 大盘趋势...', file=sys.stderr)
    market, market_dates = compute_market_system(idx_map, ext_days)
    
    # 行业分类
    print('\n[4] 行业分类...', file=sys.stderr)
    s2i, ind_stocks, _ = hs.fetch_stock_industry_map()
    print(f'  {len(ind_stocks)}个行业', file=sys.stderr)
    
    # 策略模拟
    print('\n[5] 策略模拟...', file=sys.stderr)
    daily_nav, daily_pnl, daily_holdings, pos_log = simulate_strategy(
        market, eval_days, ext_days, daily, ind_stocks, s2i)
    
    # 统计
    up_days = sum(1 for d in eval_days if market.get(d,{}).get('state')==1)
    pos_days = sum(1 for ed in eval_days if daily_holdings.get(ed))
    early_exit = sum(1 for _,_,_,r in pos_log if r == '早退')
    
    final_nav = daily_nav[-1]
    total_ret = (final_nav - 1) * 100
    years = len(eval_days) / TRADING_DAYS_PER_YEAR
    annual_ret = (final_nav ** (1/years) - 1) * 100 if years > 0 else 0
    
    print(f'\n{"="*60}')
    print(f'策略统计')
    print(f'{"="*60}')
    print(f'  评估日: {len(eval_days)}天')
    print(f'  上升趋势日: {up_days}天 ({up_days/len(eval_days)*100:.0f}%)')
    print(f'  持仓日: {pos_days}天')
    print(f'  提前平仓: {early_exit}次')
    print(f'  总收益: {total_ret:+.1f}%')
    print(f'  年化收益: {annual_ret:+.1f}%')
    print(f'  交易次数: {len(pos_log)}次')
    
    # 绘图
    plot_chart(market, market_dates, daily_nav, daily_pnl, daily_holdings, 
              pos_log, eval_days, ext_days, daily, ind_stocks, s2i)


if __name__ == '__main__':
    main()
