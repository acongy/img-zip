from flask import Flask, request, send_file, render_template, jsonify
from PIL import Image
import io
import subprocess
import platform
import os

app = Flask(__name__)


def get_pngquant_path():
    """根据系统返回 pngquant 可执行文件路径"""
    system = platform.system().lower()
    if system.startswith("win"):  # Windows
        return os.path.join("pngquant-linux", "pngquant.exe")
    else:  # Linux
        return os.path.join("pngquant-win", "pngquant")


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
    压缩图片：
    - JPEG: 有损压缩
    - PNG: 无损压缩 + 可选 pngquant 有损压缩
    """
    img = Image.open(file_stream)

    if img.format == "PNG":
        img = img.convert("RGBA")
        output = io.BytesIO()
        img.save(output, format="PNG", optimize=True, compress_level=9)
        output_bytes = output.getvalue()
        if use_pngquant:
            compressed_output = compress_png_with_pngquant(output_bytes, quality)
        else:
            compressed_output = io.BytesIO(output_bytes)
        compressed_output.seek(0)
        return compressed_output, "image/png"
    else:
        # JPEG 压缩
        img = img.convert("RGB")
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        output.seek(0)
        return output, "image/jpeg"


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
        compressed_file, mime = compress_image(file.stream, quality)
        return send_file(
            compressed_file,
            mimetype=mime,
            as_attachment=True,
            download_name=f"{file.filename}"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)