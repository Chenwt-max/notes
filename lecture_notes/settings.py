from __future__ import annotations

import base64
import ctypes
import os
import math
from ctypes import wintypes
from urllib.parse import urlsplit

from .common import DATA, read_json, write_json
from .asr import ASR_MODEL
from .document_model import DOCUMENT_MODEL

SESSION_KEY = ''
DEFAULTS = {'base_url': '', 'model': '', 'input_price': 0., 'output_price': 0., 'budget_per_hour': 1., 'budget_per_note': 1.,
            'input_tokens_per_hour': 180000, 'output_tokens_per_hour': 60000, 'max_output_tokens': 6000,
            'review_notes':True,
            'remember_key': False, 'include_ocr_context':False, 'asr_model': ASR_MODEL, 'device': 'cuda',
            'person_model':'yolox-tiny','formula_model':DOCUMENT_MODEL,'processing_mode':'balanced',
            'cpu_threads':2,'gpu_concurrency':1,'max_concurrent_jobs':0}


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(value, decrypt=False):
    raw = value if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    if decrypt:
        ok = ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target))
    else:
        ok = ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), 'lecture-notes', None, None, None, 0, ctypes.byref(target))
    if not ok:
        raise OSError('Windows密钥保护失败')
    try:
        result = ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)
    return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')


def settings(include_key=False):
    data = {**DEFAULTS, **read_json(DATA/'settings.json', {})}
    data.pop('early_notes',None)
    data['asr_model']=ASR_MODEL
    data['formula_model']=DOCUMENT_MODEL
    key = os.environ.get('LECTURE_API_KEY') or SESSION_KEY
    encrypted = data.pop('encrypted_key', '')
    if not key and encrypted:
        try:
            key = crypt(base64.b64decode(encrypted, validate=True), decrypt=True)
        except (OSError, ValueError, UnicodeError):
            data['key_reentry_required'] = True
    data['has_key'] = bool(key)
    data['cpu_count'] = os.cpu_count() or 1
    if include_key:
        data['api_key'] = key
    return data


def save_settings(value):
    global SESSION_KEY
    old = read_json(DATA/'settings.json', {})
    result = {key: value.get(key, old.get(key, default)) for key, default in DEFAULTS.items()}
    if type(result['review_notes']) is not bool:raise ValueError('笔记复核选项必须为开或关')
    result['asr_model']=value.get('asr_model',ASR_MODEL)
    if result['asr_model']!=ASR_MODEL:raise ValueError('未知的字幕模型')
    if result['processing_mode'] not in {'listening','balanced','fast'}:
        raise ValueError('未知的处理负载模式')
    if result['device'] not in {'cpu','cuda'}:
        raise ValueError('请选择CPU或NVIDIA显卡')
    for name,low,high,label in [('cpu_threads',1,os.cpu_count() or 1,'CPU线程'),
                               ('gpu_concurrency',0,64,'GPU推理并发'),('max_concurrent_jobs',0,128,'课程并发')]:
        if type(result[name]) is not int or not low<=result[name]<=high:
            raise ValueError(f'{label}必须为{low}至{high}之间的整数')
    result['formula_model']=value.get('formula_model',DOCUMENT_MODEL)
    if result['person_model'] not in {'yolox-tiny','yolox-s'} or result['formula_model']!=DOCUMENT_MODEL:
        raise ValueError('未知的本地模型配置')
    for key in ['input_price', 'output_price', 'budget_per_hour', 'budget_per_note', 'input_tokens_per_hour', 'output_tokens_per_hour', 'max_output_tokens']:
        if not isinstance(result[key], (float, int)) or not math.isfinite(result[key]) or result[key] < 0:
            raise ValueError('价格和额度必须为非负数字')
    address = result['base_url']
    try:
        if not isinstance(address, str):raise ValueError()
        if address:
            endpoint = urlsplit(address)
            local_http = endpoint.scheme == 'http' and endpoint.hostname in {'127.0.0.1', 'localhost'}
            if (not endpoint.hostname or endpoint.scheme != 'https' and not local_http
                    or endpoint.username is not None or endpoint.password is not None
                    or endpoint.query or endpoint.fragment or any(c.isspace() for c in address)
                    or endpoint.port is not None and endpoint.port < 1):raise ValueError()
    except ValueError:
        raise ValueError('接口地址必须是完整HTTPS或本机HTTP基础地址，不能包含账号、查询参数或片段') from None
    key = str(value.get('api_key', '')).strip()
    if key:
        SESSION_KEY = key
    if result['remember_key']:
        current = key or settings(True)['api_key']
        if current:
            result['encrypted_key'] = crypt(current)
        elif old.get('encrypted_key'):
            result['encrypted_key'] = old['encrypted_key']
    write_json(DATA/'settings.json', result)
    return settings()
