#!/usr/bin/env python3
"""发送策略三合一图和板块扫描结果到企业微信伯利克利群"""
import urllib.request
import json
import os
import sys

WEBHOOK_KEY = '62d8c6d6-df0a-410b-915d-bd8bbdd145a8'
WEBHOOK_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY}'
UPLOAD_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={WEBHOOK_KEY}&type=file'

def post(payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}

def upload_file(file_path):
    """上传文件，返回media_id"""
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
            print(f'上传失败: {result}', file=sys.stderr)
            return ''
    except Exception as e:
        print(f'上传异常: {e}', file=sys.stderr)
        return ''

def send_file(media_id):
    return post({'msgtype': 'file', 'file': {'media_id': media_id}})

def send_text(content):
    return post({'msgtype': 'text', 'text': {'content': content}})

# ===== 1. 发送策略图 =====
chart_path = '/mnt/e/Hermes_workspace/stock_research/2.行业板块判断/策略三合一.png'
print('上传策略图...')
media_id = upload_file(chart_path)
if media_id:
    r = send_file(media_id)
    print(f'  文件发送结果: {r}')
else:
    print('  ❌ 上传失败，尝试发送文字通知')
    send_text('【策略三合一图】生成成功，但上传到企业微信失败')

# ===== 2. 发送板块扫描5/22结果 =====
sector_msg = """【A股热门板块扫描】2026-05-22

📈 市场: 上升趋势(MA↑+KDJ↓) 沪深300: +1.30%
🔥 Top3优势板块（预估+3d延续性）:

🥇 元器件(85分)
  当日+7.17% RPS5=98 RPS20=97 涨停28家
  主力净流+9.4% | 5日+5.43% 20日+15.21%
  ✅ 加速热点(顺势) — 量价资金共振

🥈 玻璃(83分)
  当日+6.31% RPS5=99 RPS20=98 涨停4家
  主力净流+10.4% | 5日+6.38% 20日+15.95%
  ✅ 持续热点 — 多周期强势

🥉 公路(82分)
  当日+3.77% RPS5=97 RPS20=94 量比2.3x
  主力净流-9.0% | 5日+4.46% 20日+11.43%
  ✅ 持续热点 — 高量比突破

📊 关注板块:
铜(74) 矿物制品(74) 铝(69) 机械基件(68) 半导体(67)

⚠ 风险提示: 以上为量化扫描结果，不构成投资建议"""

r = send_text(sector_msg)
print(f'板块扫描文字发送结果: {r}')
