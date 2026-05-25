#!/usr/bin/env python3
"""用新渐变逻辑重绘历史日期的大盘图"""
import subprocess, os

SCRIPT_DIR = '/mnt/e/Hermes_workspace/stock_research/1.大盘趋势判断'
PROB = os.path.join(SCRIPT_DIR, 'probability_system.py')
PLOT = os.path.join(SCRIPT_DIR, 'plot_three_panels.py')

DATES = ['20260313', '20260317', '20260320', '20260323',
         '20260324', '20260325', '20260326', '20260327',
         '20260330', '20260331', '20260401', '20260402', '20260403']
RESTORE = '20260525'

for dt in DATES:
    for f in [PROB, PLOT]:
        with open(f, 'r') as fh:
            c = fh.read()
        c = c.replace(f'end_date="{RESTORE}"', f'end_date="{dt}"')
        with open(f, 'w') as fh:
            fh.write(c)
    subprocess.run(['python3', PLOT], capture_output=True, timeout=30)
    print(f'  ✅ {dt}')

for f in [PROB, PLOT]:
    with open(f, 'r') as fh:
        c = fh.read()
    c = c.replace(f'end_date="{DATES[-1]}"', f'end_date="{RESTORE}"')
    with open(f, 'w') as fh:
        fh.write(c)
print('✅ 全部完成，已恢复 end_date')
