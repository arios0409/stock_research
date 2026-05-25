#!/usr/bin/env python3
"""发送板块扫描结果到企业微信伯利克利群"""
import urllib.request
import json
import os

WEBHOOK_KEY = '62d8c6d6-df0a-410b-915d-bd8bbdd145a8'
WEBHOOK_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY}'

def post(payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}

msg = """【A股热门板块扫描】2026-05-25

📈 市场: 上升趋势(MA↑+KDJ↓) 沪深300: +1.58%
涨停105只，仅4个行业主力净流入，整体资金偏弱

🔥 Top3优势板块：

🥇 电子(89分)
  当日+3.00% RPS5=100 RPS20=100 涨停24家
  主力净流+2.2% | 5日+6.60% 20日+19.45%
  ✅ 持续热点 — 量价资金全面共振，最强板块

🥈 建筑材料(73分)
  当日+0.75% RPS5=93 RPS20=93 涨停3家
  主力净流+0.3% | 5日+1.02% 20日+5.11%
  ✅ 关注中 — RPS双高，资金小幅流入

🥉 煤炭(66分)
  当日+3.05% RPS5=52 RPS20=66 涨停3家
  主力净流-7.7% | 5日-2.21% 20日+0.04%
  ⭐ 新兴热点 — 宽度88%极高，注意资金流出

📊 Top4-5:
机械设备(66) 公用事业(65)

📊 关注板块:
通信(64) 有色金属(62) 交通运输(57) 电力设备(53) 房地产(52)

📊 延续性分布:
• 持续热点: 电子
• 新兴热点: 煤炭、机械设备、公用事业
• 关注中: 建筑材料、通信、有色金属、交通运输、电力设备、房地产

⚠️ 风险提示: 以上为量化扫描结果，不构成投资建议"""

r = post({'msgtype': 'markdown', 'markdown': {'content': msg}})
print(f'发送结果: {r}')
