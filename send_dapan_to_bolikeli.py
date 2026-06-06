#!/usr/bin/env python3
"""发送大盘趋势扫描结果到企业微信伯利克利群"""
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

# ===== 发送图表 =====
chart_path = '/mnt/d/Hermes_workspace/stock_research/1.Shanghai_composite_trend_detect/20260529_三子图_高对比.png'
print('上传大盘趋势图...')
media_id = upload_file(chart_path)
if media_id:
    r = send_file(media_id)
    print(f'  文件发送结果: {r}')
else:
    print('  ❌ 上传失败')
    send_text('【上证指数概率趋势图】生成成功，但上传到企业微信失败')

# ===== 发送文字分析 =====
dapan_msg = """【上证指数 KDJ概率趋势系统】2026-06-01

📊 当前状态: ↓下降 (P_up=10% P_down=60% P_risk=22%)
K=29.4 D=38.6 K<D 死叉运行中，已进入K<35&D<40危险区

📉 近期走势:
5/14  ↑上升 → ⚠风险 (高位死叉 K=87.7)
5/15-5/21 连续 ⚠风险状态 (7天)
5/22  ⚠风险 → ↓下降 (K跌至46.5)
5/25-5/29  持续 ↓下降，K值从46→29
5/29 K=29.4已进入超卖区(K<35&D<40)

🔍 关键信号:
• K值29.4 为2024年10月以来最低
• P_down=60% > P_up=10%，下降趋势占优
• 已连续6个交易日处于下降状态
• 本轮从5/14高位死叉已持续11个交易日
• K值已触及超卖区，关注金叉反转信号

📈 历史信号统计 (2024.08-2026.05):
• P_up≥60买入: 23次 +3d胜率73.9% +5d胜率69.6%
• P_up≥75买入: 19次 +3d胜率79%
• P_down≥55卖出: 10次 +3d下跌胜率22%(死叉卖点不可靠)

⚠ 当前建议: K已触底超卖区，等待K上穿D金叉信号确认反转再入场"""

r = post({'msgtype': 'markdown', 'markdown': {'content': dapan_msg}})
print(f'文字发送结果: {r}')
