"""Native handout pages and text. This path never invokes image recognition."""
from __future__ import annotations

from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from .common import ROOT, write_json, source_identity

PDF_LOCK=threading.Lock()  # PDFium forbids simultaneous calls, even for different documents.
NS={'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'm':'http://schemas.openxmlformats.org/officeDocument/2006/math'}


def converter():
    office=shutil.which('soffice')
    for folder in ('C:/Program Files','C:/Program Files (x86)'):
        candidate=Path(folder)/'LibreOffice/program/soffice.exe'
        if not office and candidate.is_file():office=str(candidate)
    if office:return ('libreoffice',office)
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,'PowerPoint.Application/CLSID'.replace('/','\\')):
                return ('powerpoint','powershell.exe')
        except OSError:pass
    return None


def local_handout(raw):
    raw=str(raw or '').strip().strip('"')
    path=Path(raw)
    if not path.is_absolute() or raw.startswith(('\\\\','//')) or path.suffix.lower() not in {'.pdf','.pptx','.ppt'} or not path.is_file():
        raise ValueError('请填写存在的本机 PDF、PPTX 或 PPT 完整路径')
    if path.stat().st_size>512*1024**2:raise ValueError('课件文件不能超过512 MiB，请拆分或压缩后导入')
    if path.suffix.lower()!='.pdf' and not converter():
        raise ValueError('渲染PPT需要本机PowerPoint或LibreOffice；也可先另存为PDF后导入')
    return path.resolve()


def omml_latex(node):
    """Preserve common editable Office Math structures; reject unknown structures."""
    tag=node.tag.rsplit('}',1)[-1]
    children=lambda:''.join(omml_latex(c) for c in node)
    part=lambda name:omml_latex(node.find('m:'+name,NS)) if node.find('m:'+name,NS) is not None else ''
    if tag.endswith('Pr') or tag in {'ctrlPr','rPr'}:return ''
    if tag=='t':return (node.text or '').replace('−','-').replace('×',r'\times ').replace('∞',r'\infty ')
    if tag=='f':return r'\frac{'+part('num')+'}{'+part('den')+'}'
    if tag in {'sSup','sSub','sSubSup'}:
        return '{'+part('e')+'}'+('_{'+part('sub')+'}' if tag!='sSup' else '')+('^{'+part('sup')+'}' if tag!='sSub' else '')
    if tag=='rad':return r'\sqrt'+('['+part('deg')+']' if part('deg') else '')+'{'+part('e')+'}'
    if tag=='m':return r'\begin{matrix}'+r'\\'.join('&'.join(omml_latex(c) for c in row.findall('m:e',NS)) for row in node.findall('m:mr',NS))+r'\end{matrix}'
    if tag=='d':
        prop=node.find('m:dPr',NS)
        def val(name,default):
            el=prop.find('m:'+name,NS) if prop is not None else None
            return el.get('{'+NS['m']+'}val',default) if el is not None else default
        left,right=val('begChr','('),val('endChr',')')
        return r'\left'+({'{':r'\{','':'.'}.get(left,left))+children()+r'\right'+({'}':r'\}','':'.'}.get(right,right))
    if tag in {'oMath','oMathPara','r','num','den','e','sub','sup','deg','fName','func'}:return children()
    raise ValueError('不支持的Office公式结构：'+tag)


def pptx_content(path):
    pages=[]
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>512*1024**2:raise ValueError('PPTX展开内容过大')
        presentation=ET.fromstring(z.read('ppt/presentation.xml'))
        rels={r.get('Id'):r.get('Target') for r in ET.fromstring(z.read('ppt/_rels/presentation.xml.rels')) if r.get('TargetMode')!='External'}
        for slide in presentation.findall('p:sldIdLst/p:sldId',NS):
            target=rels.get(slide.get('{'+NS['r']+'}id'),'')
            name=posixpath.normpath('ppt/'+target) if not target.startswith('/') else target.lstrip('/')
            if not name.startswith('ppt/slides/'):raise ValueError('PPTX幻灯片关系无效')
            xml=ET.fromstring(z.read(name))
            texts=[''.join(t.text or '' for t in p.findall('.//a:t',NS)) for p in xml.findall('.//a:p',NS)]
            formulas=[];unreadable=0
            for formula in xml.findall('.//m:oMath',NS):
                try:formulas.append(omml_latex(formula))
                except ValueError:unreadable+=1
            pages.append({'text':'\n'.join(t for t in texts if t.strip()),'formulas':formulas,'unreadable_formulas':unreadable})
    return pages


def render_presentation(path,destination,check):
    engine=converter()
    if not engine:raise ValueError('请安装PowerPoint或LibreOffice，或将课件另存为PDF')
    if engine[0]=='powerpoint':
        command=[engine[1],'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/render-presentation.ps1'),'-Source',str(path),'-Destination',str(destination)]
    else:
        profile=destination.parent/'office-profile'
        command=[engine[1],'-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}','--outdir',str(destination.parent),str(path)]
    with (destination.parent/'conversion.log').open('ab') as log:
        process=subprocess.Popen(command,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+180
            while process.poll() is None:
                check()
                if time.monotonic()>deadline:raise ValueError('PPT转换超时，请先手动另存为PDF后导入')
                time.sleep(.2)
            if process.returncode:raise ValueError('PPT转换未完成，请确认本机Office可用，或另存为PDF后导入')
        finally:
            if process.poll() is None:
                from .runner import terminate_tree
                terminate_tree(process)
    if engine[0]=='libreoffice':
        generated=destination.parent/(path.stem+'.pdf')
        if generated!=destination and generated.is_file():generated.replace(destination)
    if not destination.is_file():raise ValueError('未得到PPT页面，请另存为PDF后导入')


def recognition_reasons(content,image_ratio):
    reasons=[]
    if image_ratio>.015:reasons.append('image_content')
    if content.get('unreadable_formulas'):reasons.append('unsupported_office_math')
    text=content['text']
    if not content['formulas'] and re.search(r'[=∑∫√∞±≠≤≥∂∇∈∉∏∠≈≡α-ωΑ-Ω\u2070-\u209f\U0001d400-\U0001d7ff]|\b(?:sin|cos|tan|log|exp|lim)\s*\(',text):
        reasons.append('formula_structure')
    return reasons


def import_handout(path,output,windows,callback,check,recognize=False):
    import pypdfium2 as pdfium
    path=Path(path);output=Path(output);folder=output/'documents';folder.mkdir(exist_ok=True)
    identity=source_identity(path)
    source=folder/('source'+path.suffix.lower());shutil.copy2(path,source)
    with source.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    native=pptx_content(source) if path.suffix.lower()=='.pptx' else []
    pdf=source if path.suffix.lower()=='.pdf' else folder/'pages.pdf'
    if pdf!=source:render_presentation(source,pdf,check)
    visuals=[];warnings=[]
    with PDF_LOCK,pdfium.PdfDocument(pdf) as document:
        if not 0<len(document)<=500:raise ValueError('课件应为1至500页，请拆分后导入')
        if native and len(native)!=len(document):raise ValueError('PPT原始页数与渲染结果不一致，未使用错位课件')
        for index in range(len(document)):
            check();page=document[index]
            try:
                width,height=page.get_size()
                if min(width,height)<=0 or max(width,height)>20000:raise ValueError('课件页面尺寸无效')
                textpage=page.get_textpage()
                try:text=textpage.get_text_range().replace('\r\n','\n').strip()
                finally:textpage.close()
                content=native[index] if native else {'text':text,'formulas':[],'unreadable_formulas':0}
                image_area=0
                for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]):
                    left,bottom,right,top=obj.get_bounds();image_area+=abs((right-left)*(top-bottom))
                reasons=recognition_reasons(content,image_area/(width*height))
                if recognize=='all':reasons.append('all_pages_requested')
                image=f'images/document-{index+1:04d}.png';(output/'images').mkdir(exist_ok=True)
                bitmap=page.render(scale=min(4,2560/max(width,height)))
                try:bitmap.to_pil().save(output/image)
                finally:bitmap.close()
                flags=[]
                if not content['text'] and not content['formulas']:
                    flags.append('document_image_only');warnings.append(f'课件第{index+1}页没有可直接读取的文字层，已保留原页')
                if content['unreadable_formulas']:
                    flags.append('document_formula_unsupported');warnings.append(f'课件第{index+1}页有无法直接转换的公式，请对照原页')
                vid=f'd{index+1:04d}'
                formulas=[{'id':f'{vid}_f{i+1}','visual_id':vid,'latex':s,'status':'native','source':'office_math'} for i,s in enumerate(content['formulas']) if s.strip()]
                if not (recognize and reasons):write_json(output/'formula_cache'/f'{vid}.json',formulas)
                visuals.append({'id':vid,'kind':'slides','image':image,'start':windows[0][0],'end':windows[-1][1],
                    'capture_ts':windows[0][0],'quad':None,'layout':'document','content_id':vid,'poster_id':vid,
                    'document_page':index+1,'source_document':source.name,'untimed':True,'is_representative':True,
                    'ocr':content['text'],'native_text':content['text'],'native_formulas':formulas,
                    'needs_document_recognition':bool(reasons),'document_recognition_reasons':reasons,
                    'ocr_lines':[],'ocr_model':'native_document','formulas':formulas,'flags':flags})
                callback((index+1)/len(document),f'直接读取课件 {index+1}/{len(document)} · 未调用图像识别')
            finally:page.close()
    if source_identity(path)!=identity:raise ValueError('导入期间课件已改变，请重新创建任务')
    records=[{**v,'page_id':v['content_id'],'representative_id':v['id']} for v in visuals]
    write_json(output/'visuals.json',visuals);write_json(output/'source_records.json',records)
    write_json(output/'layouts.json',[])
    write_json(output/'compaction.json',{'version':'native_document','original_count':len(visuals),'page_count':len(visuals),'all_sources_mapped':True,'retained_count':len(visuals)})
    write_json(output/'handout.json',{'source':identity,'sha256':sha,'pages':len(visuals),'warnings':warnings,'ocr_used':False,'timeline_alignment':'unavailable','pdf_formula_structure':'not_reconstructed' if not native else 'office_math'})
    return visuals


def document_audit(visuals,output):
    report={'source':'native_document','retained_images':len(visuals),'content_groups':len(visuals),'raw_appearances':len(visuals),
        'uncovered_intervals_over_0_6s':[],'region_coverage_gaps_over_0_6s':[],'short_appearances':[],
        'occluded_appearances':[],'timeline_coverage_applicable':False,'semantic_completeness_verified':False,
        'limits':['文档页没有视频时间戳，按原顺序保留；PDF文字层不能保证还原公式结构']}
    write_json(output/'visual_audit.json',report)
    write_json(output/'pages.json',[{'content_id':v['id'],'representative':v['id'],'kind':'slides','document_page':v['document_page'],'appearances':[]} for v in visuals])
    return report


def relevant_pages(text,pages):
    """Text relevance supplies context, never invents a video timestamp."""
    def terms(s):
        tokens=re.findall(r'[a-z0-9]{2,}|[\u4e00-\u9fff]+',s.lower())
        return Counter(t for token in tokens for t in ([token] if token.isascii() else [token[i:i+2] for i in range(len(token)-1)]))
    query=terms(text);documents=[terms(p.get('ocr','')+' '+' '.join(f.get('latex','') for f in p.get('formulas',[]))) for p in pages]
    df=Counter(t for d in documents for t in d)
    scores=[sum(min(query[t],count)*(1+math.log((len(pages)+1)/(df[t]+1))) for t,count in d.items())/math.sqrt(max(1,sum(d.values()))) for d in documents]
    chosen={i for i in sorted(range(len(pages)),key=lambda i:scores[i],reverse=True)[:6] if scores[i]>0}
    return [p for i,p in enumerate(pages) if i in chosen]
