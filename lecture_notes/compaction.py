"""Keep original pages which directly cover the visible information of discarded views.

No inpainting, no chained similarity, and no deletion here. Every original time/quad
is kept separately so a discarded bitmap can be recovered from the source video.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from difflib import SequenceMatcher
from pathlib import Path
import time
import unicodedata

import cv2
import numpy as np

from .common import read_json,write_json

VERSION=2
GROUP_VERSION=4


def text_agrees(a,b):
    """OCR is additional grouping evidence, never permission to delete a source."""
    def normalized(v):
        return ''.join(c for c in unicodedata.normalize('NFKC',v.get('ocr','')).lower() if c.isalnum())
    aa,bb=normalized(a),normalized(b)
    return min(len(aa),len(bb))>=32 and SequenceMatcher(None,aa,bb,autojunk=False).ratio()>=.85


def glyph_changed(a,b):
    delta=np.abs(a['gray'].astype(np.float32)-b['gray']-a['median']+b['median'])
    added=b['edge']&~a['edge']&(delta>35)&~(a['mask']|b['mask'])
    if added.sum()<3:return False
    _,labels,stats,_=cv2.connectedComponentsWithStats(np.uint8(b['edge']))
    ids,counts=np.unique(labels[added],return_counts=True)
    for index,count in zip(ids,counts):
        if index==0 or count<3:continue
        x,y,w,h,area=stats[index]
        if w<=60 and h<=60 and np.count_nonzero((labels[y:y+h,x:x+w]==index)&a['edge'][y:y+h,x:x+w])>=2:
            return True
    return False


def features(image,mask=None):
    gray=cv2.cvtColor(cv2.resize(image,(640,400)),cv2.COLOR_BGR2GRAY)
    masked=np.zeros_like(gray,dtype=bool) if mask is None else cv2.resize(mask,(640,400),interpolation=cv2.INTER_NEAREST)>0
    masked=cv2.dilate(np.uint8(masked),np.ones((3,3),np.uint8))>0
    edge=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,7)>0
    edge[masked]=False
    edge[:4]=edge[-4:]=False;edge[:,:4]=edge[:,-4:]=False
    hash_image=gray.copy();hash_image[masked]=np.median(gray)
    small=cv2.resize(hash_image,(32,32)).astype(np.float32)
    signature=cv2.resize(np.float32(edge),(20,12),interpolation=cv2.INTER_AREA).ravel()
    signature/=max(1e-6,float(np.linalg.norm(signature)))
    dct=cv2.dct(small)[:8,:8].ravel()[1:]
    bits=dct>np.median(dct)
    fingerprint=sum(int(bit)<<i for i,bit in enumerate(bits))
    keypoints,descriptors=cv2.ORB_create(nfeatures=1000,fastThreshold=12).detectAndCompute(gray,np.uint8(~masked)*255)
    return {'gray':gray,'mask':masked,'edge':edge,'near':cv2.dilate(np.uint8(edge),np.ones((3,3),np.uint8))>0,
            'median':float(np.median(gray)), 'ink':int(edge.sum()),'hash':fingerprint,'signature':signature,'keypoints':keypoints,'descriptors':descriptors}


def coverage(source,target):
    missing=source['edge']&(~target['near']|target['mask'])
    fraction=1-float(missing.sum())/max(1,source['ink'])
    if fraction<.975:
        return {'covers':False,'coverage':round(fraction,6)}
    delta=np.abs(source['gray'].astype(np.float32)-target['gray']-source['median']+target['median'])
    strong=np.uint8(missing&(delta>25))
    _,_,stats,_=cv2.connectedComponentsWithStats(strong)
    largest=int(max(stats[1:,cv2.CC_STAT_AREA],default=0))
    count=int(strong.sum())
    # Connected new minus signs/superscripts veto the merge even on a dense page.
    glyph_edit=glyph_changed(source,target) or glyph_changed(target,source) if count<16 else True
    return {'covers':largest<=2 and count<=4 and not glyph_edit,
            'coverage':round(fraction,6),'strong_missing':count,'largest_unique_component':largest}


def aligned_target(source,target):
    ka,da=source['keypoints'],source['descriptors']
    kb,db=target['keypoints'],target['descriptors']
    if da is None or db is None:
        return None
    pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(db,da,k=2)
    good=[a for pair in pairs if len(pair)==2 for a,b in [pair] if a.distance<.7*b.distance]
    if len(good)<14:
        return None
    a=np.float32([kb[m.queryIdx].pt for m in good]);b=np.float32([ka[m.trainIdx].pt for m in good])
    matrix,inliers=cv2.estimateAffine2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2,maxIters=1000)
    if matrix is None or inliers.sum()<12 or inliers.mean()<.55:
        return None
    scale=float(np.hypot(matrix[0,0],matrix[1,0]))
    rotation=float(abs(np.arctan2(matrix[1,0],matrix[0,0])))
    if not .85<scale<1.15 or not .85<matrix[1,1]<1.15 or rotation>.05 or abs(matrix[0,1])>.05 or max(abs(matrix[:,2]))>40:
        return None
    gray=cv2.warpAffine(target['gray'],matrix,(640,400),borderValue=255)
    mask=cv2.warpAffine(np.uint8(target['mask']),matrix,(640,400),flags=cv2.INTER_NEAREST,borderValue=1)>0
    edge=cv2.warpAffine(np.uint8(target['edge']),matrix,(640,400),flags=cv2.INTER_NEAREST)>0
    edge[mask]=False
    return {**target,'gray':gray,'mask':mask,'edge':edge,'near':cv2.dilate(np.uint8(edge),np.ones((3,3),np.uint8))>0,
            'median':float(np.median(gray))}


def family_overlap(a,b):
    visible=~(a['mask']|b['mask'])
    if visible.mean()<.65:return 0.
    aa=a['edge']&visible;bb=b['edge']&visible
    return max(1-float((aa&~b['near']).sum())/max(1,int(aa.sum())),
               1-float((bb&~a['near']).sum())/max(1,int(bb.sum())))


def choose_posters(visuals,feature,check=lambda:None,callback=lambda p,m:None):
    """A page poster is separate from genuinely complementary source bitmaps."""
    summaries={}
    for visual in visuals:
        check();f=feature(visual['id']);summaries[visual['id']]=(f['ink'],f['signature'])
    families=[]
    for index,visual in enumerate(sorted(visuals,key=lambda v:summaries[v['id']][0],reverse=True)):
        check();a=feature(visual['id']);matched=None
        candidates=[f for f in families if f[0]['kind']==visual['kind']]
        candidates=sorted(candidates,key=lambda f:float(a['signature']@summaries[f[0]['id']][1]),reverse=True)[:8]
        for family in candidates:
            if visual['kind']!='slides' and (visual['layout']!=family[0]['layout'] or abs(visual['capture_ts']-family[0]['capture_ts'])>180):continue
            b=feature(family[0]['id'])
            # Grouping only chooses a cover for browsing. Symbol changes remain
            # supplementary originals because deletion still requires coverage().
            overlap=family_overlap(a,b)
            if overlap<=.96 and float(a['signature']@b['signature'])>.7:
                aligned=aligned_target(a,b)
                if aligned is not None:overlap=max(overlap,family_overlap(a,aligned))
            # Projection noise can lower pixel overlap on the very same page.
            # Require substantial matching text as a second, independent signal.
            if overlap>.96 or overlap>.90 and text_agrees(visual,family[0]):
                matched=family;break
        if matched is None:families.append([visual])
        else:matched.append(visual)
        callback(.35*(index+1)/max(1,len(visuals)),f'整理代表页 {index+1}/{len(visuals)}')
    for index,family in enumerate(families):
        candidates=sorted(family,key=lambda v:summaries[v['id']][0],reverse=True)[:5]
        candidates+=sorted(family,key=lambda v:v.get('occlusion',0))[:2]
        def rank(v):
            target=feature(v['id'])
            covers=sum(coverage(feature(other['id']),target)['covers'] for other in family)
            corrected=any(f.get('status')=='corrected' for f in v.get('formulas',[]))
            return corrected,covers,v.get('occlusion',0)<.02,len(v.get('ocr','')),target['ink'],float(v.get('quality_score',0)),v['capture_ts']
        best=max(candidates,key=rank)
        for v in family:
            v['content_id']='p'+best['id'][1:];v['is_representative']=v['id']==best['id']
            v['poster_id']=best['id']
            if not v['is_representative'] and 'complementary_or_uncertain_state' not in v['flags']:
                v['flags'].append('complementary_or_uncertain_state')
        callback(.35+.25*(index+1)/max(1,len(families)),f'选择完整画面 {index+1}/{len(families)}')
    return len(families)


def page_families(visuals,records,feature,check=lambda:None,callback=lambda p,m:None):
    count=choose_posters(visuals,feature,check,callback)
    mapping={v['id']:v for v in visuals}
    protected={v['id'] for v in visuals if any(f.get('status')=='corrected' for f in v.get('formulas',[]))}
    for index,record in enumerate(records):
        check()
        record['page_id']=mapping[record['representative_id']]['content_id']
        record['poster_id']=mapping[record['representative_id']]['poster_id']
        # Recheck the original against the FINAL poster, never via another source.
        if record['representative_id'] not in protected:
            a=feature(record['id']);b=feature(record['poster_id']);evidence=coverage(a,b)
            if not evidence['covers'] and .45<evidence['coverage']<1 and float(a['signature']@b['signature'])>.7:
                aligned=aligned_target(a,b)
                if aligned:evidence=coverage(a,aligned)
            if evidence['covers']:
                record.update(representative_id=record['poster_id'],reason='directly_covered_by_final_page',**evidence)
        callback(.6+.4*(index+1)/max(1,len(records)),f'核对来源 {index+1}/{len(records)}')
    needed={r['representative_id'] for r in records}
    visuals[:]=[v for v in visuals if v['id'] in needed]
    for v in visuals:
        v['appearances']=[{k:r[k] for k in ['id','start','end','capture_ts','quad','kind','layout']} for r in records if r['representative_id']==v['id']]
        v['merged_count']=len(v['appearances'])
    return count


def regroup_existing(visuals,records,output,check=lambda:None,callback=lambda p,m:None):
    """Merge existing browsing groups; preserve every bitmap and recovery target."""
    output=Path(output)
    representatives=[v for v in visuals if v.get('is_representative',True)]
    previous={v['id']:v['content_id'] for v in representatives}
    mapping={v['id']:v for v in visuals}
    @lru_cache(maxsize=128)
    def feature(vid):
        v=mapping[vid]
        image=cv2.imdecode(np.fromfile(str(output/v['image']),np.uint8),1)
        if image is None:raise ValueError('保留图无法读取，停止重新分组')
        mask_path=output/v.get('person_mask','missing')
        mask=cv2.imdecode(np.fromfile(str(mask_path),np.uint8),0) if mask_path.is_file() else None
        return features(image,mask)
    count=choose_posters(representatives,feature,check,callback)
    changed={previous[v['id']]:(v['content_id'],v['poster_id']) for v in representatives}
    for visual in visuals:
        old=previous.get(visual['id'],visual['content_id'])
        content_id,poster_id=changed[old]
        visual.update(content_id=content_id,poster_id=poster_id,is_representative=visual['id']==poster_id)
        if not visual['is_representative'] and 'complementary_or_uncertain_state' not in visual['flags']:
            visual['flags'].append('complementary_or_uncertain_state')
    for record in records:
        v=mapping[record['representative_id']]
        record.update(page_id=v['content_id'],poster_id=v['poster_id'],coverage_target_id=record['representative_id'])
        if record.get('reason')=='directly_covered_by_final_page':record['reason']='directly_covered_by_retained_source'
    return {'previous_groups':len(representatives),'groups':count,'retained_images':len(visuals),'deleted_images':0}


def compact_visuals(visuals,output,check=lambda:None,callback=lambda p,m:None,commit=True):
    output=Path(output)
    started=time.monotonic()
    originals=read_json(output/'source_records.json')
    if originals and read_json(output/'compaction.json',{}).get('version')==VERSION and all(r['representative_id'] in {v['id'] for v in visuals} for r in originals):
        return visuals,originals,read_json(output/'compaction.json')
    if (output/'visuals.precompact.json').exists():visuals=read_json(output/'visuals.precompact.json')
    by_id={v['id']:v for v in visuals}
    @lru_cache(maxsize=512)
    def feature(vid):
        v=by_id[vid]
        image=cv2.imdecode(np.fromfile(str(output/v['image']),np.uint8),1)
        if image is None:
            raise ValueError(f'来源图无法读取：{v["image"]}')
        mask_path=output/v.get('person_mask','missing')
        mask=cv2.imdecode(np.fromfile(str(mask_path),np.uint8),0) if mask_path.is_file() else None
        return features(image,mask)
    scores={};hashes={};signatures={}
    for index,v in enumerate(visuals):
        check()
        f=feature(v['id'])
        scores[v['id']]=(f['ink'],float(v.get('quality_score',0)));hashes[v['id']]=f['hash'];signatures[v['id']]=f['signature']
        callback(.2*(index+1)/max(1,len(visuals)),f'分析画面信息 {index+1}/{len(visuals)}')
    # Richer animation states are considered first. A later image never replaces
    # an anchor, so every discarded original is checked directly against its survivor.
    ordered=sorted(visuals,key=lambda v:(any(f.get('status')=='corrected' for f in v.get('formulas',[])),v.get('occlusion',0)<.02,*scores[v['id']]),reverse=True)
    kept=[];mapping={};decisions={}
    for index,v in enumerate(ordered):
        check()
        f=feature(v['id'])
        candidates=[k for k in kept if k['kind']==v['kind']]
        nearby=sorted(candidates,key=lambda k:abs(k['capture_ts']-v['capture_ts']))[:5]
        similar=sorted(candidates,key=lambda k:float(signatures[k['id']]@f['signature'])-.002*(f['hash']^hashes[k['id']]).bit_count(),reverse=True)[:10]
        candidates=list({k['id']:k for k in similar+nearby}.values())
        protected=any(x.get('status')=='corrected' for x in v.get('formulas',[]))
        for target in ([] if protected else candidates):
            tf=feature(target['id'])
            if (f['hash']^tf['hash']).bit_count()>32:
                continue
            evidence=coverage(f,tf)
            aligned=False
            if not evidence['covers'] and .45<evidence['coverage']<1 and float(f['signature']@tf['signature'])>.7:
                af=aligned_target(f,tf)
                if af:
                    evidence=coverage(f,af);aligned=True
            if not evidence['covers']:
                continue
            reverse=coverage(tf,f)
            # Board erasures and replacement diagrams remain independent states.
            if v['kind']!='slides' and not reverse['covers']:
                continue
            mapping[v['id']]=target['id']
            decisions[v['id']]={'reason':'duplicate' if reverse['covers'] else 'visible_content_contained',**evidence,'aligned':aligned}
            break
        if v['id'] not in mapping:
            kept.append(v);mapping[v['id']]=v['id'];decisions[v['id']]={'reason':'retained_unique_or_uncertain'}
        callback(.2+.5*(index+1)/max(1,len(ordered)),f'精简画面 {index+1}/{len(ordered)} · 保留 {len(kept)} 幅')
    records=[]
    for v in visuals:
        records.append({k:v.get(k) for k in ['id','kind','layout','start','end','capture_ts','quad']}|
            {'representative_id':mapping[v['id']],'original_image':v['image'],**decisions[v['id']]})
    for v in kept:
        v['appearances']=[{k:r[k] for k in ['id','start','end','capture_ts','quad','kind','layout']} for r in records if r['representative_id']==v['id']]
        v['content_id']='p'+v['id'][1:]
        v['merged_count']=len(v['appearances'])
    page_count=page_families(kept,records,feature,check,lambda p,m:callback(.7+.3*p,m))
    kept.sort(key=lambda v:min(a['start'] for a in v['appearances']))
    report={'version':VERSION,'original_count':len(visuals),'retained_count':len(kept),'removed_bitmap_candidates':len(visuals)-len(kept),
            'by_kind':dict(Counter(v['kind'] for v in kept)),'all_sources_mapped':len(records)==len(visuals) and all(r['representative_id'] in {v['id'] for v in kept} for r in records),
            'decisions':dict(Counter(r['reason'] for r in records)),'elapsed_seconds':round(time.monotonic()-started,3),
            'page_count':page_count,'supplementary_images':len(kept)-page_count,
            'semantic_recall_verified':False,'source_video_required_for_recovery':True}
    if commit:
        if not (output/'visuals.precompact.json').exists():write_json(output/'visuals.precompact.json',read_json(output/'visuals.json',visuals))
        write_json(output/'source_records.json',records)
        write_json(output/'visuals.json',kept)
        write_json(output/'compaction.json',report)
    feature.cache_clear()
    return kept,records,report
