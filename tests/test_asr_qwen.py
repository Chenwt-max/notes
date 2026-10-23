import pytest

from lecture_notes import asr,settings
from lecture_notes.common import write_json


def test_alignment_keeps_punctuation_spaces_and_equation_symbols():
    text='最小二乘，x = 1。'
    items=[{'text':c,'start_time':i*.2,'end_time':(i+1)*.2} for i,c in enumerate(['最','小','二','乘','x','1'])]
    words=asr.aligned_words(text,items,2)
    assert ''.join(w['word'] for w in words)==text
    assert all('probability' not in w for w in words)
    captions=asr.caption_segments(words)
    assert ''.join(s['text'] for s in captions)==text
    assert captions[0]['end']==pytest.approx(1.2)


@pytest.mark.parametrize('items',[
    [{'text':'错','start_time':0,'end_time':1}],
    [{'text':'正','start_time':0,'end_time':1}],
    [{'text':'正确','start_time':float('nan'),'end_time':1}],
    [{'text':'正确','start_time':0,'end_time':4}],
    [{'text':'正','start_time':1,'end_time':1.2},{'text':'确','start_time':.5,'end_time':1}],
])
def test_alignment_rejects_text_loss_and_bad_timing(items):
    with pytest.raises(ValueError):asr.aligned_words('正确',items,2)


def test_alignment_recovery_redecodes_bad_audio_instead_of_clamping_or_dropping_text():
    calls=[];events=[]
    def infer(audio,sr):
        calls.append(list(audio))
        if len(calls)==1:
            return {'text':'错误循环','items':[{'text':'错误循环','start_time':0,'end_time':30}]}
        return {'text':'甲' if audio[0]==0 else '乙',
                'items':[{'text':'甲' if audio[0]==0 else '乙','start_time':2,'end_time':3}]}
    result=asr.recognize_aligned(list(range(20)),1,infer,events.append,lambda:None)
    assert len(calls)==3 and calls[1]==list(range(11)) and calls[2]==list(range(9,20))
    assert result['text']=='甲乙' and [w['start'] for w in result['words']]==[2,11]
    assert len(events)==1 and '超出' in events[0]['error']


def test_alignment_recovery_is_bounded_and_honors_stop():
    calls=[]
    def bad(audio,sr):
        calls.append(len(audio));return {'text':'错','items':[{'text':'错','start_time':0,'end_time':1000}]}
    with pytest.raises(ValueError,match='短段重识别'):
        asr.recognize_aligned(list(range(64)),1,bad,lambda e:None,lambda:None)
    assert len(calls)==4
    def stop():raise InterruptedError('paused')
    with pytest.raises(InterruptedError):
        asr.recognize_aligned([1]*20,1,bad,lambda e:None,stop)
    assert len(calls)==4


def test_alignment_accepts_small_edge_rounding_without_negative_word_duration():
    items=[{'text':'正','start_time':-.1,'end_time':-.05},
           {'text':'确','start_time':1.95,'end_time':2.05}]
    words=asr.validated_recognition('正确',items,2)
    assert all(0<=w['start']<=w['end']<=2 for w in words)
    with pytest.raises(ValueError,match='有效时长'):
        asr.validated_recognition('正',items[:1],2)


def test_chunk_windows_keep_context_without_bridging_unselected_video():
    request={'windows':[[10,85],[100,110]],'chunk_seconds':60,'overlap_seconds':2}
    assert asr.audio_parts(request)==[(10,70,10,72),(70,85,68,85),(100,110,100,110)]


def test_overlap_owns_each_word_once_and_cleans_success_cache(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    monkeypatch.setenv('LECTURE_PROCESSING_MODE','fast')
    request=asr.make_request(source,[[0,65]],'cuda')
    messages=[]
    class Backend:
        def recognize(self,path,start,end):
            assert messages[-1].startswith('正在识别')
            return {'text':'甲乙丙','speech_intervals':[[max(0,58-start),min(65,end)-start]],
                    'words':[{'start':t-start,'end':t+.4-start,'word':c} for t,c in [(59,'甲'),(60,'乙'),(61,'丙')]
                             if start<=t and t+.4<=end]}
        def runtime(self):return {}
    rows=asr.process_audio(request,tmp_path,lambda _,message:messages.append(message),lambda:None,Backend)
    assert ''.join(r['text'] for r in rows)=='甲乙丙'
    words=[w for r in rows for w in r['words']]
    assert [w['start'] for w in words]==[59,60,61]
    assert not (tmp_path/'asr_chunks').exists()
    monkeypatch.setattr(asr,'models_ready',lambda:False)
    # A completed result is reusable on CPU even when model weights are unavailable.
    assert asr.transcribe(source,[[0,65]],tmp_path,lambda *_:None,lambda:None,'cpu')==rows
    source.write_bytes(b'changed source')
    with pytest.raises(RuntimeError,match='模型未就绪'):
        asr.transcribe(source,[[0,65]],tmp_path,lambda *_:None,lambda:None,'cpu')


def test_resume_recomputes_invalid_timing_cache_without_discarding_good_minutes(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    monkeypatch.setenv('LECTURE_PROCESSING_MODE','fast')
    request=asr.make_request(source,[[0,120]],'cuda');key=asr.request_key(request)
    cache=tmp_path/'asr_chunks';cache.mkdir()
    for core_a,core_b,a,b in asr.audio_parts(request):
        text='原字幕' if core_a==60 else '保留'
        write_json(cache/f'qwen_v3_{asr.digest([key,a,b])[:24]}.json',
            {'text':text,'words':[{'word':text,'start':2,'end':100 if core_a==60 else 3}],
             'speech_intervals':[],'request_key':key,'device':'cuda'})
    calls=[]
    class Backend:
        def recognize(self,path,start,end):
            calls.append((start,end));return {'text':'恢复','words':[{'word':'恢复','start':2,'end':3}],'speech_intervals':[]}
        def runtime(self):return {}
    rows=asr.process_audio(request,tmp_path,lambda *_:None,lambda:None,Backend)
    assert calls==[(58,120)] and ''.join(s['text'] for s in rows)=='保留恢复'


def test_default_migrates_saved_model_without_touching_other_settings(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'DATA',tmp_path)
    write_json(tmp_path/'settings.json',{'asr_model':'previous-model','cpu_threads':1})
    assert settings.settings()['asr_model']==asr.ASR_MODEL
    saved=settings.save_settings({'max_concurrent_jobs':2})
    assert saved['asr_model']==asr.ASR_MODEL and saved['cpu_threads']==1
    with pytest.raises(ValueError,match='未知的字幕模型'):settings.save_settings({'asr_model':'unknown'})
