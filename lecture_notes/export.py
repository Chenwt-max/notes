from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from .common import ROOT, stamp, read_json,write_json,math_markdown
from .note_content import clean_note


def source_caption(visual):
    if visual.get('document_page'):return f'原课件第{visual["document_page"]}页（无视频时间戳）'
    if 'start' not in visual or 'end' not in visual:return f'截图 {visual["capture_ts"]:.3f}秒'
    return f'{stamp(visual["start"])}—{stamp(visual["end"])} · 截图 {visual["capture_ts"]:.3f}秒'


def export_notes(title, sections, segments, visuals, output, warnings=None):
    sections=[clean_note(s) for s in sections]
    output = Path(output)
    write_json(output/'note_repairs.json',{'status':'ai_suggested','originals_preserved':True,
        'sections':[{'id':s['id'],'time':s['title'],'repairs':s.get('repairs',[]),
            'editorial_notes':s.get('editorial_notes',[]),'deferred_formula_ids':s.get('deferred_formula_ids',[])} for s in sections if s.get('repairs') or s.get('editorial_notes') or s.get('deferred_formula_ids')]})
    checks=read_json(output/'quality.json',{}).get('formulas',{}).get('syntax',{})
    invalid={f['id'] for f in checks.get('errors',[])}
    disagreements={f['id'] for f in read_json(output/'quality.json',{}).get('formulas',{}).get('disagreements',[])}
    mapping = {v['id']:v for v in visuals}
    by_segment = {s['id']:s for s in segments}
    lines = [f'# {title}', '', f'生成状态：{"已整理" if sections and all(s["organized"] for s in sections) else "本地图文讲义 / 含待整理章节"}', '']
    for warning in warnings or []:
        lines += [f'> {warning}', '']
    lines += ['[查看全部课件识别文字（本地原始识别）](ocr.txt)',
              '[核对画面分组与所有出现记录](visuals.html)','']
    for section in sections:
        if section.get('omitted'):continue
        if section.get('publication_pending'):
            lines += [f'## {section["title"]}', '', '> 本章整理与复核完成后发布。', '']
            continue
        if not section.get('organized') or not section.get('body'):
            lines += [f'## {section["title"]}', '']
        if section.get('body'):
            lines += [math_markdown(section['body']), '']
        else:
            for sid in section['segment_ids']:
                item = by_segment[sid]
                lines += [f'**[{stamp(item["start"])}]** {item["text"]}', '']
        if section.get('warning'):
            lines += ['> '+section['warning'], '']
        if section.get('organized') and section.get('body'):
            ids=section.get('display_visual_ids',section['visual_ids'])
            anchor=mapping[ids[0]]['content_id'] if ids else ''
            lines += [f'[查看课件来源](visuals.html#{anchor}) · [原始字幕](transcript.txt) · [识别修订记录](note_repairs.json)','']
            continue
        if section.get('repairs'):
            lines += ['### 整理时的识别修订', '', '> 以下为 AI 修订，原始字幕和公式候选保持原样。', '']
            for row in section['repairs']:
                lines += [f"- {row['source']}：{row['before']} → {row['after']}（{row['reason']}）",'']
        if section.get('deferred_formula_ids'):
            lines += [f"> 另有 {len(section['deferred_formula_ids'])} 处公式疑点未附图修复，请在核验页对照原图。",'']
        seen = set()
        local_visuals = [mapping[vid] for vid in section.get('display_visual_ids',section['visual_ids'])]
        for vid in section.get('display_visual_ids',section['visual_ids']):
            visual = mapping[vid]
            if visual['content_id'] in seen:
                continue
            seen.add(visual['content_id'])
            visual = max((v for v in local_visuals if v['content_id']==visual['content_id']),
                         key=lambda x:(x.get('is_representative',True),x.get('quality_score',0)))
            kind = {'slides':'课件','board':'板书','screen':'整屏画面'}.get(visual['kind'],'画面')
            lines += [f'### {kind} · {source_caption(visual)}', '',
                      f'![{kind}]({visual["image"]})', '',
                      source_caption(visual), '']
            supplements=[v for v in visuals if v['content_id']==visual['content_id'] and not v.get('is_representative',True)]
            if supplements:lines += [f'[查看本组的{len(supplements)}幅补充或待核对状态](visuals.html#{visual["content_id"]})','']
            for formula in visual.get('formulas',[]):
                if formula.get('id') in disagreements:
                    lines += ['> 此公式与同一位置的文字识别存在分歧，请对照上方课件原图；未自动选用任一候选。','']
                    continue
                if formula.get('id') in invalid or not checks.get('available',False):
                    lines += ['> 此公式候选未通过渲染检查，请对照上方课件原图；未自动补写或替换。','']
                    continue
                lines += ['$$',formula.get('corrected_latex',formula['latex']),'$$','',
                          f'公式状态：{"已保存修订" if formula.get("corrected_latex") else "识别候选，请对照原图"}。','']
    markdown = '\n'.join(lines)
    (output/'notes.md').write_text(markdown, encoding='utf-8')
    ocr_lines=['课件与板书识别文字（本地识别，须对照原图核查）','']
    for visual in visuals:
        ocr_lines += [f"[{source_caption(visual)}] {visual['id']} · {visual['image']}",visual.get('ocr',''),'']
    (output/'ocr.txt').write_text('\n'.join(ocr_lines),encoding='utf-8')
    export_visual_index(visuals,output)
    assets = output/'assets'
    assets.mkdir(exist_ok=True)
    modules = ROOT/'frontend/node_modules'
    for source, name in [(modules/'markdown-it/dist/markdown-it.min.js','markdown-it.min.js'),
                          (modules/'katex/dist','katex')]:
        if source.is_dir():
            shutil.copytree(source,assets/name,dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source,assets/name)
    payload = json.dumps(markdown, ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e')
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><link rel="stylesheet" href="assets/katex/katex.min.css"><style>
body{margin:0;background:#f5f5f7;color:#1d1d1f;font:22px/1.95 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}main{max-width:920px;margin:48px auto;padding:52px;background:white;border-radius:28px;letter-spacing:.025em}h1{font-size:44px}h2{margin-top:48px;padding-top:20px;border-top:1px solid #e1e1e6}h3{font-size:24px}img{max-width:100%;height:auto;border:1px solid #e1e1e6;border-radius:8px}blockquote{border-left:3px solid #0071e3;padding:8px 18px;background:#f0f6ff}pre{overflow:auto;background:#f5f5f7;padding:18px}.katex-display{overflow:auto}a{color:#0071e3}header{font-size:17px;color:#6e6e73}@media(max-width:700px){main{margin:0;padding:20px;border-radius:0}}
</style><main><header>课间 · 学习笔记</header><article id="notes"></article></main>
<script id="source" type="application/json">__PAYLOAD__</script><script src="assets/markdown-it.min.js"></script><script src="assets/katex/katex.min.js"></script><script src="assets/katex/contrib/auto-render.min.js"></script>
<script>
const source=JSON.parse(document.getElementById('source').textContent),node=document.getElementById('notes'),math=[];
const protectedSource=source.replace(/```[\\s\\S]*?```|~~~[\\s\\S]*?~~~|`[^`\\n]*`|\\$\\$([\\s\\S]*?)\\$\\$|(?<!\\$)\\$(?!\\$)([^\\n]+?)\\$(?!\\$)/g,(whole,block,inline)=>{if(block===undefined&&inline===undefined)return whole;const id=math.push({latex:block??inline,display:block!==undefined})-1;return 'LNFORMULA'+id+'PLACEHOLDER'});
if(window.markdownit){node.innerHTML=markdownit({html:false,breaks:true}).render(protectedSource);node.innerHTML=node.innerHTML.replace(/LNFORMULA(\\d+)PLACEHOLDER/g,(_,i)=>{const item=math[Number(i)];if(window.katex)return katex.renderToString(item.latex,{displayMode:item.display,throwOnError:false,trust:false});const span=document.createElement('span');span.textContent=item.latex;return span.outerHTML})}else{node.textContent=source;node.style.whiteSpace='pre-wrap'}
</script></html>'''
    (output/'notes.html').write_text(page.replace('__TITLE__',html.escape(title)).replace('__PAYLOAD__',payload),encoding='utf-8')
    return markdown


def export_visual_index(visuals,output):
    groups = {}
    for visual in sorted(visuals,key=lambda v:v['capture_ts']):
        groups.setdefault(visual['content_id'],[]).append(visual)
    cards = []
    for key,items in groups.items():
        best = max(items,key=lambda x:(x.get('is_representative',True),x.get('quality_score',0)))
        kind = {'slides':'课件','board':'板书','screen':'整屏画面'}.get(best['kind'],'画面')
        entries = ''.join(f'<figure><a href="{html.escape(v.get("hd_image",v["image"]))}"><img loading="lazy" src="{html.escape(v.get("hd_image",v["image"]))}"></a>'
                          f'<figcaption>{v["id"]} · {source_caption(v)}</figcaption></figure>'
                          for v in items)
        cards.append(f'<article id="{key}"><h2>{source_caption(best) if best.get("document_page") else f"{key} · {kind} · {len(items)}幅互补或待核对状态"}</h2><img loading="lazy" src="{html.escape(best.get("hd_image",best["image"]))}">'
                     f'<details><summary>展开补充状态及时间</summary><div class="grid">{entries}</div></details></article>')
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>画面核对索引</title><style>body{max-width:1100px;margin:30px auto;padding:20px;font:19px/1.9 "Microsoft YaHei",sans-serif;background:#f5f5f7;color:#1d1d1f;letter-spacing:.025em}'
            'article{padding:20px;margin:20px 0;background:white;border:1px solid #e1e1e6;border-radius:24px}h2{font-size:23px}img{max-width:100%;max-height:420px}summary{cursor:pointer;padding:12px;color:#0071e3}'
            '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}figure{margin:10px 0}figcaption{font-size:17px;color:#6e6e73}</style>'
            f'<h1>画面核对索引</h1><p>{len(groups)}组代表画面，含{len(visuals)}幅代表及补充原图。重复位图已精简，全部原始时刻见source_records.json，可在本地程序按需恢复。'
            '短于0.5秒的内容、持续遮挡及识别错误仍需对照原视频。</p><p><a href="notes.html">返回图文讲义</a></p>'+''.join(cards)+'</html>')
    (Path(output)/'visuals.html').write_text(page,encoding='utf-8')
