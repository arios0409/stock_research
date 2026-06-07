"""
驱动脚本：调双底扫描器，逐日扫描 2026-04-15 ~ 2026-05-10
每天独立运行，END_DATE 按日修改
"""
import os, sys, re, subprocess
from datetime import datetime, timedelta

BASE = '/mnt/d/Hermes_workspace/stock_research'
SCANNER = os.path.join(BASE, '4.Bottom_reversal/1.double_bottom/double_bottom_scanner.py')

date_range = []
d = datetime(2026, 4, 15)
while d <= datetime(2026, 5, 10):
    date_range.append(d.strftime('%Y%m%d'))
    d += timedelta(days=1)

print(f"双底扫描器逐日批处理")
print(f"日期范围: {date_range[0]} ~ {date_range[-1]} ({len(date_range)} 天)")
print(f"扫描器: {SCANNER}")
print()

total = len(date_range)
success_count = 0
fail_count = 0

for di, end_date in enumerate(date_range):
    print(f"\n{'='*60}")
    print(f"[{di+1}/{total}] END_DATE={end_date}")
    print(f"{'='*60}")

    # Modify END_DATE in scanner script
    with open(SCANNER, 'r') as f:
        content = f.read()
    content = re.sub(r"END_DATE\s*=\s*'[^']*'", f"END_DATE = '{end_date}'", content)
    with open(SCANNER, 'w') as f:
        f.write(content)

    # Run scanner
    workdir = os.path.dirname(SCANNER)
    try:
        result = subprocess.run(
            ['python3', SCANNER],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=600,
        )
        success = result.returncode == 0
        output = result.stdout + result.stderr

        # Print last lines for quick status
        lines = output.strip().split('\n')
        for line in lines[-8:]:
            print(f"  {line}")

        if success:
            success_count += 1
        else:
            fail_count += 1
            print(f"  [FAIL] exit code: {result.returncode}")

    except subprocess.TimeoutExpired:
        fail_count += 1
        print(f"  [TIMEOUT] 超过600秒")
    except Exception as e:
        fail_count += 1
        print(f"  [ERROR] {e}")

print(f"\n{'='*60}")
print(f"全部完成! 成功: {success_count}/{total}, 失败: {fail_count}/{total}")

# Restore END_DATE to a reasonable default
with open(SCANNER, 'r') as f:
    content = f.read()
content = re.sub(r"END_DATE\s*=\s*'[^']*'", "END_DATE = '20260510'", content)
with open(SCANNER, 'w') as f:
    f.write(content)
print(f"END_DATE 已恢复为 20260510")
