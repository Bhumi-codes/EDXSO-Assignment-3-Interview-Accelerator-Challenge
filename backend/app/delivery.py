"""Observable delivery measurements; no inference of confidence or knowledge."""
from collections import Counter
import re

# Count content-word repetition for inspection, but never penalise necessary topic vocabulary.
EXPRESSIONS=('basically','actually','literally','essentially','obviously','um','uh','erm','you know','i mean','sort of','kind of','like','so')
UNAMBIGUOUS={'basically','um','uh','erm'}

def repetition_observations(text):
    text=re.sub(r'\bum+\b','um',(text or '').lower())
    text=re.sub(r'\buh+\b','uh',text)
    words=re.findall(r"[a-z]+(?:'[a-z]+)?",(text or '').lower())
    counts=Counter(words)
    expressions={phrase:len(re.findall(r'\b'+re.escape(phrase)+r'\b',(text or '').lower())) for phrase in EXPRESSIONS}
    expressions={k:v for k,v in expressions.items() if v}
    return {'expression_counts':expressions,'repeated_words':{k:v for k,v in counts.items() if v>=5},
            'eligible_expressions':{k:v for k,v in expressions.items() if v>=5}}

def delivery_adjustment(turn,confirmed_repetitions,unfinished_pause_ids):
    text=turn.get('raw_transcript') if turn.get('mode')=='voice' else turn.get('answer')
    repetition=repetition_observations(text)
    eligible=repetition['eligible_expressions']
    repeated={k:v for k,v in eligible.items() if k in UNAMBIGUOUS or k in confirmed_repetitions}
    pauses=(turn.get('delivery_metrics') or {}).get('pauses',[]) if turn.get('mode')=='voice' else []
    confirmed=[p for p in pauses if p['id'] in unfinished_pause_ids and p.get('aligned')]
    longest=max((p['duration_seconds'] for p in confirmed),default=0)
    filler_points=2*len(repeated)
    pause_points=5 if longest>25 else 2 if longest>6 else 0
    return {'repetition':repetition,'penalised_expressions':repeated,'confirmed_unfinished_pauses':confirmed,
            'filler_deduction_points':filler_points,'pause_deduction_points':pause_points,
            'total_deduction_points':filler_points+pause_points,
            'pause_measurement_status':(turn.get('delivery_metrics') or {}).get('status','unavailable') if turn.get('mode')=='voice' else 'not_applicable'}
