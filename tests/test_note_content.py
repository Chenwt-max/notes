import json
import pytest
from pathlib import Path
from lecture_notes.note_content import separate_editorial,clean_note,unwrapped_math


@pytest.mark.parametrize('body',[
    r'拟合向量 X\hat w 是列空间投影。',
    r'答案是 \frac{1}{2}。',
])
def test_naked_latex_is_detected(body):
    assert unwrapped_math(body)


@pytest.mark.parametrize('body',[
    r'拟合向量 $X\hat w$ 是列空间投影。',
    r'拟合向量 \(X\hat w\) 是列空间投影。',
    r'公式：\[\frac{1}{2}\]',
    r'命令写法 `\hat w`。',
    '```latex\n\\frac{1}{2}\n```',
    r'文件 C:\Users\student\video.mp4。',
])
def test_existing_math_code_and_paths_are_preserved(body):
    assert not unwrapped_math(body)


def test_correction_list_moves_out_of_notes_without_changing_knowledge():
    knowledge='## 最小二乘\n\n令 $Xw=t$，最小化残差平方和。'
    editorial='> 注：字幕中“自由二乘”应为“最小二乘”，“使命网络”应为“神经网络”。'
    body,items=separate_editorial(knowledge+'\n\n'+editorial)
    assert body==knowledge and items==[editorial]
    result=clean_note({'body':knowledge+'\n\n'+editorial})
    assert result['body']==knowledge and result['body_before_cleanup'].endswith(editorial)
    assert result['editorial_notes']==[editorial]


def test_substantive_notes_and_code_are_preserved():
    body='## 定义\n\n注：矩阵应为满列秩。\n\n```text\n注：字幕识别错字应为例子\n```'
    assert separate_editorial(body)==(body,[])


def test_inline_source_format_diagnostic_moves_to_metadata():
    diagnostic='（原图 v00002_f1 中范数符号误排，应为双竖线范数。）'
    body='## 范数\n\n\\[L(w)=\\|Xw-y\\|^2\\]\n'+diagnostic+'\n平方误差同时惩罚正负偏差。'
    cleaned,items=separate_editorial(body)
    assert cleaned=='## 范数\n\n\\[L(w)=\\|Xw-y\\|^2\\]\n平方误差同时惩罚正负偏差。'
    assert items==[diagnostic]


def test_source_diagnostic_inside_code_is_preserved():
    body='```text\n（原图 v00002_f1 误排，应为双竖线。）\n```'
    assert separate_editorial(body)==(body,[])


def test_mathematical_comment_and_unlabelled_source_reference_are_kept():
    body='## 范数\n\n（原图中给出了反例，应为列满秩。）\n\n（原图 v00002_f1 中的范数用于定义误差。）'
    assert separate_editorial(body)==(body,[])


def test_editorial_only_completed_segment_does_not_fall_back_to_raw_subtitles():
    result=clean_note({'organized':True,'body':'本时段以设备调试为主，没有出现知识内容。'})
    assert result['omitted'] and result['body']=='' and result['editorial_notes']
    pending=clean_note({'organized':False,'body':''})
    assert not pending.get('omitted')


def test_editorial_heading_does_not_consume_next_knowledge_section():
    body='## 主题\n\n### 字幕纠错\n\n一些修订说明\n\n### 定义\n\n定义正文'
    text,items=separate_editorial(body)
    assert text=='## 主题\n\n### 定义\n\n定义正文'
    assert items==['### 字幕纠错','一些修订说明']


def test_offline_quotes_have_attribution_and_are_unique():
    rows=json.loads((Path(__file__).parents[1]/'frontend/src/data/quotes.json').read_text(encoding='utf-8'))
    assert len(rows)>=300 and len({q['text'] for q in rows})==len(rows)
    assert all(q['author'] and q['source'] and 8<=len(q['text'])<=72 for q in rows)
