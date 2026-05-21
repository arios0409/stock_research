"""
企业微信群机器人消息推送模块
使用 Webhook 方式发送消息到企业微信群
"""
import urllib.request
import json

# ============ 配置 ============
WEBHOOK_URL = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=62d8c6d6-df0a-410b-915d-bd8bbdd145a8'


def send_text(content: str, mentioned_list: list | None = None) -> dict:
    """发送文本消息"""
    payload = {
        'msgtype': 'text',
        'text': {
            'content': content,
        }
    }
    if mentioned_list:
        payload['text']['mentioned_list'] = mentioned_list
    return _post(payload)


def send_markdown(content: str) -> dict:
    """发送 Markdown 消息"""
    payload = {
        'msgtype': 'markdown',
        'markdown': {
            'content': content
        }
    }
    return _post(payload)


def send_image(base64_data: str, md5_hash: str) -> dict:
    """发送图片消息 (base64编码)"""
    payload = {
        'msgtype': 'image',
        'image': {
            'base64': base64_data,
            'md5': md5_hash
        }
    }
    return _post(payload)


def send_news(articles: list) -> dict:
    """发送图文消息
    articles: [{'title': '', 'description': '', 'url': '', 'picurl': ''}, ...]
    最多8条
    """
    payload = {
        'msgtype': 'news',
        'news': {
            'articles': articles
        }
    }
    return _post(payload)


def send_file(media_id: str) -> dict:
    """发送文件消息 (需先上传文件获取media_id)"""
    payload = {
        'msgtype': 'file',
        'file': {
            'media_id': media_id
        }
    }
    return _post(payload)


def upload_file(file_path: str) -> str:
    """上传文件到企业微信，返回 media_id"""
    import os
    from urllib.parse import urlencode

    url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key=62d8c6d6-df0a-410b-915d-bd8bbdd145a8&type=file'

    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        file_content = f.read()

    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    ).encode('utf-8') + file_content + f'\r\n--{boundary}--\r\n'.encode('utf-8')

    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errcode') == 0:
            return result.get('media_id', '')
        else:
            print(f'[WeCom] 上传失败: {result}')
            return ''
    except Exception as e:
        print(f'[WeCom] 上传异常: {e}')
        return ''


def _post(payload: dict) -> dict:
    """发送 POST 请求到 Webhook"""
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode('utf-8'))
        return result
    except Exception as e:
        return {'errcode': -1, 'errmsg': str(e)}


# ============ 快捷测试 ============
if __name__ == '__main__':
    result = send_text('wecom_notify 模块已就绪 ✅')
    print(result)