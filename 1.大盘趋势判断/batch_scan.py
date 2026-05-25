#!/usr/bin/env python3
"""
批量扫描大盘：2026-03-24 到 2026-04-03 每天生成三子图
"""
import subprocess, os, sys

SCRIPT_DIR = '/mnt/e/Hermes_workspace/stock_research/1.大盘趋势判断'
PROB_SCRIPT = os.path.join(SCRIPT_DIR, 'probability_system.py')
PLOT_SCRIPT = os.path.join(SCRIPT_DIR, 'plot_three_panels.py')

DATES = [
    '20260324', '20260325', '20260326', '20260327',
    '20260330', '20260331',
    '20260401', '20260402', '20260403',
]

RESTORE_DATE = '20260525'

def patch_date(filepath, old_date, new_date):
    with open(filepath, 'r') as f:
        content = f.read()
    content = content.replace(f'end_date="{old_date}"', f'end_date="{new_date}"')
    with open(filepath, 'w') as f:
        f.write(content)

for dt in DATES:
    print(f'\n{"="*60}')
    print(f'  扫描 {dt}')
    print(f'{"="*60}')

    # 改日期
    patch_date(PROB_SCRIPT, RESTORE_DATE if dt == DATES[0] else DATES[DATES.index(dt)-1], dt)
    patch_date(PLOT_SCRIPT, RESTORE_DATE if dt == DATES[0] else DATES[DATES.index(dt)-1], dt)

    # 画图
    r = subprocess.run(['python3', PLOT_SCRIPT], capture_output=True, text=True, timeout=30)
    out = r.stdout + r.stderr
    for line in out.split('\n'):
        if '已保存' in line or '信号标记' in line:
            print(f'  {line}')

    # 文字输出（只取最后5行行情摘要）
    r = subprocess.run(['python3', PROB_SCRIPT], capture_output=True, text=True, timeout=30)
    lines = r.stdout.split('\n')
    # 找到最后几个有效数据行
    data_lines = [l for l in lines if l.strip() and l[0].isdigit()]
    if data_lines:
        last = data_lines[-1]
        print(f'  → {last.strip()}')

# 恢复
print(f'\n{"="*60}')
print(f'  恢复 end_date 至 {RESTORE_DATE}')
print(f'{"="*60}')
patch_date(PROB_SCRIPT, DATES[-1], RESTORE_DATE)
patch_date(PLOT_SCRIPT, DATES[-1], RESTORE_DATE)
print('  ✅ 完成')
