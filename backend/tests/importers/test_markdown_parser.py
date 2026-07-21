from app.importers.markdown_parser import parse_markdown_text


def test_markdown_parser_reads_two_image_prompts() -> None:
    source = """
## 001｜测试题

- 类型：动漫名
- 难度：★★☆☆☆
- 答案字数：3

### 图1生图提示词
图1内容

### 图1题面提示
这是图1

### 图2生图提示词
图2内容

### 图2题面填空
这是 ＿ ＿ ＿

### 答案
测试题

### 数字声调拼音
ce4 shi4 ti2

### 谜底拆解
拆解内容
"""

    preview = parse_markdown_text(source)

    assert len(preview.questions) == 1
    assert preview.questions[0].image1_prompt == "图1内容"
    assert preview.questions[0].image2_prompt == "图2内容"
    assert preview.error_count == 0

