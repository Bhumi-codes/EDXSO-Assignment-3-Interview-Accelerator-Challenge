"""Post-recording local Silero VAD. Audio is decoded in memory and never retained."""
from functools import lru_cache
from pathlib import Path
import io
import math

@lru_cache(maxsize=1)
def model():
    import onnxruntime as ort
    ort.disable_telemetry_events()
    opts=ort.SessionOptions();opts.inter_op_num_threads=1;opts.intra_op_num_threads=1
    return ort.InferenceSession(str(Path(__file__).parent/'assets/silero_vad.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])

def internal_gaps(intervals):
    return [{'start':round(left[1],3),'end':round(right[0],3),'duration_seconds':round(right[0]-left[1],3)}
            for left,right in zip(intervals,intervals[1:]) if right[0]-left[1]>6]

def align_gaps(gaps,words):
    valid=[]
    for w in words or []:
        try:
            start,end=float(w['start']),float(w['end']);text=w['word'].strip()
            if text and math.isfinite(start) and math.isfinite(end) and 0<=start<=end:valid.append({'start':start,'end':end,'word':text})
        except (ValueError,KeyError,TypeError):continue
    valid.sort(key=lambda w:w['start'])
    result=[]
    for gap in gaps[:64]:
        left=[i for i,w in enumerate(valid) if w['end']<=gap['start']+0.5]
        right=[i for i,w in enumerate(valid) if w['start']>=gap['end']-0.5]
        li=left[-1] if left else None;ri=right[0] if right else None
        aligned=li is not None and ri is not None and li<ri and abs(valid[li]['end']-gap['start'])<=1.5 and abs(valid[ri]['start']-gap['end'])<=1.5
        result.append({**gap,'id':f'pause-{len(result)+1}','aligned':aligned,
            'before':' '.join(w['word'] for w in valid[max(0,li-11):li+1]) if li is not None else '',
            'after':' '.join(w['word'] for w in valid[ri:ri+12]) if ri is not None else ''})
    return result

def measure_pauses(data,words):
    if len(data)<64 or not (data.startswith((b'RIFF',b'OggS',b'\x1aE\xdf\xa3')) or b'ftyp' in data[:32]):
        return {'version':'silero-v6.2.1','status':'unavailable','pauses':[]}
    try:
        import av
        import numpy as np
        chunks=[];length=0
        with av.open(io.BytesIO(data)) as container:
            resampler=av.AudioResampler(format='flt',layout='mono',rate=16000)
            for frame in container.decode(audio=0):
                for sample in resampler.resample(frame):
                    values=sample.to_ndarray().reshape(-1);length+=len(values)
                    if length>16000*1200:raise ValueError('Recording exceeds pause-analysis capacity')
                    chunks.append(values)
            for sample in resampler.resample(None):chunks.append(sample.to_ndarray().reshape(-1))
        audio=np.concatenate(chunks).astype(np.float32) if chunks else np.array([],dtype=np.float32)
        if len(audio)<512:raise ValueError('No samples')
        session=model();state=np.zeros((2,1,128),dtype=np.float32);context=np.zeros((1,64),dtype=np.float32)
        intervals=[];start=None;last_positive=0
        for offset in range(0,len(audio),512):
            frame=audio[offset:offset+512]
            if len(frame)<512:frame=np.pad(frame,(0,512-len(frame)))
            sample=np.concatenate([context,frame.reshape(1,-1)],axis=1)
            probability,state=session.run(None,{'input':sample,'state':state,'sr':np.array(16000,dtype=np.int64)})
            context=sample[:,-64:];p=float(probability[0][0]);time=offset/16000
            if p>=.5:
                if start is None:start=time
                last_positive=min((offset+512)/16000,len(audio)/16000)
            elif start is not None and p>=.35:last_positive=min((offset+512)/16000,len(audio)/16000)
            elif start is not None and time-last_positive>=.25:
                if last_positive-start>=.16:intervals.append((start,last_positive))
                start=None
        if start is not None and last_positive-start>=.16:intervals.append((start,last_positive))
        if not intervals:raise ValueError('No confident speech')
        return {'version':'silero-v6.2.1','status':'measured','pauses':align_gaps(internal_gaps(intervals),words),
                'speech_seconds':round(sum(b-a for a,b in intervals),3)}
    except Exception:
        # Missing/failed measurement must never become a candidate deduction or block transcription.
        return {'version':'silero-v6.2.1','status':'unavailable','pauses':[]}
