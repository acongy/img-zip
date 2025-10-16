from flask import Flask, request, send_file, render_template, jsonify
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

app = Flask(__name__)


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
        process = subprocess.Popen(
            [pngquant_path, f'--quality={min_q}-{max_q}', '--speed', '1', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        out, err = process.communicate(input=input_bytes)
        if process.returncode == 0 and out:
            return io.BytesIO(out)
        else:
            # 如果 pngquant 出错，返回原始数据
            return io.BytesIO(input_bytes)
    except Exception:
        return io.BytesIO(input_bytes)


def compress_image(file_stream, quality=80, use_pngquant=True):
    """
    压缩图片（优化版）：
    - GIF: 不处理
    - JPEG: 有损压缩
    - PNG: 优先保留 Indexed 模式，无损优化；仅在 pngquant 时转为 RGBA
    返回 (compressed_io, mime_type, original_size, compressed_size)
    """
    original_size = len(file_stream.read())
    file_stream.seek(0)
    img = Image.open(file_stream)

    if img.format == "GIF":
        file_stream.seek(0)
        compressed_output = io.BytesIO(file_stream.read())
        compressed_output.seek(0)
        return compressed_output, "image/gif", original_size, original_size
    elif img.format == "PNG":
        # 先尝试无损优化，保留原模式
        output = io.BytesIO()
        save_kwargs = {"format": "PNG", "optimize": True, "compress_level": 9}

        if use_pngquant:
            # pngquant 需要 RGBA
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img.save(output, **save_kwargs)
            output_bytes = output.getvalue()
            compressed_output = compress_png_with_pngquant(output_bytes, quality)  # 假设此函数存在
        else:
            # 无 pngquant 时，保留原模式（Indexed 优先）
            if img.mode == "P" and img.palette is not None:
                # 确保 Indexed 模式下有调色板
                save_kwargs["palette"] = img.palette
            img.save(output, **save_kwargs)
            compressed_output = output

        compressed_output.seek(0)
        compressed_size = len(compressed_output.read())
        compressed_output.seek(0)
        return compressed_output, "image/png", original_size, compressed_size
    else:
        # JPEG 压缩（不变）
        img = img.convert("RGB")
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        output.seek(0)
        compressed_size = len(output.getvalue())
        return output, "image/jpeg", original_size, compressed_size

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/compress', methods=['POST'])
def compress():
    if 'file' not in request.files:
        return jsonify({"error": "请上传文件参数 file"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "文件名为空"}), 400

    quality = int(request.form.get('quality', 80))

    try:
        compressed_file, mime, orig_size, comp_size = compress_image(file.stream, quality)
        return send_file(
            compressed_file,
            mimetype=mime,
            as_attachment=True,
            download_name=f"{secure_filename(file.filename)}"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/index2.html')
def index2():
    return render_template('index2.html')


@app.route('/compress2', methods=['POST'])
def compress2():
    quality = int(request.form.get('quality', 80))
    is_batch = request.form.get('is_batch', 'false').lower() == 'true'
    files = request.files.getlist('file')

    if not files or (not is_batch and len(files) != 1):
        return jsonify({"error": "请上传文件参数 file (单个或批量)"}), 400

    try:
        if not is_batch or len(files) == 1:
            # 单文件处理
            file = files[0]
            if file.filename == '':
                return jsonify({"error": "文件名为空"}), 400

            compressed_file, mime, orig_size, comp_size = compress_image(file.stream, quality)
            response = send_file(
                compressed_file,
                mimetype=mime,
                as_attachment=True,
                download_name=f"{secure_filename(file.filename)}"
            )
            # 对于单文件，也设置头（可选）
            response.headers['X-File-Sizes'] = json.dumps({file.filename: comp_size})
            return response
        else:
            # 批量处理：创建ZIP
            zip_buffer = io.BytesIO()
            file_sizes = {}  # {original_filename: comp_size}
            total_orig_size = 0
            total_comp_size = 0
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file in files:
                    if file.filename == '':
                        continue
                    # 读取文件内容到BytesIO
                    file_bytes = file.read()
                    file_stream = io.BytesIO(file_bytes)
                    compressed_file, mime, orig_size, comp_size = compress_image(file_stream, quality)
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
            return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
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
    webbrowser.open('http://127.0.0.1:5000')  # 或你的首页路由，如 '/home'