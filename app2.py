from flask import Flask, request, send_file, render_template, jsonify, g, current_app
from PIL import Image
import io
import subprocess
import platform
import os
import zipfile
import json
from werkzeug.utils import secure_filename
import webbrowser
import threading
import logging
from logging.handlers import TimedRotatingFileHandler
import uuid
import time


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

handler_file = TimedRotatingFileHandler(
    'app.log',
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
    print("system:{}", system)
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
    - JPEG: 有损压缩
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
            f"检测到 PNG (模式: {img.mode})，原始大小: {original_size} 字节，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
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
            f"PNG 压缩完成: 原始 {original_size} -> 压缩 {compressed_size} 字节 (比率: {compressed_size / original_size:.2%})，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
        return compressed_output, "image/png", original_size, compressed_size
    else:
        # JPEG 压缩（不变）
        logger.info(
            f"检测到 JPEG，原始大小: {original_size} 字节，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
        img = img.convert("RGB")
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        output.seek(0)
        compressed_size = len(output.getvalue())
        logger.info(
            f"JPEG 压缩完成: 原始 {original_size} -> 压缩 {compressed_size} 字节 (比率: {compressed_size / original_size:.2%})，文件: {filename if filename else '未知'}，客户端IP: {client_ip if client_ip else '未知'}")
        return output, "image/jpeg", original_size, compressed_size


@app.route('/')
def index():
    client_ip = request.remote_addr
    logger.info(f"提供 index.html，客户端IP: {client_ip}")
    return render_template('index.html')


@app.route('/index2.html')
def index2():
    client_ip = request.remote_addr
    logger.info(f"提供 index2.html，客户端IP: {client_ip}")
    return render_template('index2.html')


@app.route('/compress', methods=['POST'])
def compress():
    client_ip = request.remote_addr
    logger.info(f"收到单个文件压缩请求，客户端IP: {client_ip}")
    if 'file' not in request.files:
        logger.warning(f"请求中缺少文件，客户端IP: {client_ip}")
        return jsonify({"error": "请上传文件参数 file"}), 400

    file = request.files['file']
    if file.filename == '':
        logger.warning(f"请求中文件名为空，客户端IP: {client_ip}")
        return jsonify({"error": "文件名为空"}), 400

    quality = int(request.form.get('quality', 80))
    logger.info(f"处理单个文件: {file.filename}，质量: {quality}，客户端IP: {client_ip}")

    try:
        compressed_file, mime, orig_size, comp_size = compress_image(file.stream, quality, client_ip=client_ip,
                                                                     filename=file.filename)
        logger.info(f"单个文件压缩成功: {file.filename} ({orig_size} -> {comp_size} 字节)，客户端IP: {client_ip}")
        return send_file(
            compressed_file,
            mimetype=mime,
            as_attachment=True,
            download_name=f"{secure_filename(file.filename)}"
        )
    except Exception as e:
        logger.error(f"单个文件压缩错误 {file.filename}: {str(e)}，客户端IP: {client_ip}")
        return jsonify({"error": str(e)}), 500


@app.route('/compress2', methods=['POST'])
def compress2():
    client_ip = request.remote_addr
    logger.info(f"收到批量/单个文件压缩请求，客户端IP: {client_ip}")
    quality = int(request.form.get('quality', 80))
    is_batch = request.form.get('is_batch', 'false').lower() == 'true'
    files = request.files.getlist('file')

    if not files or (not is_batch and len(files) != 1):
        logger.warning(f"请求中文件无效，客户端IP: {client_ip}")
        return jsonify({"error": "请上传文件参数 file (单个或批量)"}), 400

    try:
        if not is_batch or len(files) == 1:
            # 单文件处理
            logger.info(f"在批量模式下处理单个文件，客户端IP: {client_ip}")
            file = files[0]
            if file.filename == '':
                logger.warning(f"批量单个文件为空文件名，客户端IP: {client_ip}")
                return jsonify({"error": "文件名为空"}), 400

            compressed_file, mime, orig_size, comp_size = compress_image(file.stream, quality, client_ip=client_ip,
                                                                         filename=file.filename)
            response = send_file(
                compressed_file,
                mimetype=mime,
                as_attachment=True,
                download_name=f"{secure_filename(file.filename)}"
            )
            # 对于单文件，也设置头（可选）
            response.headers['X-File-Sizes'] = json.dumps({file.filename: comp_size})
            logger.info(
                f"批量单个文件压缩成功: {file.filename} ({orig_size} -> {comp_size} 字节)，客户端IP: {client_ip}")
            return response
        else:
            # 批量处理：创建ZIP
            logger.info(f"开始批量压缩 {len(files)} 个文件，质量: {quality}，客户端IP: {client_ip}")
            zip_buffer = io.BytesIO()
            file_sizes = {}  # {original_filename: comp_size}
            total_orig_size = 0
            total_comp_size = 0
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file in files:
                    if file.filename == '':
                        logger.warning(f"批量中跳过空文件名: {file.filename}，客户端IP: {client_ip}")
                        continue
                    # 读取文件内容到BytesIO
                    file_bytes = file.read()
                    file_stream = io.BytesIO(file_bytes)
                    compressed_file, mime, orig_size, comp_size = compress_image(file_stream, quality,
                                                                                 client_ip=client_ip,
                                                                                 filename=file.filename)
                    # 获取相对路径
                    rel_path = getattr(file, 'webkitRelativePath', file.filename)
                    if not rel_path:
                        rel_path = secure_filename(file.filename)
                    # 保持原后缀
                    base_name, orig_ext = os.path.splitext(rel_path)
                    comp_filename = base_name + orig_ext
                    zip_file.writestr(comp_filename, compressed_file.getvalue())
                    file_sizes[file.filename] = comp_size  # 用原文件名作为key，前端匹配
                    total_orig_size += orig_size
                    total_comp_size += comp_size
                    logger.info(
                        f"批量文件处理: {file.filename} ({orig_size} -> {comp_size} 字节)，客户端IP: {client_ip}")

            zip_buffer.seek(0)
            response = send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name='compressed_images.zip'
            )
            # 设置响应头返回大小信息
            response.headers['X-Original-Total'] = str(total_orig_size)
            response.headers['X-Compressed-Total'] = str(total_comp_size)
            response.headers['X-File-Sizes'] = json.dumps(file_sizes)
            logger.info(
                f"批量压缩完成: 总原始 {total_orig_size} -> 总压缩 {total_comp_size} 字节 (比率: {total_comp_size / total_orig_size:.2%})，客户端IP: {client_ip}")
            return response
    except Exception as e:
        logger.error(f"批量/单个压缩错误: {str(e)}，客户端IP: {client_ip}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    logger.info("启动 Flask 应用")
    # 在后台线程启动 Flask 服务器（避免阻塞主线程）
    threading.Thread(
        target=app.run,
        kwargs={
            'host': '0.0.0.0',
            'port': 5000,
            'debug': True,  # 保持 debug=True，但见下方注意
            'use_reloader': False  # 禁用 reloader，避免 debug 模式下线程冲突
        }
    ).start()

    # 主线程立即打开浏览器
    webbrowser.open('http://127.0.0.1:5000')
    logger.info("浏览器已打开到 http://127.0.0.1:5000")