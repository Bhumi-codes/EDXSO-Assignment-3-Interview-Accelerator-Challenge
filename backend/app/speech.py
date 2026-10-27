import httpx
from .provider_http import provider_client
from .config import get_settings
from .llm import AnalysisUnavailable

MAX_AUDIO_BYTES=8*1024*1024

async def transcribe_audio(data:bytes,filename:str):
    settings=get_settings()
    if not settings.groq_api_key:
        raise AnalysisUnavailable('Transcription is awaiting server setup.')
    if not data or len(data)>MAX_AUDIO_BYTES:
        raise AnalysisUnavailable('Record a short answer under 8 MB and try again.')
    suffix=filename.rsplit('.',1)[-1]
    valid=(suffix=='webm' and data.startswith(b'\x1aE\xdf\xa3') or
           suffix=='wav' and data.startswith(b'RIFF') or
           suffix=='ogg' and data.startswith(b'OggS') or
           suffix in ('mp4','m4a') and b'ftyp' in data[:32])
    if not valid:
        raise AnalysisUnavailable('Unsupported recording format. Try Chrome or Edge, or use the text fallback.')
    try:
        async with provider_client(timeout=60) as client:
            result=await client.post('https://api.groq.com/openai/v1/audio/transcriptions',timeout=60,
                headers={'Authorization':'Bearer '+settings.groq_api_key.get_secret_value()},
                files={'file':(filename,data)},data={'model':settings.groq_stt_model,'response_format':'verbose_json',
                'temperature':'0','language':'en','timestamp_granularities[]':['word','segment']})
    except httpx.HTTPError:
        raise AnalysisUnavailable('Transcription failed to connect. Record again or use the text fallback.') from None
    if result.status_code==429:
        raise AnalysisUnavailable('Transcription quota is temporarily exhausted. Record again after the limit resets, or use text.')
    if result.status_code!=200:
        raise AnalysisUnavailable('Transcription could not process this recording. Record again or use text.')
    try:
        output=result.json()
        text=output.get('text','').strip()
        duration=float(output.get('duration',0))
        segments=output.get('segments',[])
        silent=bool(segments) and all(float(x.get('no_speech_prob',0))>.8 for x in segments)
        if not text or silent:
            raise AnalysisUnavailable('No clear speech was detected. Check the microphone and record again.')
        return {'text':text,'duration':duration,'words':output.get('words',[])}
    except (ValueError,TypeError,KeyError):
        raise AnalysisUnavailable('The transcription response was unreadable. Record again.') from None
