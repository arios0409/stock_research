#!/usr/bin/env python3
"""
统一形态扫描器 - 扩展版（含创业板+科创板）
扫描5种形态：双底、三底、头肩底、三角收敛、旗形中继
每种形态推荐Top 10，生成CSV并推送到企业微信
"""

import os
import sys
import time
import json
import urllib.request
from datetime import datetime

# ============ 配置 ============
TUSHARE_TOKEN = '0265861c3dee65908f646a7c9e01f759ebda32a742b1728f92a7ad60'
API_URL = 'http://api.tushare.pro'
WEBHOOK_KEY_BOLIKELI = '62d8c6d6'  # 伯利克利群
WEBHOOK_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY_BOLIKELI}'
UPLOAD_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={WEBHOOK_KEY_BOLIKELI}&type=file'

BASE_DIR = '/mnt/d/Hermes_workspace/stock_research'
TODAY = datetime.now().strftime('%Y%m%d')

# ============ Tushare API ============
def api_call(api_name, fields=None, **kwargs):
    payload = {'api_name': api_name, 'token': TUSHARE_TOKEN, 'params': kwargs}
    if fields:
        payload['fields'] = fields
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') != 0:
            return None
        return result.get('data', {})
    except Exception as e:
        print(f"API调用失败: {e}")
        return None

def get_extended_stock_pool():
    """获取扩展股票池：沪深300 + 中证500 + 创业板 + 科创板"""
    print("获取股票池...")
    
    # 1. 沪深300
    hs300_data = api_call('index_weight', index_code='399300.SZ', fields='con_code')
    hs300 = set(item[0] for item in hs300_data['items']) if hs300_data and 'items' in hs300_data else set()
    print(f"  沪深300: {len(hs300)} 只")
    
    # 2. 中证500
    zz500_data = api_call('index_weight', index_code='000905.SH', fields='con_code')
    zz500 = set(item[0] for item in zz500_data['items']) if zz500_data and 'items' in zz500_data else set()
    print(f"  中证500: {len(zz500)} 只")
    
    # 3. 全市场股票（包含创业板和科创板）
    stock_basic = api_call('stock_basic', fields='ts_code,symbol,name,list_status')
    all_stocks = {}
    gemb = set()  # 创业板 300xxx
    kcb = set()   # 科创板 688xxx
    
    if stock_basic and 'items' in stock_basic:
        for item in stock_basic['items']:
            code = item[0]
            status = item[3] if len(item) > 3 else 'L'
            if status == 'L':
                all_stocks[code] = {'name': item[2], 'symbol': item[1]}
                if code.startswith('300'):
                    gemb.add(code)
                elif code.startswith('688'):
                    kcb.add(code)
    
    print(f"  创业板: {len(gemb)} 只")
    print(f"  科创板: {len(kcb)} 只")
    
    # 合并所有股票池
    combined = hs300 | zz500 | gemb | kcb
    valid_codes = [code for code in combined if code in all_stocks]
    
    print(f"  合计扫描: {len(valid_codes)} 只股票")
    return valid_codes, all_stocks

# ============ 企业微信推送 ============
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
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}

def send_text(content):
    """发送文本消息"""
    payload = {'msgtype': 'text', 'text': {'content': content}}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}

# ============ 扫描器调用 ============
def run_scanner(scanner_name, scanner_path, stock_codes, stock_map, top_n=10):
    """运行单个扫描器"""
    print(f"\n{'='*60}")
    print(f"扫描: {scanner_name}")
    print(f"{'='*60}")
    
    # 动态导入扫描器模块
    import importlib.util
    spec = importlib.util.spec_from_file_location(scanner_name, scanner_path)
    module = importlib.util.module_from_spec(spec)
    
    # 注入扩展股票池
    module.get_extended_stock_pool = lambda: (stock_codes, stock_map)
    
    try:
        spec.loader.exec_module(module)
        
        # 调用扫描器主逻辑
        if hasattr(module, 'scan_with_extended_pool'):
            results = module.scan_with_extended_pool(stock_codes, stock_map, top_n=top_n)
        else:
            # 兼容旧版本：修改股票池后调用main
            original_get_stock_list = module.get_stock_list
            module.get_stock_list = lambda: [stock_map[code] for code in stock_codes if code in stock_map]
            module.main()
            results = None
        
        return results
    except Exception as e:
        print(f"扫描失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("="*60)
    print("统一形态扫描器 - 扩展版")
    print(f"扫描日期: {TODAY}")
    print("="*60)
    
    # 获取扩展股票池
    stock_codes, stock_map = get_extended_stock_pool()
    
    # 定义5个扫描器
    scanners = [
        ('双底形态', os.path.join(BASE_DIR, '4.Bottom_reversal/1.double_bottom/double_bottom_scanner.py')),
        ('三底形态', os.path.join(BASE_DIR, '4.Bottom_reversal/3.Triple_Bottom/triple_bottom_scanner.py')),
        ('头肩底形态', os.path.join(BASE_DIR, '4.Bottom_reversal/2.Inverse_Head_Shoulders/ihs_scanner.py')),
        ('三角收敛', os.path.join(BASE_DIR, '3.Rising_continuation/1.Triangle_oscillation/triangle_scanner.py')),
        ('旗形中继', os.path.join(BASE_DIR, '3.Rising_continuation/2.Flag_continuation/bull_flag_scanner.py')),
    ]
    
    all_results = {}
    csv_files = []
    
    # 逐个扫描
    for scanner_name, scanner_path in scanners:
        if not os.path.exists(scanner_path):
            print(f"警告: {scanner_path} 不存在，跳过")
            continue
        
        results = run_scanner(scanner_name, scanner_path, stock_codes, stock_map, top_n=10)
        all_results[scanner_name] = results
        
        # 生成CSV（由各个扫描器自己生成）
        # CSV路径会在扫描器输出目录中
        csv_pattern = f"{scanner_name}_Top10_{TODAY}.csv"
        csv_files.append((scanner_name, csv_pattern))
    
    # 推送结果到企业微信
    print(f"\n{'='*60}")
    print("推送到企业微信（伯利克利群）")
    print(f"{'='*60}")
    
    # 发送汇总消息
    summary_msg = f"【形态扫描结果】{TODAY}\n\n"
    for scanner_name in all_results:
        summary_msg += f"✓ {scanner_name}\n"
    summary_msg += f"\n股票池: 沪深300 + 中证500 + 创业板 + 科创板\n"
    summary_msg += f"共 {len(stock_codes)} 只股票\n"
    summary_msg += f"每种形态推荐Top 10\n"
    summary_msg += f"\n详细CSV文件将陆续发送..."
    
    send_text(summary_msg)
    
    # 发送CSV文件
    for scanner_name, csv_filename in csv_files:
        # 查找CSV文件
        csv_path = None
        for root, dirs, files in os.walk(BASE_DIR):
            for file in files:
                if file.endswith('.csv') and TODAY in file and scanner_name.split('形态')[0] in file:
                    csv_path = os.path.join(root, file)
                    break
            if csv_path:
                break
        
        if csv_path and os.path.exists(csv_path):
            print(f"发送: {scanner_name} CSV")
            media_id = upload_file(csv_path)
            if media_id:
                result = send_file(media_id)
                print(f"  结果: {result}")
            else:
                print(f"  ❌ 上传失败")
            time.sleep(1)  # 避免限流
        else:
            print(f"警告: 找不到 {scanner_name} 的CSV文件")

if __name__ == '__main__':
    main()
