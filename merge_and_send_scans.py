#!/usr/bin/env python3
"""合并扫描器图片并推送到企业微信"""
import os
import glob
import base64
import hashlib
import urllib.request
import json
import time
import subprocess

# 企业微信配置
WEBHOOK_KEY = '62d8c6d6-df0a-410b-915d-bd8bbdd145a8'
WEBHOOK_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_KEY}'
UPLOAD_URL = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={WEBHOOK_KEY}&type=file'

# 扫描器配置
SCANNERS = [
    {
        'name': '双底扫描',
        'dir': '4.Bottom_reversal/1.double_bottom/20260619_data',
        'csv': '双底扫描_results_20260619.csv',
        'category': '底部反转形态'
    },
    {
        'name': '头肩底扫描',
        'dir': '4.Bottom_reversal/2.Inverse_Head_Shoulders/20260619_data',
        'csv': '头肩底扫描_results_20260619.csv',
        'category': '底部反转形态'
    },
    {
        'name': '三底扫描',
        'dir': '4.Bottom_reversal/3.Triple_Bottom/20260619_data',
        'csv': '三底扫描_results_20260619.csv',
        'category': '底部反转形态'
    },
    {
        'name': '三角收敛扫描',
        'dir': '3.Rising_continuation/1.Triangle_oscillation/20260619_data',
        'csv': '三角收敛扫描_results_20260619.csv',
        'category': '上升中继形态'
    },
    {
        'name': '旗形中继扫描',
        'dir': '3.Rising_continuation/2.Flag_continuation/20260619_data',
        'csv': '旗形中继扫描_results_20260619.csv',
        'category': '上升中继形态'
    }
]

def get_top_svgs(scanner_dir, max_count=10):
    """获取排名前N的SVG文件"""
    svgs = []
    for i in range(1, max_count + 1):
        pattern = os.path.join(scanner_dir, f'top{i}_*.svg')
        matches = glob.glob(pattern)
        if matches:
            svgs.append(matches[0])
    return svgs

def convert_svg_to_png_batch(svg_files, output_dir):
    """使用rsvg-convert批量转换SVG为PNG"""
    png_files = []
    for svg_path in svg_files:
        basename = os.path.splitext(os.path.basename(svg_path))[0]
        png_path = os.path.join(output_dir, f'{basename}.png')
        
        # 使用rsvg-convert（速度快，质量好）
        cmd = ['rsvg-convert', '-w', '1200', '-o', png_path, svg_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            png_files.append(png_path)
        except subprocess.CalledProcessError as e:
            print(f"    rsvg转换失败: {e}")
            # 尝试使用librsvg
            try:
                cmd = ['convert', '-density', '150', '-resize', '1200x', svg_path, png_path]
                subprocess.run(cmd, check=True, capture_output=True, timeout=10)
                png_files.append(png_path)
            except:
                print(f"    ImageMagick也失败，跳过: {svg_path}")
    
    return png_files

def merge_images_vertically(png_files, title, output_path, max_width=1200):
    """垂直合并多张PNG图片"""
    if not png_files:
        return None
    
    from PIL import Image, ImageDraw, ImageFont
    
    images = []
    for path in png_files:
        try:
            img = Image.open(path).convert('RGB')
            # 等比缩放
            if img.width != max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            images.append(img)
        except Exception as e:
            print(f"    加载失败 {path}: {e}")
            continue
    
    if not images:
        return None
    
    # 计算总高度
    total_height = sum(img.height for img in images)
    
    # 创建标题区域
    title_height = 100
    title_img = Image.new('RGB', (max_width, title_height), color='#1a1a2e')
    draw = ImageDraw.Draw(title_img)
    
    # 尝试加载字体
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    except:
        font = ImageFont.load_default()
    
    # 绘制标题
    bbox = draw.textbbox((0, 0), title, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = (max_width - text_width) // 2
    draw.text((text_x, 25), title, fill='#00d4ff', font=font)
    
    # 创建合并图片
    merged = Image.new('RGB', (max_width, title_height + total_height), color='#0f0f1e')
    merged.paste(title_img, (0, 0))
    
    # 粘贴所有图片
    y_offset = title_height
    for img in images:
        merged.paste(img, (0, y_offset))
        y_offset += img.height
    
    # 保存
    merged.save(output_path, 'PNG', quality=95, optimize=True)
    return output_path

def send_image(image_path, title):
    """发送图片到企业微信（使用base64+md5方式）"""
    if not os.path.exists(image_path):
        print(f"    文件不存在: {image_path}")
        return False
    
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        base64_data = base64.b64encode(image_data).decode()
        md5_hash = hashlib.md5(image_data).hexdigest()
        
        payload = {
            "msgtype": "image",
            "image": {
                "base64": base64_data,
                "md5": md5_hash
            }
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('errcode') == 0:
                print(f"    ✓ 图片发送成功: {title}")
                return True
            else:
                print(f"    ✗ 图片发送失败: {result}")
    except Exception as e:
        print(f"    ✗ 发送异常: {e}")
    
    return False

def send_csv(csv_path, title):
    """发送CSV文件到企业微信（先上传再发送）"""
    if not os.path.exists(csv_path):
        print(f"    CSV不存在: {csv_path}")
        return False
    
    try:
        filename = os.path.basename(csv_path)
        
        # 上传文件
        with open(csv_path, 'rb') as f:
            file_content = f.read()
        
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        body = b''
        body += f'--{boundary}\r\n'.encode()
        body += f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'.encode()
        body += f'Content-Type: application/octet-stream\r\n\r\n'.encode()
        body += file_content
        body += f'\r\n--{boundary}--\r\n'.encode()
        
        headers = {
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(body))
        }
        
        req = urllib.request.Request(UPLOAD_URL, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
            
            if result.get('errcode') == 0:
                media_id = result.get('media_id')
                
                # 发送文件
                msg_data = {
                    'msgtype': 'file',
                    'file': {'media_id': media_id}
                }
                
                req = urllib.request.Request(
                    WEBHOOK_URL,
                    data=json.dumps(msg_data).encode(),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    send_result = json.loads(response.read().decode())
                    if send_result.get('errcode') == 0:
                        print(f"    ✓ CSV发送成功: {title}")
                        return True
                    else:
                        print(f"    ✗ CSV发送失败: {send_result}")
            else:
                print(f"    ✗ CSV上传失败: {result}")
    except Exception as e:
        print(f"    ✗ CSV发送异常: {e}")
    
    return False

def process_scanner(scanner):
    """处理单个扫描器：合并图片+发送图片和CSV"""
    name = scanner['name']
    scan_dir = scanner['dir']
    csv_file = scanner['csv']
    category = scanner['category']
    
    print(f"\n[{category}] {name}")
    
    # 获取SVG文件
    svgs = get_top_svgs(scan_dir, max_count=10)
    count = len(svgs)
    print(f"  找到 {count} 张图")
    
    if count == 0:
        print(f"  跳过（无图片）")
        return False
    
    # 转换SVG为PNG
    print(f"  转换SVG -> PNG...")
    png_files = convert_svg_to_png_batch(svgs, scan_dir)
    
    if not png_files:
        print(f"  PNG转换失败")
        return False
    
    # 合并图片
    print(f"  合并 {len(png_files)} 张图片...")
    output_path = os.path.join(scan_dir, f'{name}_Top{count}_20260619.png')
    merged = merge_images_vertically(png_files, f'{name} Top{count}', output_path)
    
    if not merged:
        print(f"  合并失败")
        return False
    
    print(f"  合并完成: {os.path.basename(merged)}")
    
    # 发送图片
    print(f"  发送图片...")
    img_ok = send_image(merged, f'{category} - {name}')
    
    time.sleep(1)
    
    # 发送CSV
    csv_path = os.path.join(scan_dir, csv_file)
    print(f"  发送CSV...")
    csv_ok = send_csv(csv_path, csv_file)
    
    return img_ok and csv_ok

def main():
    print("=" * 70)
    print("扫描结果图片合并与推送")
    print("=" * 70)
    
    results = []
    for scanner in SCANNERS:
        success = process_scanner(scanner)
        results.append((scanner['name'], success))
        time.sleep(2)  # 避免请求过快
    
    print("\n" + "=" * 70)
    print("推送结果汇总:")
    print("=" * 70)
    for name, ok in results:
        status = "✓ 成功" if ok else "✗ 失败"
        print(f"  {name:15s} {status}")
    print("=" * 70)

if __name__ == '__main__':
    main()
