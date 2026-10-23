from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

import cv2
import numpy as np

from .common import write_json, read_json
from .resources import cpu_threads,inference_device
from .media import image_at, stream_frames, save_image, native_frame
from .person import person_mask, edge_occluders, detector, MODEL_CONFIGS


def ordered_quad(points):
    points = np.float32(points)
    center = points.mean(axis=0)
    points = points[np.argsort(np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0]))]
    return np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)


def crop_quad(image, normalized):
    h, w = image.shape[:2]
    points = ordered_quad(np.float32(normalized) * [w, h])
    width = max(32, int(max(np.linalg.norm(points[1]-points[0]), np.linalg.norm(points[2]-points[3]))))
    height = max(32, int(max(np.linalg.norm(points[3]-points[0]), np.linalg.norm(points[2]-points[1]))))
    matrix = cv2.getPerspectiveTransform(points, np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]]))
    return cv2.warpPerspective(image, matrix, (width, height))


def propose_regions(image):
    """Find a large bright projection in a classroom; full-screen inputs stay full-screen."""
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = np.uint8((hsv[:, :, 1] < 110) & (hsv[:, :, 2] > 110)) * 255
    mask[int(h*.75):] = 0
    mask[:, int(w*.70):] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        x, y, cw, ch = cv2.boundingRect(contour)
        if not (.23*w < cw < .67*w and .30*h < ch < .74*h and x < .22*w):
            continue
        if x+cw >= .695*w or cw/ch < 1.2 or cw/ch > 2.25:
            continue
        rect = cv2.minAreaRect(cv2.convexHull(contour))
        quad = ordered_quad(cv2.boxPoints(rect))
        if cv2.contourArea(quad) < .12*w*h:
            continue
        # Bright air-conditioning housing may touch the projection. Infer the top
        # from its central columns rather than extending the crop to the ceiling.
        center_left, center_right = int(x+cw*.40), int(x+cw*.80)
        row_luma = np.median(hsv[:int(h*.75), center_left:center_right, 2], axis=1)
        rows = cv2.morphologyEx(np.uint8(row_luma > 130).reshape(-1, 1), cv2.MORPH_CLOSE,
                               np.ones((35, 1), np.uint8)).ravel() > 0
        runs = []
        begin = None
        for iy, yes in enumerate(rows):
            if yes and begin is None:
                begin = iy
            if begin is not None and (not yes or iy == len(rows)-1):
                finish = iy if not yes else iy+1
                runs.append((finish-begin, begin, finish))
                begin = None
        if runs:
            _, top, bottom = max(runs)
            if bottom-top > h*.25 and .025*h < top < .20*h:
                quad[:, 1] = np.where(quad[:, 1] < h*.25, top, quad[:, 1])
        all_edges = cv2.Canny(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 40, 120)
        lines = cv2.HoughLinesP(all_edges, 1, np.pi/180, 70, minLineLength=int(h*.30), maxLineGap=25)
        verticals = []
        horizontals = []
        for line in ([] if lines is None else lines[:, 0]):
            x1, y1, x2, y2 = map(int, line)
            if abs(x2-x1) < .045*max(1, abs(y2-y1)):
                verticals.append(((x1+x2)/2, min(y1,y2), max(y1,y2)))
            if abs(y2-y1) < .045*max(1, abs(x2-x1)) and abs(x2-x1) > .24*w:
                horizontals.append(((y1+y2)/2, min(x1,x2), max(x1,x2)))
        projection_tops = [hy for hy,hx0,hx1 in horizontals
                           if .025*h < hy < .18*h and hx0 < .30*w and .50*w < hx1 < .66*w]
        projection_tops += [vy0 for vx,vy0,vy1 in verticals
                            if .025*h < vy0 < .18*h and vy1-vy0 > .3*h
                            and (abs(vx-x)<.025*w or abs(vx-(x+cw))<.025*w)]
        if .025*h < quad[:2, 1].mean() < .18*h:
            projection_tops.append(float(quad[:2, 1].mean()))
        if projection_tops:
            quad[[0, 1], 1] = min(projection_tops)
        if quad[:2, 1].mean() > .09*h:
            # A browser's white document body can start below its physical screen.
            # Expand a short proposal upward instead of cutting off its title bar.
            conservative_top = max(0, float(quad[2:,1].max()) - float(np.ptp(quad[:,0]))/1.6)
            quad[[0,1],1] = min(float(quad[:2,1].mean()), conservative_top)
        if quad[:2, 1].mean() > .20*h:
            continue
        outer_left = [vx for vx, vy0, vy1 in verticals if .012*w < vx <= x+.025*w and vy1-vy0 > .45*ch]
        if outer_left:
            quad[[0, 3], 0] = min(outer_left)
        quad[:, 0] = np.clip(quad[:, 0], 0, w-1)
        quad[:, 1] = np.clip(quad[:, 1], 0, h-1)
        left = (quad / [w, h]).tolist()
        # The companion panel is proposed only when a physical rectangular border exists.
        regions = [{'kind': 'slides', 'quad': left, 'automatic': True}]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for c in cs:
            p = cv2.approxPolyDP(c, .02*cv2.arcLength(c, True), True)
            if len(p) != 4 or not cv2.isContourConvex(p):
                continue
            bx, by, bw, bh = cv2.boundingRect(p)
            if bx > .52*w and bw > .26*w and .2*h < bh < .6*h:
                candidates.append(p.reshape(-1, 2))
        if candidates:
            board = max(candidates, key=cv2.contourArea)
            regions.append({'kind': 'board', 'quad': (ordered_quad(board)/[w, h]).tolist(), 'automatic': True})
        else:
            hs = [(hy, hx0, hx1) for hy,hx0,hx1 in horizontals if hx0 > .55*w and hx1 > .9*w and .1*h < hy < .75*h]
            upper = [r for r in hs if .15*h < r[0] < .38*h]
            lower = [r for r in hs if .53*h < r[0] < .75*h]
            if upper and lower:
                top_line = max(upper, key=lambda r: r[2]-r[1])
                bottom_line = max(lower, key=lambda r: r[2]-r[1])
                bx0, bx1 = min(top_line[1], bottom_line[1]), max(top_line[2], bottom_line[2])
                by0, by1 = top_line[0], bottom_line[0]
                if 1.2 < (bx1-bx0)/max(1, by1-by0) < 2.4:
                    regions.append({'kind': 'board', 'quad': [[bx0/w,by0/h],[bx1/w,by0/h],[bx1/w,by1/h],[bx0/w,by1/h]], 'automatic': True})
        if len(regions) == 1:
            # A conservative companion-panel proposal retains its surrounding
            # border when glare breaks contour detection; users can refine it.
            bx0 = min(.82, float(quad[[1,2],0].max()/w)+.004)
            by0 = max(.12, float(quad[:2,1].mean()/h)+.13)
            by1 = min(.82, float(quad[2:,1].max()/h)+.035)
            if bx0 < .72 and by1-by0 > .25:
                regions.append({'kind': 'board', 'quad': [[bx0,by0],[.998,by0],[.998,by1],[bx0,by1]],
                                'automatic': True, 'needs_calibration': True})
        return regions
    return []


def is_flat_screen(image):
    small = cv2.resize(image, (160, 90))
    bins = (small // 32).astype(np.int32)
    codes = bins[:,:,0]*64 + bins[:,:,1]*8 + bins[:,:,2]
    return np.bincount(codes.ravel(), minlength=512).max()/codes.size > .58


def gray_small(image, width=640):
    h, w = image.shape[:2]
    return cv2.cvtColor(cv2.resize(image, (width, max(24, int(h*width/w)))), cv2.COLOR_BGR2GRAY)


@lru_cache(maxsize=64)
def _human_mask(shape, pixels):
    image = np.frombuffer(pixels,np.uint8).reshape(shape)
    gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    mask = np.zeros(gray.shape,np.uint8)
    for name in ['haarcascade_frontalface_default.xml','haarcascade_profileface.xml']:
        detector = face_detector(name)
        offset = int(gray.shape[0]*.35)
        faces = detector.detectMultiScale(gray[offset:],scaleFactor=1.2,minNeighbors=4,minSize=(14,14))
        for x,y,w,h in faces:
            y += offset
            if y+h/2 < gray.shape[0]*.42:
                continue
            sample = hsv[y:y+h,x:x+w]
            skin = (sample[:,:,0]<28)&(sample[:,:,1]>30)&(sample[:,:,1]<220)&(sample[:,:,2]>60)
            if skin.mean() < .12:
                continue
            x0,x1 = max(0,int(x-.8*w)),min(gray.shape[1],int(x+1.8*w))
            y0 = max(0,int(y-.2*h))
            mask[y0:,x0:x1] = 1
    return mask if mask.mean()<.38 else np.zeros_like(mask)


@lru_cache(maxsize=2)
def face_detector(name):
    # OpenCV's filename loader cannot open some Unicode Windows paths.
    path=Path(cv2.data.haarcascades)/name
    storage=cv2.FileStorage(path.read_text(encoding='utf-8'),cv2.FILE_STORAGE_READ|cv2.FILE_STORAGE_MEMORY)
    try:
        detector=cv2.CascadeClassifier()
        if not detector.read(storage.getFirstTopLevelNode()) or detector.empty():
            raise RuntimeError('本地人脸检测资源损坏，请重新解压运行时')
        return detector
    finally:
        storage.release()


def human_mask(image,width=512):
    if image.ndim != 3:
        return np.zeros(image.shape,np.uint8)
    h,w = image.shape[:2]
    small = cv2.resize(image,(320,max(24,int(h*320/w))))
    mask = _human_mask(small.shape,small.tobytes())
    return cv2.resize(mask,(width,max(24,int(h*width/w))),interpolation=cv2.INTER_NEAREST)


def comparison_mask(image, mask=None):
    shape = gray_small(image, 512).shape if image.ndim == 3 else image.shape
    if mask is None:
        mask = human_mask(image)
    mask = cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return cv2.dilate(mask,np.ones((5,5),np.uint8))>0


def compare(a, b, mask_a=None, mask_b=None):
    """Conservative local block comparison; an unchanged overall template is insufficient."""
    mask_a,mask_b = comparison_mask(a,mask_a),comparison_mask(b,mask_b)
    if a.ndim==3 and b.ndim==3:
        colour_a = cv2.resize(a,(512,mask_a.shape[0]))
        colour_b = cv2.resize(b,(512,mask_a.shape[0]))
        mask_a |= edge_occluders(colour_a,colour_b)>0
        mask_b = cv2.resize(mask_b.astype(np.uint8),(512,mask_a.shape[0]),interpolation=cv2.INTER_NEAREST)>0
        mask_b |= edge_occluders(colour_b,colour_a)>0
    a = gray_small(a, 512) if a.ndim == 3 else a
    b = gray_small(b, 512) if b.ndim == 3 else b
    b = cv2.resize(b, (a.shape[1], a.shape[0]))
    mask = mask_a|cv2.resize(mask_b.astype(np.uint8),(a.shape[1],a.shape[0]),interpolation=cv2.INTER_NEAREST).astype(bool)
    # Remove a global brightness offset while preserving local symbol changes.
    delta = b.astype(np.float32)-a.astype(np.float32)
    delta -= np.median(delta)
    delta = np.abs(delta)
    delta[mask] = 0
    block = 16
    hh, ww = a.shape[0]//block*block, a.shape[1]//block*block
    tiles = delta[:hh, :ww].reshape(hh//block, block, ww//block, block).mean(axis=(1, 3))
    ratio = float(np.mean(tiles > 7))
    ea, eb = cv2.Canny(a, 60, 150), cv2.Canny(b, 60, 150)
    ea[mask],eb[mask] = 0,0
    near_a = cv2.dilate(ea, np.ones((3, 3), np.uint8))
    near_b = cv2.dilate(eb, np.ones((3, 3), np.uint8))
    denominator = max(1, np.count_nonzero(ea)+np.count_nonzero(eb))
    edge_agreement = (np.count_nonzero((ea > 0) & (near_b > 0)) + np.count_nonzero((eb > 0) & (near_a > 0))) / denominator
    unmatched = ((ea>0)&(near_b==0))|((eb>0)&(near_a==0))
    # Ignore compression flicker but retain a small new/erased symbol.
    ink = np.uint8(unmatched & (delta>18))
    _,_,stats,_ = cv2.connectedComponentsWithStats(cv2.dilate(ink,np.ones((3,3),np.uint8)))
    changed_ink = int(max(stats[1:,cv2.CC_STAT_AREA],default=0))
    return {'changed_blocks': ratio, 'edge_agreement': float(edge_agreement),
            'mean_difference': float(delta.mean()), 'changed_ink': changed_ink, 'visible_fraction':1-float(mask.mean())}


def same_content(a, b, mask_a=None, mask_b=None):
    result = compare(a, b, mask_a, mask_b)
    return (result['visible_fraction']>.65 and result['changed_blocks']<.012
            and result['edge_agreement']>.94 and result['changed_ink']<18)


def geometry_match(reference, observation):
    """Geometry locates a view; independent content checks decide whether to merge it."""
    a, b = gray_small(reference, 640), gray_small(observation, 640)
    sift = cv2.SIFT_create(nfeatures=1800, contrastThreshold=.015)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or min(len(ka), len(kb)) < 12:
        return None
    pairs = cv2.BFMatcher().knnMatch(db, da, k=2)
    matches = [p[0] for p in pairs if len(p) == 2 and p[0].distance < .75*p[1].distance]
    if len(matches) < 12:
        return None
    source = np.float32([kb[m.queryIdx].pt for m in matches])
    target = np.float32([ka[m.trainIdx].pt for m in matches])
    matrix, inliers = cv2.estimateAffine2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=3.)
    if matrix is None or int(inliers.sum()) < 12 or float(inliers.mean()) < .30:
        return None
    determinant = np.linalg.det(matrix[:, :2])
    if determinant <= 0:
        return None
    corners = cv2.transform(np.float32([[[0, 0], [b.shape[1]-1, 0], [b.shape[1]-1, b.shape[0]-1], [0, b.shape[0]-1]]]), matrix)[0]
    area_ratio = abs(cv2.contourArea(corners))/(a.shape[0]*a.shape[1])
    if not cv2.isContourConvex(corners) or not .08 < area_ratio < 6:
        return None
    if np.ptp(target[inliers.ravel() > 0], axis=0).prod() < .04*a.shape[0]*a.shape[1]:
        return None
    warped = cv2.warpAffine(b, matrix, (a.shape[1], a.shape[0]))
    mask = cv2.warpAffine(np.ones_like(b)*255, matrix, (a.shape[1], a.shape[0])) > 250
    mask = cv2.erode(np.uint8(mask), np.ones((7, 7), np.uint8)) > 0
    if mask.mean() < .08:
        return None
    ea, eb = cv2.Canny(a, 60, 150), cv2.Canny(warped, 60, 150)
    near_a = cv2.dilate(ea, np.ones((3, 3), np.uint8))
    near_b = cv2.dilate(eb, np.ones((3, 3), np.uint8))
    denom = max(1, np.count_nonzero((ea > 0) & mask)+np.count_nonzero((eb > 0) & mask))
    agreement = (np.count_nonzero((ea > 0) & (near_b > 0) & mask)+np.count_nonzero((eb > 0) & (near_a > 0) & mask))/denom
    return {'inliers': int(inliers.sum()), 'area_ratio': float(area_ratio), 'edge_agreement': float(agreement),
            'partial': area_ratio < .75, 'matrix': matrix.tolist()}


def quality(image, mask=None):
    gray = gray_small(image, 512)
    mask = comparison_mask(image,mask)
    laplace = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(laplace[~mask].var()) if (~mask).any() else 0
    clipped = float(np.mean(gray > 250))
    return sharpness * (1-.5*clipped) * (1-float(mask.mean()))**2


@dataclass
class Profile:
    image: np.ndarray
    regions: list
    mask: np.ndarray

    @classmethod
    def create(cls, image, regions):
        small = cv2.resize(image, (320, 180))
        mask = np.ones((180, 320), np.uint8)
        for region in regions:
            cv2.fillConvexPoly(mask, np.int32(np.float32(region['quad'])*[320, 180]), 0)
        mask[120:] = 0  # students and moving lecturer below the screens
        return cls(small, regions, mask > 0)

    def score(self, image):
        small = cv2.resize(image, (320, 180))
        delta = np.abs(small.astype(float)-self.image.astype(float)).mean(axis=2)
        return float(np.median(delta[self.mask])+.25*np.percentile(delta[self.mask],80)) if self.mask.any() else 255.


def extract_video(path, windows, output, callback, check, configured=None, configured_at=None,person_model='yolox-tiny',low_resolution=False):
    output = Path(output)
    session = detector(person_model)
    size = session.get_inputs()[0].shape[2] if session else 416
    write_json(output/'vision_runtime.json',{'person_model':person_model if session else 'OpenCV Haar fallback',
               'person_model_sha256':MODEL_CONFIGS[person_model][1] if session else None,
               'providers':session.get_providers() if session else [],'input_size':[size,size],
               'sampling':'2Hz low-resolution screening + native candidate capture' if low_resolution else '2Hz grid, actual decoded source PTS','source_images_modified':False})
    profile_path = output/'profiles.json'
    saved_profiles = read_json(profile_path, [])
    profiles = []
    for item in saved_profiles:
        try:
            profiles.append(Profile.create(image_at(path, item['capture_ts']), item['regions']))
        except (ValueError, RuntimeError):
            pass
    if configured:
        reference_time = configured_at if configured_at is not None else windows[0][0]
        profiles = [Profile.create(image_at(path, reference_time), configured)]
        saved_profiles = [{'capture_ts': reference_time, 'regions': configured}]
        write_json(profile_path,saved_profiles)
    checkpoint = read_json(output/'visual_checkpoint.json', {})
    observations = read_json(output/'visuals.json', []) if checkpoint else []
    layouts = read_json(output/'layouts.json', []) if checkpoint else []
    # A one-minute checkpoint closes open appearances without discarding pixels.
    # Resumption starts at that boundary and strict linking handles duplicates.
    scan_windows = []
    for a,b in windows:
        a = max(a, checkpoint.get('until',a))
        while a < b:
            scan_windows.append((a,min(a+60,b)))
            a += 60
    total = sum(end-start for start, end in windows)
    completed = sum(max(0,min(b,checkpoint.get('until',a))-a) for a,b in windows)
    active = {}
    layout_key = None
    layout_start = None
    layout_index = len(layouts)
    background_failures = 0
    last_native_proposal = -3
    native = cv2.VideoCapture(str(path),cv2.CAP_FFMPEG,[cv2.CAP_PROP_N_THREADS,cpu_threads()])

    def close_state(kind, end):
        state = active.pop(kind, None)
        if state is None:
            return
        state['end'] = end
        if state['end']-state['start'] < .49:
            return
        selected,actual=native_frame(native,path,state['capture_ts'])
        image=crop_quad(selected,state['quad']) if state['quad'] else selected
        candidates=[(image,state['best_mask'],actual,state['capture_ts'])]
        if low_resolution and end-state['start']>1.2 and end-.2-state['capture_ts']>.6:
            final,final_time=native_frame(native,path,end-.2)
            final_mask,_=person_mask(final,person_model)
            if final_mask is None:final_mask=cv2.resize(human_mask(final),(final.shape[1],final.shape[0]),interpolation=cv2.INTER_NEAREST)
            final_image=crop_quad(final,state['quad']) if state['quad'] else final
            final_mask=np.uint8((crop_quad(final_mask,state['quad']) if state['quad'] else final_mask)>0)
            from .compaction import features,coverage
            before,after=features(image,state['best_mask']),features(final_image,final_mask)
            if coverage(before,after)['covers']:
                candidates=[(final_image,final_mask,final_time,end-.2)]
            elif not coverage(after,before)['covers']:
                candidates.append((final_image,final_mask,final_time,end-.2))
        for image,mask,captured,requested in candidates:
            stored={k:v for k,v in state.items() if k not in {'reference','reference_mask','best_mask','best_score'}}
            stored['flags']=list(state['flags'])
            if len(candidates)>1:stored['flags'].append('native_end_state_needs_check')
            stored['capture_ts']=captured;stored['requested_capture_ts']=requested
            stored['quality_score']=quality(image,mask);stored['occlusion']=float(mask.mean())
            name=f"images/{len(observations)+1:05d}_{kind}_{captured:.2f}.png"
            mask_name=f"masks/{len(observations)+1:05d}.png"
            save_image(output/name,image);save_image(output/mask_name,mask*255)
            stored.update({'id':f'v{len(observations)+1:05d}','image':name,'ocr':'','formulas':[],
                           'content_id':f'c{len(observations)+1:05d}','person_mask':mask_name})
            if stored['occlusion']>.12:stored['flags'].append('person_occlusion')
            observations.append(stored)

    for window_start, window_end in scan_windows:
        active.clear()
        layout_key = None
        for second, frame in stream_frames(path, window_start, window_end, fps=2, width=480 if low_resolution else 960,hardware=low_resolution and inference_device()=='cuda'):
            from .resources import cooldown
            import time
            work_start=time.monotonic()
            check()
            people, _ = person_mask(frame,person_model)
            if people is None:
                people = cv2.resize(human_mask(frame), (frame.shape[1],frame.shape[0]), interpolation=cv2.INTER_NEAREST)
            scores = [profile.score(frame) for profile in profiles]
            best = int(np.argmin(scores)) if scores else -1
            flat_screen = is_flat_screen(frame)
            if best >= 0 and scores[best] < 21 and not flat_screen:
                regions = profiles[best].regions
                current_key = f'classroom_{best}'
                background_failures = 0
            else:
                background_failures += 1
                regions = []
                if not flat_screen and (not profiles or background_failures >= 4):
                    proposed=[]
                    if not low_resolution:proposed=propose_regions(frame)
                    elif second-last_native_proposal>=3:
                        proposed=propose_regions(image_at(path,second));last_native_proposal=second
                    if proposed:
                        profiles.append(Profile.create(frame, proposed))
                        saved_profiles.append({'capture_ts': second, 'regions': proposed})
                        write_json(profile_path, saved_profiles)
                        regions = proposed
                        best = len(profiles)-1
                        background_failures = 0
                current_key = f'classroom_{best}' if regions else 'full_frame'
            if not regions:
                regions = [{'kind': 'screen', 'quad': None, 'automatic': True}]
            if current_key != layout_key:
                for kind in list(active):
                    close_state(kind, second)
                if layout_key is not None:
                    layouts.append({'id': f'l{layout_index}', 'start': layout_start, 'end': second, 'kind': layout_key})
                layout_index += 1
                layout_key, layout_start = current_key, second
            for region in regions:
                kind = region['kind']
                crop = crop_quad(frame, region['quad']) if region['quad'] else frame
                mask = crop_quad(people,region['quad']) if region['quad'] else people
                mask = np.uint8(mask>0)
                state = active.get(kind)
                difference = compare(state['reference'],crop,state['reference_mask'],mask) if state else None
                # Local differences create candidates. Exact duplicate grouping is a later step.
                threshold = .012 if kind=='slides' else .008
                changed = state is not None and (difference['changed_blocks']>threshold
                           or difference['edge_agreement']<.88 or difference['changed_ink']>24)
                if changed and second-state['start'] >= 1.0:
                    close_state(kind, second)
                    state = None
                score = quality(crop,mask)
                if state is None:
                    active[kind] = {'kind': kind, 'start': second, 'end': second, 'capture_ts': second,
                                    'quad': region['quad'], 'layout': current_key, 'reference': crop.copy(),
                                    'reference_mask':mask.copy(), 'best_mask':mask.copy(), 'occlusion':float(mask.mean()),
                                    'best_score': score, 'flags': (['region_proposal_needs_check'] if region.get('needs_calibration') else [])
                                    + ([] if region['quad'] else ['full_frame_source'])}
                elif score > state['best_score']*1.03:
                    state['best_score'], state['capture_ts'] = score, second
                    state['best_mask'],state['occlusion'] = mask.copy(),float(mask.mean())
                if state is not None:
                    revealed = (state['reference_mask']>0)&(mask==0)
                    state['reference'][revealed] = crop[revealed]
                    state['reference_mask'][revealed] = 0
            if int((second-window_start)*2) % 20 == 0:
                callback((completed+second-window_start)/max(1, total), f'扫描画面 {second/60:.1f} 分钟 · 已保留 {len(observations)} 张')
            cooldown(work_start,check)
        for kind in list(active):
            close_state(kind, window_end)
        if layout_key is not None:
            layouts.append({'id': f'l{layout_index}', 'start': layout_start, 'end': window_end, 'kind': layout_key})
        completed += window_end-window_start
        write_json(output/'visuals.json', observations)
        write_json(output/'layouts.json', layouts)
        write_json(output/'visual_checkpoint.json', {'until':window_end})
    callback(1, f'画面提取完成 · {len(observations)} 张，{len(layouts)} 个镜头区间')
    native.release()
    return observations, layouts


def link_views(visuals, output, check, callback):
    """Link only verified views; never delete an appearance or its timestamps."""
    recent = []
    anchors = []
    for index, item in enumerate(visuals):
        check()
        image = cv2.imdecode(np.fromfile(str(Path(output)/item['image']), np.uint8), cv2.IMREAD_COLOR)
        mask = cv2.imdecode(np.fromfile(str(Path(output)/item['person_mask']),np.uint8),0) if item.get('person_mask') else None
        item.pop('linked_to',None)
        item.pop('related_to',None)
        item['content_id'] = 'c'+item['id'][1:]
        for other, previous, previous_mask in reversed(anchors[-48:]):
            # Always compare with the group's fixed first observation. Matching
            # A-B and B-C alone must never imply A-C when occlusion moves.
            if other['kind'] == item['kind'] and other['layout']==item['layout'] and same_content(previous,image,previous_mask,mask):
                item['content_id'] = other['content_id']
                item['linked_to'] = other['id']
                if max(item.get('occlusion',0),other.get('occlusion',0))>.01:
                    if 'grouped_occlusion_needs_check' not in item['flags']:
                        item['flags'].append('grouped_occlusion_needs_check')
                break
        if 'linked_to' not in item:
            anchors.append((item,image,mask))
            if len(anchors)>48:
                anchors.pop(0)
        for other, previous, previous_mask in reversed(recent[-12:]):
            if other['layout'] != item['layout']:
                match = geometry_match(previous, image)
                if match and match['edge_agreement'] > .90:
                    item['related_to'] = other['id']
                    item['geometry'] = match
                    item['flags'].append('detail_view' if match['partial'] else 'related_view_needs_check')
                    break
        recent.append((item, image, mask))
        if len(recent) > 12:
            recent.pop(0)
        callback((index+1)/max(1, len(visuals)), f'关联画面 {index+1}/{len(visuals)}')
    write_json(Path(output)/'visuals.json', visuals)
    return visuals


def audit_visuals(visuals, layouts, windows, output, version=5):
    """Check timeline coverage and make every retained appearance inspectable."""
    kept_count=len(visuals)
    visuals=[{**v,**a,'image':v['image'],'content_id':v['content_id']} for v in visuals for a in v.get('appearances',[{}])]
    gaps = []
    for start,end in windows:
        cursor = start
        for a,b in sorted((max(start,v['start']),min(end,v['end'])) for v in visuals
                          if v['end']>start and v['start']<end):
            if a-cursor>.6:
                gaps.append([cursor,a])
            cursor = max(cursor,b)
        if end-cursor>.6:
            gaps.append([cursor,end])
    groups = {}
    for item in visuals:
        groups.setdefault(item['content_id'],[]).append(item)
    pages = []
    for key,items in groups.items():
        representative = max(items,key=lambda x:(x.get('is_representative',True),x.get('quality_score',0)))
        pages.append({'content_id':key,'representative':representative['id'],'kind':representative['kind'],
                      'appearances':[{'id':v['id'],'start':v['start'],'end':v['end'],'image':v['image']} for v in items]})
    profiles = read_json(Path(output)/'profiles.json',[])
    region_gaps = []
    for layout in layouts:
        key = layout['kind']
        if key=='full_frame':
            expected = ['screen']
        elif key.startswith('classroom_') and int(key.split('_')[-1])<len(profiles):
            expected = [r['kind'] for r in profiles[int(key.split('_')[-1])]['regions']]
        else:
            continue
        for kind in expected:
            cursor = layout['start']
            for v in sorted((v for v in visuals if v['layout']==key and v['kind']==kind
                             and v['end']>layout['start'] and v['start']<layout['end']),key=lambda v:v['start']):
                if v['start']-cursor>.6:
                    region_gaps.append({'layout':layout['id'],'kind':kind,'start':cursor,'end':v['start']})
                cursor = max(cursor,v['end'])
            if layout['end']-cursor>.6:
                region_gaps.append({'layout':layout['id'],'kind':kind,'start':cursor,'end':layout['end']})
    audit = {'visual_version':version,'raw_appearances':len(visuals),'retained_images':kept_count,'content_groups':len(groups),
             'grouped_repeats':len(visuals)-len(groups),'uncovered_intervals_over_0_6s':gaps,
             'region_coverage_gaps_over_0_6s':region_gaps,
             'short_appearances':[v['id'] for v in visuals if v['end']-v['start']<1.1],
             'occluded_appearances':[v['id'] for v in visuals if v.get('occlusion',0)>.12],
             'sample_interval_seconds':.5,'timestamps':'decoded_source_pts' if version>=5 else 'legacy_fps_grid',
             'semantic_completeness_verified':False,
             'limits':['短于采样间隔的内容可能遗漏','教师持续遮挡的文字不能自动恢复','自动相似分组仍需核对，所有来源记录可展开'],
             'layouts':layouts}
    write_json(Path(output)/'pages.json',pages)
    write_json(Path(output)/'visual_audit.json',audit)
    return audit
