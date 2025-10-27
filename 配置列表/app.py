import pandas as pd

def process_excel():
    # 步骤 1：从 input.xlsx 读取数据
    input_file = 'input.xlsx'
    try:
        df_input = pd.read_excel(input_file, engine='openpyxl', header=None)
        if df_input.shape[1] != 4:
            print("错误：input.xlsx 必须包含4列数据！")
            exit(1)
        raw_data = df_input.dropna().values.tolist()
        if not raw_data:
            print("错误：input.xlsx 文件为空或数据无效！")
            exit(1)
    except FileNotFoundError:
        print(f"错误：找不到文件 {input_file}！")
        exit(1)
    except Exception as e:
        print(f"读取 input.xlsx 出错：{e}")
        exit(1)

    # 步骤 2：创建三行格式（zh-cn, zh-tw, en-us）
    values1, values2, values3, values4, languages = [], [], [], [], []
    for row in raw_data:
        v1, v2, v3, v4 = row
        # zh-cn 行：Value1 和 Value4 有值，Value2 和 Value3 为空
        values1.extend([v1, '', ''])
        values2.extend([v2, v2, v2])
        values3.extend([v3, v3, v3])
        values4.extend([v4, '', ''])
        languages.extend(['zh-cn', 'zh-tw', 'en-us'])

    # 创建 DataFrame
    df_output = pd.DataFrame({
        'Value1': values1,
        'Value2': values2,
        'Value3': values3,
        'Value4': values4,
        'Language': languages
    })

    # 步骤 3：生成 output.xlsx
    output_file = 'output.xlsx'
    try:
        df_output.to_excel(output_file, index=False, engine='openpyxl')
        print(f"Excel 文件已生成：{output_file}")
    except Exception as e:
        print(f"生成 output.xlsx 出错：{e}")
        exit(1)

    # 步骤 4：读取并打印 output.xlsx
    try:
        df_read = pd.read_excel(output_file, engine='openpyxl')
        print("\n从 output.xlsx 读取的内容：")
        print(df_read.to_string(index=False))
    except Exception as e:
        print(f"读取 output.xlsx 出错：{e}")
        exit(1)

if __name__ == '__main__':
    process_excel()