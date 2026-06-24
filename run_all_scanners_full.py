#!/usr/bin/env python3
"""
统一运行5个扫描器_full版本（扩展股票池版）
扫描完成后推送到企业微信伯利克利群，并发送CSV文件
"""

import subprocess
import os
import time
import json
import urllib.request
from datetime import datetime

BASE_DIR = '/mnt/d/Hermes_workspace/stock_research'
WEBHOOK_KEY = '62d8c6d6-df0a-410b-915d-bd8bbdd145a8'
WEBHOOK_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY}'
UPLOAD_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={WEBHOOK_KEY}&type=file'

SCANNERS = [
    ('双底扫描', '4.Bottom_reversal/1.double_bottom/double_bottom_scanner_full.py'),
    ('三底扫描', '4.Bottom_reversal/3.Triple_Bottom/triple_bottom_scanner_full.py'),
    ('头肩底扫描', '4.Bottom_reversal/2.Inverse_Head_Shoulders/ihs_scanner_full.py'),
    ('三角收敛扫描', '3.Rising_continuation/1.Triangle_oscillation/triangle_scanner_full.py'),
    ('旗形中继扫描', '3.Rising_continuation/2.Flag_continuation/bull_flag_scanner_full.py'),
]

def post_wechat(payload):
    """发送消息到企业微信"""
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}

def upload_file(file_path):
    """上传文件到企业微信"""
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        file_content = f.read()
    
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    ).encode('utf-8') + file_content + f'\r\n--{boundary}--\r\n'.encode('utf-8')
    
    req = urllib.request.Request(UPLOAD_URL, data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errcode') == 0:
            return result.get('media_id', '')
        else:
            print(f'上传失败: {result}')
            return ''
    except Exception as e:
        print(f'上传异常: {e}')
        return ''

def send_file(media_id):
    """发送文件"""
    payload = {'msgtype': 'file', 'file': {'media_id': media_id}}
    return post_wechat(payload)

def send_text(content):
    """发送文本消息"""
    payload = {'msgtype': 'text', 'text': {'content': content}}
    return post_wechat(payload)

def run_scanner(name, script_path):
    """运行单个扫描器"""
    print(f"\n{'='*60}")
    print(f"运行: {name}")
    print(f"脚本: {script_path}")
    print(f"{'='*60}")
    
    full_path = os.path.join(BASE_DIR, script_path)
    script_dir = os.path.dirname(full_path)
    
    start_time = time.time()
    result = subprocess.run(
        ['python3', full_path],
        cwd=script_dir,
        capture_output=False,
        text=True
    )
    elapsed = time.time() - start_time
    
    print(f"\n{name} 完成，耗时: {elapsed:.1f}秒，退出码: {result.returncode}")
    return result.returncode == 0

def find_csv_files(scanner_name, end_date):
    """查找生成的CSV文件"""
    csv_files = []
    
    # 扫描各个可能的输出目录
    for root, dirs, files in os.walk(BASE_DIR):
        for file in files:
            if file.endswith('.csv') and scanner_name in file and end_date in file:
                csv_files.append(os.path.join(root, file))
    
    return csv_files

def main():
    end_date = '20260619'
    print(f"开始运行5个扫描器（扩展版），截止日期: {end_date}")
    print(f"股票池: 沪深300 + 中证500 + 创业板 + 科创板")
    print(f"每个扫描器推荐Top 10\n")
    
    total_start = time.time()
    results = []
    
    for name, script_path in SCANNERS:
        success = run_scanner(name, script_path)
        results.append((name, success))
        
        # 扫描间隔，避免API限流
        if name != SCANNERS[-1][0]:
            print("\n等待30秒后继续...")
            time.sleep(30)
    
    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"全部扫描完成，总耗时: {total_elapsed:.1f}秒")
    print(f"{'='*60}")
    
    # 汇总结果
    success_count = sum(1 for _, s in results if s)
    print(f"\n成功: {success_count}/{len(results)}")
    for name, success in results:
        status = '✓' if success else '✗'
        print(f"  {status} {name}")
    
    # 推送结果到企业微信
    print(f"\n{'='*60}")
    print("推送结果到企业微信（伯利克利群）")
    print(f"{'='*60}")
    
    # 发送汇总消息
    summary_msg = f"【形态扫描结果】{datetime.now().strftime('%Y-%m-%d')}\n\n"
    summary_msg += f"扫描范围: 沪深300 + 中证500 + 创业板 + 科创板\n"
    summary_msg += f"截止日期: {end_date}\n"
    summary_msg += f"每个形态推荐Top 10\n\n"
    
    summary_msg += "扫描项目:\n"
    for name, success in results:
        status = '✓' if success else '✗'
        summary_msg += f"  {status} {name}\n"
    
    summary_msg += f"\n总耗时: {total_elapsed/60:.1f}分钟\n"
    summary_msg += f"详细CSV文件将陆续发送..."
    
    print("\n发送汇总消息...")
    r = send_text(summary_msg)
    print(f"  结果: {r}")
    time.sleep(2)
    
    # 发送CSV文件
    print("\n发送CSV文件...")
    csv_sent = 0
    for name, success in results:
        if not success:
            print(f"  跳过 {name} (扫描失败)")
            continue
        
        # 查找CSV文件
        csv_files = find_csv_files(name, end_date)
        
        if not csv_files:
            # 尝试不带"扫描"的文件名
            csv_files = find_csv_files(name.replace('扫描', ''), end_date)
        
        if csv_files:
            for csv_file in csv_files:
                print(f"\n  上传: {os.path.basename(csv_file)}")
                media_id = upload_file(csv_file)
                if media_id:
                    r = send_file(media_id)
                    print(f"    发送结果: {r}")
                    csv_sent += 1
                else:
                    print(f"    ❌ 上传失败")
                time.sleep(2)
        else:
            print(f"  警告: 找不到 {name} 的CSV文件")
    
    print(f"\n{'='*60}")
    print(f"推送完成，共发送 {csv_sent} 个CSV文件")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
