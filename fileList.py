from flask import Flask, render_template_string, send_from_directory, abort
import os
import argparse

# 解析命令行参数
parser = argparse.ArgumentParser(description='Flask 文件浏览器')
parser.add_argument('--dir', type=str, default=os.getcwd(), help='指定根目录路径（默认：当前目录）')
args = parser.parse_args()

app = Flask(__name__)
BASE_DIR = os.path.abspath("E:\\openvpn分配")  # 使用绝对路径

# 检查目录是否存在
if not os.path.exists(BASE_DIR):
    raise ValueError(f"指定的目录不存在: {BASE_DIR}")

# HTML 模板，用于显示目录内容
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>文件浏览器</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        ul { list-style-type: none; padding: 0; }
        li { margin: 5px 0; }
        a { text-decoration: none; color: blue; }
        .dir { font-weight: bold; color: green; }
        .file { color: black; }
    </style>
</head>
<body>
    <h1>文件浏览器: {{ current_path }}</h1>
    <ul>
        {% if parent_path %}
        <li><a href="{{ parent_path }}">.. (返回上级)</a></li>
        {% endif %}
        {% for item in items %}
            {% if item.is_dir %}
                <li class="dir"><a href="{{ item.url }}">{{ item.name }}/</a></li>
            {% else %}
                <li class="file"><a href="{{ item.url }}" download>{{ item.name }}</a></li>
            {% endif %}
        {% endfor %}
    </ul>
</body>
</html>
'''

@app.route('/')
@app.route('/browse/<path:directory>')
def browse(directory=''):
    # 构建完整路径
    full_path = os.path.join(BASE_DIR, directory)
    if not os.path.exists(full_path):
        abort(404)

    # 确保路径在BASE_DIR内，避免目录遍历攻击
    if not full_path.startswith(os.path.abspath(BASE_DIR)):
        abort(403)

    # 获取目录内容
    items = []
    parent_path = None
    if directory != '':
        parent_dir = os.path.dirname(directory)
        if parent_dir:
            parent_path = f'/browse/{parent_dir}'

    try:
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            is_dir = os.path.isdir(item_path)
            url = f'/browse/{os.path.join(directory, item)}' if is_dir else f'/download/{os.path.join(directory, item)}'
            items.append({'name': item, 'url': url, 'is_dir': is_dir})
    except PermissionError:
        abort(403)

    current_path = os.path.abspath(full_path)
    return render_template_string(HTML_TEMPLATE, items=items, current_path=current_path, parent_path=parent_path)

@app.route('/download/<path:filename>')
def download(filename):
    full_path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(full_path):
        abort(404)

    # 确保路径在BASE_DIR内
    if not full_path.startswith(os.path.abspath(BASE_DIR)):
        abort(403)

    return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path), as_attachment=True)

if __name__ == '__main__':
    print(f"根目录设置为: {BASE_DIR}")
    app.run(debug=True, host='0.0.0.0', port=5001)