"""Create the public lesson from authored text, local Windows TTS and lossless slides."""
import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import wave
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'lesson-script.json'
spec = json.loads(SCRIPT.read_text('utf-8'))
font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
@lru_cache(maxsize=16)
def font(size):
    return ImageFont.truetype(str(font_path), size)


@lru_cache(maxsize=8)
def math_font(size):
    return ImageFont.truetype(str(font_path.with_name('cambria.ttc')), size)
INK, MUTED, BLUE = '#182b39', '#526775', '#247e92'


def matrix(draw, x, y, values, size=54, cell=88):
    width, height = len(values[0]) * cell, len(values) * cell
    for row, numbers in enumerate(values):
        for col, number in enumerate(numbers):
            draw.text((x + col*cell + cell/2, y + row*cell + cell/2), str(number), font=font(size), fill=INK, anchor='mm')
    for edge, direction in ((x-15, 1), (x+width+15, -1)):
        draw.line([(edge+direction*16, y), (edge, y), (edge, y+height), (edge+direction*16, y+height)], fill=INK, width=5)


def paragraph(draw, text, y):
    line = ''
    for char in text:
        if draw.textlength(line + char, font=font(40)) > 1520:
            draw.text((200, y), line, font=font(40), fill=MUTED)
            y += 64
            line = ''
        line += char
    draw.text((200, y), line, font=font(40), fill=MUTED)


def slide(index, path):
    image = Image.new('RGB', (1920, 1080), '#edf5f7')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 110, 1820, 982), radius=44, fill='white')
    draw.text((110, 44), 'notes  /  SELF-MADE REPRODUCIBLE LESSON', font=font(27), fill=BLUE)
    draw.text((200, 170), spec['slides'][index]['title'], font=font(66), fill=INK)
    draw.text((200, 274), f'0{index+1}   最小二乘 · 公开自制示例', font=font(30), fill=BLUE)
    if index == 0:
        draw.text((225, 474), 'X =', font=font(58), fill=INK)
        matrix(draw, 390, 385, [[1, 0], [1, 1], [1, 2]])
        draw.text((760, 474), 'w =', font=font(58), fill=INK)
        matrix(draw, 930, 428, [[1], [2]])
        draw.text((1240, 474), 'y =', font=font(58), fill=INK)
        matrix(draw, 1400, 385, [[1], [3], [5]])
        draw.text((720, 716), 'Xw = y', font=font(72), fill=BLUE)
        paragraph(draw, '三行观测、两个参数。此例含常数列；参数分别为截距和斜率。', 850)
    elif index == 1:
        for text, y in [('L(w) = ||Xw − y||²', 390), ('2Xᵀ(Xw − y) = 0', 520), ('XᵀXw = Xᵀy', 650)]:
            draw.text((350, y), text, font=math_font(76), fill=INK)
        paragraph(draw, '满列秩保证唯一解。不满列秩时，最小二乘解仍存在，但参数可能不唯一。', 840)
    else:
        draw.text((230, 390), 'y = [1, 3, 6]ᵀ', font=math_font(65), fill=INK)
        draw.text((230, 500), 'ŵ = [5/6, 5/2]ᵀ', font=math_font(65), fill=INK)
        draw.text((230, 610), 'r = [1/6, −1/3, 1/6]ᵀ', font=math_font(65), fill=INK)
        draw.text((230, 720), 'Xᵀr = 0', font=math_font(72), fill=BLUE)
        paragraph(draw, '残差非零表示没有精确拟合；它并不表示最小二乘问题无解。', 850)
    draw.text((1620, 1020), f'{index+1} / 3', font=font(28), fill=MUTED)
    image.save(path)


def stamp(seconds):
    ms = round(seconds * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ffmpeg', default=str(ROOT/'runtime/tools/ffmpeg.exe') if (ROOT/'portable.json').exists() else shutil.which('ffmpeg'))
    args = parser.parse_args()
    if not args.ffmpeg or not font_path.is_file():
        raise SystemExit('需要FFmpeg和Windows中文字体msyh.ttc')
    # Verify the exact rational example independently of raster/OCR/API output.
    weights = [F(5, 6), F(5, 2)]
    residual = [F(y) - weights[0] - weights[1]*x for x, y in enumerate([1, 3, 6])]
    assert residual == [F(1, 6), F(-1, 3), F(1, 6)]
    assert sum(residual) == sum(x*r for x, r in enumerate(residual)) == 0
    digest = hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    work = ROOT/'cache/public-demo-build'/digest[:12]
    work.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    def checked(command):
        result=subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace', creationflags=flags)
        if result.returncode:raise RuntimeError(result.stdout + result.stderr)
    checked(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(HERE/'speak-lesson.ps1'),
             '-ScriptPath', str(SCRIPT), '-OutputDirectory', str(work)])
    rate, index = 16000, 0
    audio, durations, captions = bytearray(), [], []
    for number, part in enumerate(spec['slides']):
        slide(number, work/f'slide-{number}.png')
        start = len(audio)//2
        audio.extend(b'\0\0' * int(.7*rate))
        for sentence in part['sentences']:
            with wave.open(str(work/f'speech-{index:02}.wav')) as wav:
                assert wav.getparams()[:3] == (1, 2, rate)
                data = wav.readframes(wav.getnframes())
            begin = len(audio)/2/rate
            audio.extend(data)
            captions.append({'start': begin, 'end': len(audio)/2/rate, 'text': sentence})
            audio.extend(b'\0\0' * int(.2*rate))
            index += 1
        frames = math.ceil(((len(audio)//2-start)/rate + .7)*2)/2*rate
        audio.extend(b'\0\0' * (round(frames) - (len(audio)//2-start)))
        durations.append(round(frames)/rate)
    with wave.open(str(work/'audio.wav'), 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(audio)
    command = [args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y']
    for number in range(3): command += ['-loop', '1', '-framerate', '2', '-i', str(work/f'slide-{number}.png')]
    command += ['-i', str(work/'audio.wav')]
    filters = ';'.join(f'[{i}:v]trim=duration={seconds},setpts=PTS-STARTPTS[v{i}]' for i, seconds in enumerate(durations))
    filters += ';[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[v]'
    video = HERE/'selfmade-lesson.webm'
    command += ['-filter_complex', filters, '-map', '[v]', '-map', '3:a', '-c:v', 'libvpx-vp9', '-lossless', '1',
                '-cpu-used', '4', '-threads', '2', '-row-mt', '1', '-c:a', 'libopus', '-b:a', '48k', '-ar', '48000',
                '-t', str(sum(durations)), str(video)]
    checked(command)
    for number in range(3): shutil.copy2(work/f'slide-{number}.png', HERE/f'lesson-slide-{number+1}.png')
    (HERE/'lesson-reference.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(captions))+'\n', encoding='utf-8')
    (HERE/'lesson-reference.json').write_text(json.dumps({'script_sha256': digest, 'synthetic_voice': 'local Windows zh-CN TTS',
        'duration_seconds': sum(durations), 'slide_durations': durations, 'reference_sentences': captions,
        'video_sha256': hashlib.sha256(video.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'video': str(video), 'seconds': sum(durations), 'sentences': len(captions), 'work': str(work)}, ensure_ascii=False))


if __name__ == '__main__': main()
