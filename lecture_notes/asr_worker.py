"""Isolated local Qwen/PyTorch process; no API client or production database access."""
import os
import subprocess
import sys
from pathlib import Path

from .asr import ASR_MODEL,ALIGNER_MODEL,recognize_aligned,process_audio,append_progress,read_progress
from .common import MODELS,read_json,write_json,stamp
from .resources import cpu_threads
from .timing import Timings


class QwenBackend:
    def __init__(self,output,device,threads):
        self.timing=Timings(output,'asr')
        import torch
        from qwen_asr import Qwen3ASRModel
        from silero_vad import load_silero_vad
        torch.set_num_threads(threads);torch.set_num_interop_threads(1)
        if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('GPU不可用，请在设置中选择CPU')
        dtype=torch.bfloat16 if device=='cuda' else torch.float32
        options={'dtype':dtype,'device_map':'cuda:0' if device=='cuda' else 'cpu','attn_implementation':'sdpa'}
        with self.timing.measure('model_load'):
            self.model=Qwen3ASRModel.from_pretrained(str(MODELS/ASR_MODEL),**options,
                forced_aligner=str(MODELS/ALIGNER_MODEL),forced_aligner_kwargs=options,
                max_inference_batch_size=1,max_new_tokens=1024)
            self.vad=load_silero_vad()
        instrument_model(self.model,self.timing)
        self.output=output;self.device=device;self.dtype=str(dtype)

    def recognize(self,path,start,end):
        import torch
        import soundfile as sf
        from silero_vad import get_speech_timestamps
        work=self.output/'asr_work';work.mkdir(exist_ok=True)
        wav=work/'chunk.wav'
        try:
            self.timing.call('audio_decode',subprocess.run,['ffmpeg','-v','error','-y','-threads',str(cpu_threads()),'-filter_threads','1',
                '-ss',str(start),'-i',path,'-t',str(end-start),'-vn','-ac','1','-ar','16000',
                '-threads',str(cpu_threads()),str(wav)],check=True,capture_output=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            audio,sr=sf.read(wav,dtype='float32')
            speech=self.timing.call('vad',get_speech_timestamps,torch.from_numpy(audio),self.vad,sampling_rate=sr,
                                         min_silence_duration_ms=500,speech_pad_ms=100)
            if not audio.any():return {'text':'','words':[],'speech_intervals':[]}
            def infer(samples,rate):
                result=self.timing.call('transcribe_total',self.model.transcribe,audio=(samples,rate),language='Chinese',context='',return_time_stamps=True)[0]
                return {'text':result.text,'items':[{'text':w.text,'start_time':w.start_time,'end_time':w.end_time} for w in (result.time_stamps or [])]}
            def report(event):
                dest=self.output/'asr_recovery.json'
                events=read_json(dest,[])
                write_json(dest,[*events[-99:],{'window_start':start,'window_end':end,**event}])
                progress=read_progress(self.output)
                if progress:
                    append_progress(self.output,progress['progress'],
                        f'检测到识别异常，正在短段重识别 {stamp(start+event["start"])}—{stamp(start+event["end"])}')
            def check():
                if (self.output/'asr.stop').exists():raise InterruptedError('paused')
            result=recognize_aligned(audio,sr,infer,report,check)
            return {**result,'speech_intervals':[[s['start']/sr,s['end']/sr] for s in speech]}
        finally:wav.unlink(missing_ok=True)

    def runtime(self):
        import torch
        return {'torch':torch.__version__,'precision':self.dtype,'attention':'sdpa','batch_size':1,
                'chunk_seconds':60,'overlap_seconds':2,'context':'','vad':'Silero VAD 6.2.3',
                'peak_allocated_mib':torch.cuda.max_memory_allocated()/1024**2 if self.device=='cuda' else None,
                'peak_reserved_mib':torch.cuda.max_memory_reserved()/1024**2 if self.device=='cuda' else None}


def instrument_model(model,timing):
    # Wrap calls without changing SDK chunking, decoding or alignment options.
    recognize=model._infer_asr
    align=model.forced_aligner.align
    model._infer_asr=lambda *a,**kw:timing.call('recognition',recognize,*a,**kw)
    model.forced_aligner.align=lambda *a,**kw:timing.call('alignment',align,*a,**kw)


def main():
    output=Path(sys.argv[1]).resolve()
    request=read_json(output/'asr_request.json')
    os.environ['LECTURE_CPU_THREADS']=str(request['cpu_threads'])
    for key in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:os.environ[key]=str(request['cpu_threads'])
    def check():
        if (output/'asr.stop').exists():raise InterruptedError('paused')
    def callback(progress,message):append_progress(output,progress,message)
    process_audio(request,output,callback,check,lambda:QwenBackend(output,request['device'],request['cpu_threads']))


if __name__=='__main__':main()
