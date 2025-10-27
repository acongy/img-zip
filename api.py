from flask import Flask, request, send_file, render_template, jsonify, g, current_app
from flask_mail import Mail
from PIL import Image
import io
import subprocess
import platform
import os
from werkzeug.utils import secure_filename
import threading
import logging
from logging.handlers import TimedRotatingFileHandler, SMTPHandler
import uuid
import time
from functools import wraps
from datetime import datetime, timedelta
import jwt


# 自定义日志过滤器：注入请求ID（处理非请求上下文）
class RequestIDFilter(logging.Filter):
    def filter(self, record):
        try:
            if current_app and hasattr(g, 'request_id'):
                record.request_id = g.request_id
            else:
                record.request_id = 'N/A'
        except RuntimeError:
            record.request_id = 'N/A'  # 非请求上下文时使用默认值
        return True


# 配置日志：输出到控制台并按日期轮转保存到本地文件（每天一个文件，保留30天备份）
# 手动创建处理器以添加过滤器
handler_console = logging.StreamHandler()
handler_console.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - [REQ-%(request_id)s] - %(message)s'
))
handler_console.addFilter(RequestIDFilter())

# 创建 logs 目录（如果不存在）
os.makedirs('logs', exist_ok=True)

handler_file = TimedRotatingFileHandler(
    'logs/app.log',
    when='midnight',  # 每天午夜轮转
    interval=1,  # 间隔1天
    backupCount=30,  # 保留30个备份文件
    encoding='utf-8'
)

handler_file.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - [REQ-%(request_id)s] - %(message)s'
))
handler_file.addFilter(RequestIDFilter())

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler_console, handler_file]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# 增加到 1G
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024

# JWT 配置：用于 Token 认证
app.config['SECRET_KEY'] = '4ZFRssDQbFs7fL3Hj_8Lrk61wq76msCzTCK9dMfi8vM'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

# 邮箱配置：请替换为实际的 SMTP 配置
app.config['MAIL_SERVER'] = 'smtp.exmail.qq.com'
# SMTP 服务器
# SMTP 端口
app.config['MAIL_PORT'] = 465
# 使用 SSL
app.config['MAIL_USE_SSL'] = True
# 发件人邮箱
app.config['MAIL_USERNAME'] = 'yangdengcong@starjade.asia'
# 应用专用密码（非账户密码）
app.config['MAIL_PASSWORD'] = '4Yyt9H93sD8kPWaU'
# 收件人邮箱列表
app.config['ADMINS'] = ['yangdengcong@starjade.asia']

mail = Mail(app)

# 账户
USERS = {
    'starjade-server': 'AtarJade@8085$',
    'gsg-server': 'GsG@8089%'
}


def send_alert_email(subject, body):
    """发送警报邮件"""
    html_template = """<!DOCTYPE html>
                <html lang="zh">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>安全警报</title>
                    <style>
                        body { margin: 0; padding: 20px; font-family: Arial, sans-serif; background-color: #f0f0f0; }
                        .email-container { max-width: 600px; margin: 0 auto; }
                        .alert-content { 
                            padding: 30px 20px 20px; 
                            border: 1px solid #ff6b6b; 
                            color: #333; 
                            line-height: 1.7; 
                            font-size: 15px; 
                            background-color: #fff5f5;
                            word-wrap: break-word;
                            overflow-wrap: break-word;
                            hyphens: auto;
                        }
                        .alert-title {
                            color: #ff4444; 
                            font-size: 18px; 
                            font-weight: bold;
                            word-wrap: break-word;
                            overflow-wrap: break-word;
                        }
                        .alert-body {
                            word-wrap: break-word;
                            overflow-wrap: break-word;
                            hyphens: auto;
                            white-space: pre-wrap; 
                        }
                        .separator {
                            border: none;
                            height: 1px;
                            background-color: #ff6b6b;
                            margin: 15px 0;
                        }
                    </style>
                </head>
                <body>
                <div class="email-container">
                    <div class="alert-content">
                        <p class="alert-title">%s</p>
                        <hr class="separator">
                        <p class="alert-body">%s</p>
                    </div>
                </div>
                </body>
                </html>"""
    from flask_mail import Message
    msg = Message(subject, recipients=app.config['ADMINS'], sender=app.config['MAIL_USERNAME'])
    msg.html = html_template % (subject, body)
    try:
        mail.send(msg)
        logger.info("警报邮件发送成功")
    except Exception as e:
        logger.error(f"邮件发送失败: {str(e)}")


def generate_token(username):
    """
        生成 JWT Token
    """
    payload = {
        'username': username,
        'exp': datetime.utcnow() + app.config['JWT_ACCESS_TOKEN_EXPIRES']
    }
    return jwt.encode(payload, app.config['SECRET_KEY'], algorithm='HS256')


def verify_token(f):
    """装饰器：验证 JWT Token"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            logger.warning(f"Token 缺失或格式错误，客户端IP: {request.remote_addr}")
            return jsonify({"msg": "Token 缺失或无效", 'code': 401}), 401
        try:
            token = auth_header.split(' ')[1]
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user = payload['username']  # 注入当前用户到 g
            logger.info(f"Token 验证成功，用户: {g.current_user}，客户端IP: {request.remote_addr}")
        except jwt.ExpiredSignatureError:
            logger.warning(f"Token 已过期，客户端IP: {request.remote_addr}")
            return jsonify({"msg": "Token 已过期", 'code': 401}), 401
        except jwt.InvalidTokenError:
            logger.warning(f"Token 无效，客户端IP: {request.remote_addr}")
            return jsonify({"msg": "Token 无效", 'code': 401}), 401

        return f(*args, **kwargs)

    return decorated_function


# 请求钩子：为每个请求生成ID（使用 g 对象，确保线程安全）
@app.before_request
def before_request():
    g.request_id = str(uuid.uuid4())[:8]  # 短UUID
    g.start_time = time.time()


@app.after_request
def after_request(response):
    duration = time.time() - g.start_time
    logger.info(f"请求结束，耗时: {duration:.2f}秒，状态: {response.status_code}")
    return response


def get_pngquant_path():
    """根据系统返回 pngquant 可执行文件路径"""
    system = platform.system().lower()
    if system.startswith("win"):  # Windows
        return os.path.join("pngquant-win", "pngquant.exe")
    else:  # Linux
        return os.path.join("pngquant-linux", "pngquant")


def compress_png_with_pngquant(input_bytes, quality_value=80):
    # 将用户的 0-100 质量值映射到 pngquant 的 min-max
    min_q = max(0, quality_value - 20)
    max_q = quality_value
    try:
        pngquant_path = get_pngquant_path()
        logger.info(f"开始 PNGQuant 压缩，质量范围: {min_q}-{max_q}")
        process = subprocess.Popen(
            [pngquant_path, f'--quality={min_q}-{max_q}', '--speed', '1', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out, err = process.communicate(input=input_bytes)
        if process.returncode == 0 and out:
            logger.info("PNGQuant 压缩成功完成")
            return io.BytesIO(out)
        else:
            # 如果 pngquant 出错，返回原始数据
            logger.warning("PNGQuant 失败，回退到原始数据")
            return io.BytesIO(input_bytes)
    except Exception as e:
        logger.error(f"PNGQuant 压缩错误: {str(e)}")
        return io.BytesIO(input_bytes)


def compress_image(file_stream, quality=80, use_pngquant=True, client_ip=None, filename=None):
    """
    压缩图片（优化版）：
    - GIF: 不处理
    - JPEG: 有损压缩，剥离元数据，添加渐进式，质量上限85，如果变大回退原始
    - PNG: 优先保留 Indexed 模式，无损优化；仅在 pngquant 时转为 RGBA
    返回 (compressed_io, mime_type, original_size, compressed_size)
    """
    logger.info(
        f"开始图片压缩，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}，质量: {quality}, 使用 pngquant: {use_pngquant}")
    original_size = len(file_stream.read())
    file_stream.seek(0)
    img = Image.open(file_stream)

    if img.format == "GIF":
        logger.info(
            f"检测到 GIF: 跳过压缩，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
        file_stream.seek(0)
        compressed_output = io.BytesIO(file_stream.read())
        compressed_output.seek(0)
        return compressed_output, "image/gif", original_size, original_size
    elif img.format == "PNG":
        logger.info(
            f"检测到 PNG (模式: {img.mode})，原始大小: {round(original_size / 1024 / 1024, 2)} MB，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
        # 先尝试无损优化，保留原模式
        output = io.BytesIO()
        save_kwargs = {"format": "PNG", "optimize": True, "compress_level": 9}

        if use_pngquant:
            # pngquant 需要 RGBA
            if img.mode != "RGBA":
                logger.info(
                    f"将 PNG 转换为 RGBA 以用于 PNGQuant，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
                img = img.convert("RGBA")
            img.save(output, **save_kwargs)
            output_bytes = output.getvalue()
            compressed_output = compress_png_with_pngquant(output_bytes, quality)  # 假设此函数存在
        else:
            # 无 pngquant 时，保留原模式（Indexed 优先）
            if img.mode == "P" and img.palette is not None:
                # 确保 Indexed 模式下有调色板
                save_kwargs["palette"] = img.palette
                logger.info(
                    f"在 Indexed 模式下保存 PNG，无 PNGQuant，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
            img.save(output, **save_kwargs)
            compressed_output = output

        compressed_output.seek(0)
        compressed_size = len(compressed_output.read())
        compressed_output.seek(0)
        logger.info(
            f"PNG 压缩完成: 原始 {round(original_size / 1024 / 1024, 2)} -> 压缩 {round(compressed_size / 1024 / 1024, 2)} MB (比率: {compressed_size / original_size:.2%})，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")

        # 检查是否变大超过3%，发送警告
        if compressed_size > original_size * 1.03:
            current_user = getattr(g, 'current_user', '未知')
            subject = f"图片压缩警告: {filename if filename else '未知'} 变大超过3%"
            orig_mb = round(original_size / (1024 * 1024), 2)
            comp_mb = round(compressed_size / (1024 * 1024), 2)
            body = f"""文件: {filename if filename else '未知'}
用户: {current_user}
IP: {client_ip if client_ip else '未知'}
原始大小: {orig_mb} MB
压缩后大小: {comp_mb} MB
比率: {compressed_size / original_size:.2%}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            send_alert_email(subject, body)

        return compressed_output, "image/png", original_size, compressed_size
    else:
        # JPEG 压缩（优化版）
        logger.info(
            f"检测到 JPEG，原始大小: {round(original_size / 1024 / 1024, 2)} MB，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")

        # 步骤1: 剥离元数据（EXIF/ICC），减少无用数据
        if hasattr(img, 'info'):
            if 'exif' in img.info:
                img.info['exif'] = b''  # 清空EXIF
            if 'icc_profile' in img.info:
                del img.info['icc_profile']  # 清空ICC

        img = img.convert("RGB")

        # 步骤2: 智能质量调整——上限85，避免过度
        target_quality = min(quality, 85)

        output = io.BytesIO()
        save_kwargs = {
            'format': 'JPEG',
            'quality': target_quality,
            'optimize': True,
            'progressive': True  # 添加渐进式JPEG，提高兼容性和轻微优化
        }
        img.save(output, **save_kwargs)

        # 步骤3: 检查大小，如果变大（>3%）回退原始并发送警告
        output.seek(0)
        compressed_size_temp = len(output.getvalue())
        if compressed_size_temp > original_size * 1.03:
            current_user = getattr(g, 'current_user', '未知')
            logger.warning(
                f"JPEG 压缩后变大 (原始 {round(original_size / 1024 / 1024, 2)} MB -> {round(compressed_size_temp / 1024 / 1024, 2)} MB)，回退到原始文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
            subject = f"图片压缩警告: {filename if filename else '未知'} 变大超过3%"
            orig_mb = round(original_size / (1024 * 1024), 2)
            comp_mb = round(compressed_size_temp / (1024 * 1024), 2)
            body = f"""文件: {filename if filename else '未知'}
用户: {current_user}
IP: {client_ip if client_ip else '未知'}
原始大小: {orig_mb} MB
压缩后大小: {comp_mb} MB
比率: {compressed_size_temp / original_size:.2%}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            send_alert_email(subject, body)
            file_stream.seek(0)
            compressed_output = io.BytesIO(file_stream.read())
            compressed_output.seek(0)
            compressed_size = original_size
        else:
            compressed_output = output
            compressed_size = compressed_size_temp

        logger.info(
            f"JPEG 压缩完成: 原始 {round(original_size / 1024 / 1024, 2)} -> 压缩 {round(compressed_size / 1024 / 1024, 2)} MB (比率: {compressed_size / original_size:.2%})，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
        return compressed_output, "image/jpeg", original_size, compressed_size


@app.route('/login', methods=['POST'])
def login():
    """
    登录接口，生成 Token
    :return: token
    """
    # 改为 JSON 接收
    data = request.get_json()  # 获取 JSON 数据，如果失败则为 None
    if data is None:
        return jsonify({'error': 'Invalid JSON data'}), 400
    username = data.get('username')
    password = data.get('password')
    client_ip = request.remote_addr

    if not username or not password:
        logger.warning(f"登录缺少用户名或密码，客户端IP: {client_ip}")
        return jsonify({"msg": "缺少用户名或密码", 'code': 400}), 400

    if username in USERS and USERS[username] == password:
        token = generate_token(username)
        logger.info(f"用户 {username} 登录成功，客户端IP: {client_ip}")
        return jsonify({"token": token, 'code': 200})
    else:
        logger.warning(f"用户 {username} 登录失败，客户端IP: {client_ip}")
        return jsonify({"msg": "用户名或密码错误", 'code': 401}), 401


@app.route('/compress', methods=['POST'])
@verify_token
def compress():
    """
    单个压缩接口
    """
    client_ip = request.remote_addr
    logger.info(f"收到单个文件压缩请求，用户: {g.current_user}，客户端IP: {client_ip}")
    if 'file' not in request.files:
        logger.warning(f"请求中缺少文件，用户: {g.current_user}，客户端IP: {client_ip}")
        return jsonify({"msg": "请上传文件参数 file", 'code': 500}), 400

    file = request.files['file']
    if file.filename == '':
        logger.warning(f"请求中文件名为空，用户: {g.current_user}，客户端IP: {client_ip}")
        return jsonify({"msg": "文件名为空", 'code': 500}), 400

    quality = int(request.form.get('quality', 80))
    logger.info(f"处理单个文件: {file.filename}，质量: {quality}，用户: {g.current_user}，客户端IP: {client_ip}")
    try:
        compressed_file, mime, orig_size, comp_size = compress_image(file.stream, quality, client_ip=client_ip,
                                                                     filename=file.filename)
        logger.info(
            f"单个文件压缩成功: {file.filename} ({round(orig_size / 1024 / 1024, 2)} -> {round(comp_size / 1024 / 1024, 2)} MB)，用户: {g.current_user}，客户端IP: {client_ip}")
        return send_file(
            compressed_file,
            mimetype=mime,
            as_attachment=True,
            download_name=f"{secure_filename(file.filename)}"
        )
    except Exception as e:
        logger.error(f"单个文件压缩错误 {file.filename}: {str(e)}，用户: {g.current_user}，客户端IP: {client_ip}")
        subject = "图片压缩错误"
        body = f"""文件: {file.filename}
错误: {str(e)}
用户: {g.current_user}
IP: {client_ip}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        send_alert_email(subject, body)
        return jsonify({"msg": str(e), 'code': 500}), 500


if __name__ == '__main__':
    logger.info("启动 Flask 应用")
    # 在后台线程启动 Flask 服务器（避免阻塞主线程）
    threading.Thread(
        target=app.run,
        kwargs={
            'host': '0.0.0.0',
            'port': 5001,
            'debug': True,  # 保持 debug=True，但见下方注意
            'use_reloader': False  # 禁用 reloader，避免 debug 模式下线程冲突
        }
    ).start()