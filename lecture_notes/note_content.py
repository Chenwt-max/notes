"""Keep editorial diagnostics out of the learning text, preserving them as metadata."""
from __future__ import annotations
import re
from .common import math_markdown


def unwrapped_math(body):
    text=math_markdown(body)
    text=re.sub(r'```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`','',text)
    text=re.sub(r'\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\$)[^\n]+?(?<!\\)\$(?!\$)','',text)
    return bool(re.search(r'(?<!\\)\\(?:hat|widehat|frac|dfrac|sqrt|mathbb|mathbf|mathsf|operatorname|begin|alpha|beta|gamma|theta|lambda|sigma|nabla|sum|int|cdot|times)\b',text))


def separate_editorial(body):
    kept,editorial=[],[]
    in_code=False
    editorial_level=None
    for block in re.split(r'\n\s*\n',body):
        fences=re.findall(r'^\s*(```|~~~)',block,re.M)
        protected=in_code or bool(fences)
        if len(fences)%2:in_code=not in_code
        if not protected:
            lines=[]
            for line in block.splitlines():
                if re.fullmatch(r'[（(](?:原图|原始字幕|识别结果)\s*[vs]\d+(?:_f\d+)?\b.*(?:误排|识别错误|应为|修正).*[）)]',line.strip()):
                    editorial.append(line.strip())
                else:lines.append(line)
            block='\n'.join(lines)
            if not block.strip():continue
        heading=re.match(r'^(#{1,6})\s+(.+)',block)
        if heading and editorial_level and len(heading[1])<=editorial_level:editorial_level=None
        text=re.sub(r'^>\s?','',block,flags=re.M).strip()
        heading_is_editorial=bool(heading and re.fullmatch(r'(?:字幕纠错|识别修订|转写说明|整理说明|术语[与和]?纠错)(?:记录)?',heading[2].strip()))
        correction=bool(re.match(r'^(?:注[：:]|说明[：:]|字幕纠错[：:]).*(?:字幕|转写|识别).*(?:应为|应作|误|修正|校正|错)',text,re.S))
        process=bool(re.match(r'^[（(]?(?:本时段|本段|本章节|这一时段).*(?:未出现|没有).*(?:定义|推导|知识|内容)',text,re.S))
        if not protected and (heading_is_editorial or editorial_level or correction or process):
            if heading_is_editorial:editorial_level=len(heading[1])
            editorial.append(block.strip())
        else:kept.append(block)
    return '\n\n'.join(kept).strip(),editorial


def clean_note(section):
    note=dict(section)
    if note.get('publication_pending'):
        note['body']=''
        note['organized']=False
        note['warning']='本章整理与复核完成后发布。'
        return note
    body,editorial=separate_editorial(note.get('body',''))
    if editorial:
        note.setdefault('body_before_cleanup',note.get('body',''))
        note['body']=body
        note['editorial_notes']=list(dict.fromkeys([*note.get('editorial_notes',[]),*editorial]))
        if note.get('organized') and not body.strip():note['omitted']=True
    return note
