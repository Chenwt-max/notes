from __future__ import annotations

import json
import subprocess
import re
import threading
from queue import Queue, Empty
from collections import deque
from pathlib import Path

import cv2
import numpy as np
from .resources import cpu_threads


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, **kwargs)


def probe(path):
    raw = run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)])
    data = json.loads(raw.stdout)
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
    if video is None:
        raise ValueError('文件没有视频画面')
    return {'duration': float(data['format']['duration']), 'width': video['width'],
            'height': video['height'], 'audio': any(s['codec_type'] == 'audio' for s in data['streams']),
            'subtitles': [s['index'] for s in data['streams'] if s['codec_type'] == 'subtitle'],
            'streams': data['streams']}


def image_at(path, second, *, with_timestamp=False):
    raw = run(['ffmpeg', '-v', 'error', '-threads',str(cpu_threads()),'-filter_threads','1','-ss', str(max(0, second)), '-i', str(path),
               '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-threads', str(cpu_threads()), 'pipe:1'])
    actual = max(0, second)
    image = cv2.imdecode(np.frombuffer(raw.stdout, np.uint8), cv2.IMREAD_COLOR) if raw.stdout else None
    if not raw.stdout:
        # FFmpeg seeks forward. Inside the final frame's display interval there
        # is no later frame; recover that exact native frame, never a thumbnail.
        capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            if fps>0 and count>=1 and (count-1)/fps<=second<=count/fps+.05:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(count)-1)
                ok, candidate = capture.read()
                timestamp = capture.get(cv2.CAP_PROP_POS_MSEC)/1000
                if ok and (count-1)/fps-.1<=timestamp<=second+.05:
                    image, actual = candidate, timestamp
        finally:
            capture.release()
    if image is None:
        raise ValueError(f'无法读取 {second:.2f} 秒的画面')
    return (image, actual) if with_timestamp else image


def native_frame(capture, path, requested):
    capture.set(cv2.CAP_PROP_POS_MSEC, requested*1000)
    ok, selected = capture.read()
    actual = capture.get(cv2.CAP_PROP_POS_MSEC)/1000
    if ok and actual>requested+.1:
        # A low/VFR seek can land on the next page. Its preceding decoded frame
        # is the state still displayed at the requested terminal time.
        previous=max(0,int(capture.get(cv2.CAP_PROP_POS_FRAMES))-2)
        capture.set(cv2.CAP_PROP_POS_FRAMES,previous)
        valid, prior=capture.read()
        prior_time=capture.get(cv2.CAP_PROP_POS_MSEC)/1000
        if valid and 0<=prior_time<=requested:return prior,prior_time
    if not ok or abs(actual-requested)>.1:
        return image_at(path, requested, with_timestamp=True)
    return selected, actual


def audio_chunk(path, start, end, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-v', 'error', '-threads',str(cpu_threads()),'-filter_threads','1','-y', '-ss', str(start), '-i', str(path), '-t', str(end-start),
         '-vn', '-ac', '1', '-ar', '16000', '-threads', str(cpu_threads()), str(output)])


def stream_frames(path, start, end, fps=2, width=640, hardware=False):
    meta = probe(path)
    height = int(round(meta['height'] * width / meta['width'] / 2) * 2)
    select=f'isnan(prev_selected_t)+gt(floor(t*{fps}),floor(prev_selected_t*{fps}))'
    command = ['ffmpeg', '-hide_banner', '-v', 'info', '-threads',str(cpu_threads()),'-filter_threads','1',
               *(['-hwaccel','cuda'] if hardware else []),'-ss', str(start), '-i', str(path), '-t', str(end-start),
               '-vf', f"select='{select}',scale={width}:{height},showinfo",
               '-fps_mode', 'vfr', '-an', '-sn', '-threads', str(cpu_threads()),
               '-pix_fmt', 'bgr24', '-f', 'rawvideo', 'pipe:1']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    timestamps = Queue()
    errors = deque(maxlen=8)
    def read_times():
        for line in iter(process.stderr.readline,b''):
            found = re.search(rb'\bn:\s*\d+\s+pts:.*?pts_time:([\d.e+\-]+)',line)
            if found:
                timestamps.put(float(found[1]))
            else:
                errors.append(line.decode('utf-8',errors='replace').strip())
    reader = threading.Thread(target=read_times,daemon=True)
    reader.start()
    size = width * height * 3
    bounded = False
    received = 0
    try:
        while True:
            raw = process.stdout.read(size)
            if len(raw) != size:
                break
            try:
                second = start+timestamps.get(timeout=30)
            except Empty:
                raise RuntimeError('未读取到视频帧的实际时间戳')
            if second>=end:
                bounded = True
                break
            received += 1
            yield second, np.frombuffer(raw, np.uint8).reshape(height, width, 3).copy()
        if not bounded:
            code = process.wait()
            if code:
                if hardware and received==0:
                    yield from stream_frames(path,start,end,fps,width,hardware=False)
                    return
                raise RuntimeError(f'画面扫描失败：FFmpeg {code} '+str(list(errors)))
    finally:
        if process.poll() is None:
            process.terminate()
        process.stdout.close()
        process.wait()
        reader.join(timeout=2)
        process.stderr.close()


def save_image(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix, image)
    if not ok:
        raise ValueError('图片编码失败')
    data.tofile(str(path))
