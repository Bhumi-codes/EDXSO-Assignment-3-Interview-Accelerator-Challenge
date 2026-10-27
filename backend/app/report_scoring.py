"""Versioned, deterministic preparation estimates from saved rubric assessments."""
from collections import defaultdict
from statistics import mean
import math

POLICY_VERSION='report-v4-dimension-skips'
DIMENSIONS={
 'role_fit':'Role fit','technical_knowledge':'Technical knowledge','problem_solving':'Problem solving',
 'communication':'Communication','confidence':'Confidence — clarity and ownership','depth':'Depth of understanding',
 'behavioural_fit':'Behavioural fit'}
PRACTICE={
 'role_fit':('Connect two documented experiences to the role responsibilities.','Explain the connection without adding unsupported experience.'),
 'technical_knowledge':('Review one relevant concept, then explain it using a small example.','Explain the concept and identify one limitation without relying on terminology alone.'),
 'problem_solving':('Work through a small job-relevant problem, stating assumptions and checking the result.','Explain why the approach fits and compare one reasonable alternative.'),
 'communication':('Record a concise answer with a clear point, supporting example and conclusion.','A listener can identify the main point and your contribution.'),
 'confidence':('Explain one contribution, what you know and what you would need to verify.','Distinguish your work, library/provider behaviour and acknowledged limits.'),
 'depth':('Revisit a supported project decision and test one changed constraint.','Explain why the original choice fits and when you would reconsider it.'),
 'behavioural_fit':('Prepare a real collaboration example using situation, action and outcome.','Identify your action, others’ roles and what you learned without inventing an incident.')}
def rounded(value):
    return round(value,2) if value is not None else None

def aggregate_report(turns,evaluations,requirements,matches,job_fit,status,communication=None):
    by_id={turn['id']:turn for turn in turns}
    valid={};invalid=0
    for turn in turns:
        evaluation=evaluations.get(turn['id'])
        if turn['status']!='answered' or not evaluation:continue
        if evaluation.get('assessment_label')=='Unassessable':continue
        targets=set(turn.get('target_competencies',[]));scores={}
        for entry in evaluation.get('competency_scores',[]):
            key=entry.get('competency');score=entry.get('score')
            if key not in DIMENSIONS or key not in targets or key in scores or isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=4:
                invalid+=1;continue
            scores[key]=float(score)
        if scores:valid[turn['id']]=scores
    def root(turn):
        seen={turn['id']}
        while turn.get('parent_turn_id') in by_id:
            parent=by_id[turn['parent_turn_id']]
            if parent['id'] in seen or parent['level']!=turn['level']:break
            seen.add(parent['id']);turn=parent
        return turn
    chains=defaultdict(list)
    for turn in turns:
        if turn['id'] in valid:chains[root(turn)['id']].append(turn)
    topics=defaultdict(list)
    for root_id,members in chains.items():
        parent=by_id[root_id];scores=defaultdict(list);ids=defaultdict(list)
        for turn in members:
            for key,score in valid[turn['id']].items():
                scores[key].append(score);ids[key].append(turn['id'])
        topics[(parent['level'],parent.get('topic_key','').strip().casefold() or root_id)].append({
            'root_id':root_id,'scores':{key:mean(values) for key,values in scores.items()},
            'turn_ids':[turn['id'] for turn in members],'dimension_turn_ids':dict(ids),
            'prompted_improvement':[key for key,values in scores.items() if len(values)>1 and values[-1]>values[0]]})
    units=[]
    for (level,topic),group in topics.items():
        keys={key for chain in group for key in chain['scores']}
        units.append({'id':f'{level}:{topic}','level':level,'topic_key':topic,
            'root_turn_ids':[chain['root_id'] for chain in group],
            'turn_ids':list(dict.fromkeys(turn_id for chain in group for turn_id in chain['turn_ids'])),
            'scores':{key:mean(chain['scores'][key] for chain in group if key in chain['scores']) for key in keys},
            'dimension_turn_ids':{key:list(dict.fromkeys(turn_id for chain in group for turn_id in chain['dimension_turn_ids'].get(key,[]))) for key in keys},
            'prompted_improvement':sorted({key for chain in group for key in chain['prompted_improvement']})})
    dimensions=[]
    raw_dimensions={}
    for key,label in DIMENSIONS.items():
        assessed=[unit for unit in units if key in unit['scores']]
        value=mean(unit['scores'][key] for unit in assessed) if assessed else None
        if key=='communication' and communication is not None:
            # Each accepted answer has equal weight, independently of topic chains.
            language=[(turn,communication[turn['id']]) for turn in turns
                if turn['status']=='answered' and turn['id'] in communication]
            value=mean(entry['score'] for _,entry in language) if language else None
            assessed=[{'dimension_turn_ids':{'communication':[turn['id']]}} for turn,_ in language]
        raw_dimensions[key]=value
        dimensions.append({'key':key,'label':label,'score_0_4':rounded(value),
            'score_percent':rounded(value*25) if value is not None else None,
            'assessed_units':len(assessed),'turn_ids':list(dict.fromkeys(t for unit in assessed for t in unit['dimension_turn_ids'][key])),
            'applicability':'assessed_for_this_role' if assessed else 'not_assessed_applicability_unconfirmed' if key=='technical_knowledge' else 'not_assessed'})
    assessed_values=[value for value in raw_dimensions.values() if value is not None]
    answer_quality=mean(assessed_values)*25 if assessed_values else None
    explicit_skips=sum(t['status']=='skipped' for t in turns)
    assessed_ids=set(valid)
    if communication is not None:
        assessed_ids.update(t['id'] for t in turns if t['status']=='answered' and t['id'] in communication)
    assessed_answers=len(assessed_ids)
    skip_factor=assessed_answers/(assessed_answers+explicit_skips) if assessed_answers+explicit_skips else 1
    adjusted_values=[]
    for dimension in dimensions:
        base=raw_dimensions[dimension['key']]
        dimension['answer_quality_0_4']=rounded(base)
        dimension['answer_quality_percent']=rounded(base*25) if base is not None else None
        dimension['skip_factor']=skip_factor
        if base is not None:
            adjusted=base*skip_factor
            adjusted_values.append(adjusted)
            dimension['score_0_4']=rounded(adjusted)
            dimension['score_percent']=rounded(adjusted*25)
    # The overall score is now the mean of the adjusted dimensions. Never apply
    # the skip factor a second time, or penalise unasked/early-ended questions.
    overall=mean(adjusted_values)*25 if adjusted_values else 0 if explicit_skips and not any(t['status']=='answered' for t in turns) else None
    required=[r for r in requirements if r.get('origin')=='explicit' and r.get('importance')=='required' and r.get('category') not in ('eligibility','qualification')]
    match_by_key={m['requirement_key']:m for m in matches}
    unverified=[]
    for requirement in required:
        key=requirement['key'];doc=match_by_key.get(key,{})
        corresponding=[unit for unit in units if unit['topic_key']==key.casefold()]
        if doc.get('status') in ('partial','not_evidenced') and not any(mean(unit['scores'].values())>=2 for unit in corresponding):
            unverified.append({'key':key,'label':requirement['label'],'document_status':doc.get('status')})
    levels=[{'number':n,'asked':sum(t['level']==n for t in turns),
        'answered':sum(t['level']==n and t['status']=='answered' for t in turns),
        'evaluated':sum(t['level']==n and t['id'] in valid for t in turns),
        'budget':{1:4,2:4,3:7}[n]} for n in (1,2,3)]
    pending=sum(turn['status']=='answered' and turn['id'] not in evaluations for turn in turns)
    unassessable=sum(turn['status']=='answered' and turn['id'] in evaluations and turn['id'] not in valid for turn in turns)
    coverage={'asked':len(turns),'answered':sum(t['status']=='answered' for t in turns),
        'skipped':sum(t['status']=='skipped' for t in turns),
        'unanswered':sum(t['status'] in ('asked','unanswered_at_finalisation') for t in turns),
        'evaluated':len(valid),'pending_evaluations':pending,'unassessable':unassessable,
        'total_budget':15,'levels':levels,'evidence_units':len(units),
        'assessed_dimensions':sum(value is not None for value in raw_dimensions.values()),
        'unassessed_dimensions':[key for key,value in raw_dimensions.items() if value is None],
        'required_unverified':unverified}
    communication_pending=sum(t['status']=='answered' and bool(t.get('answer')) and t['id'] not in communication for t in turns) if communication is not None else 0
    coverage['pending_communication']=communication_pending
    # Readiness concludes from seven assessed dimensions. Pending individual
    # assessments and interview-length coverage remain visible, not hard blockers.
    reasons=[]
    if coverage['unassessed_dimensions']:reasons.append('One or more competency dimensions have not been assessed.')
    if overall is None:reasons.append('No assessable interview evidence.')
    raw=(0.8*overall+0.2*job_fit if job_fit is not None else overall) if overall is not None else None
    sufficient=not reasons;caps=[]
    weak=[DIMENSIONS[key] for key in ('technical_knowledge','problem_solving','depth') if raw_dimensions[key] is not None and raw_dimensions[key]<2]
    if weak:caps.append({'maximum':64,'reason':'Important assessed gaps: '+', '.join(weak)})
    if any(d['assessed_units']<2 for d in dimensions):caps.append({'maximum':79,'reason':'Strong Candidate requires two independent evidence units per dimension.'})
    if unverified:caps.append({'maximum':79,'reason':'Some explicit required areas still lack sufficient documented or interview evidence.'})
    # A directly assessed required topic with major gaps also constrains readiness.
    if any(unit['topic_key'] in {r['key'].casefold() for r in required} and mean(unit['scores'].values())<2 for unit in units):
        caps.append({'maximum':64,'reason':'A directly assessed required topic has a major demonstrated gap.'})
    score=min([raw]+[cap['maximum'] for cap in caps]) if sufficient else None
    label=('Not Ready' if score<50 else 'Needs Preparation' if score<65 else 'Interview Ready' if score<80 else 'Strong Candidate') if score is not None else 'Insufficient evidence to establish readiness'
    objectives=[]
    requirement_by_key={r['key'].casefold():r for r in requirements}
    for unit in units:
        requirement=requirement_by_key.get(unit['topic_key'],{})
        weight=3 if requirement.get('origin')=='explicit' and requirement.get('importance')=='required' else 1 if requirement.get('importance')=='preferred' else 2
        rating=mean(unit['scores'].values())
        weakest=min(unit['turn_ids'],key=lambda turn_id:mean(valid[turn_id].values()))
        feedback=evaluations[weakest]
        rationale=feedback.get('reasoning','').strip()
        gaps=[str(value).strip() for value in feedback.get('improvements',[])[:3] if str(value).strip()]
        key=min(unit['scores'],key=unit['scores'].get)
        action=PRACTICE[key][0]
        objectives.append({'id':'unit:'+unit['id'],'title':requirement.get('label') or by_id[unit['root_turn_ids'][0]].get('topic_key','Assessed topic').replace('_',' ').replace('-',' ').capitalize(),
            'source':'interview','why':('Reinforce demonstrated strengths. ' if rating>=3 else 'Demonstrated gap: ')+(rationale[:450] or 'Review the cited answer and saved assessment.')+(' To improve: '+'; '.join(gaps)[:450] if gaps else ''),
            'review_topics':[],'assessment_gaps':gaps,
            'priority_value':(4-rating)*weight+.25,'turn_ids':[weakest]+[key for key in unit['turn_ids'] if key!=weakest],
            'topic_key':unit['topic_key'],
            'practice_task':action,'success_check':PRACTICE[key][1]})
    # Preparation is a set of learning objectives, so repeated assessment units
    # on the same topic do not become duplicate priorities. Scoring units stay intact.
    merged={}
    for objective in objectives:
        key=objective['topic_key']
        previous=merged.get(key)
        if previous is None:merged[key]=objective;continue
        primary,other=(objective,previous) if objective['priority_value']>previous['priority_value'] else (previous,objective)
        primary={**primary,'turn_ids':list(dict.fromkeys(primary['turn_ids']+other['turn_ids'])),
            'assessment_gaps':list(dict.fromkeys(primary['assessment_gaps']+other['assessment_gaps']))}
        primary['why']=(primary['why']+' Related saved gap: '+'; '.join(other['assessment_gaps']))[:900]
        merged[key]=primary
    objectives=list(merged.values())
    for gap in unverified:
        if gap['key'].casefold() in merged:
            objective=merged[gap['key'].casefold()]
            objective['priority_value']=max(objective['priority_value'],4.5)
            continue
        objectives.append({'id':'requirement:'+gap['key'],'title':gap['label'],'source':'document_gap',
            'why':'An explicit required area is only partly evidenced or not evidenced in the resume and has not been sufficiently established in the interview. This is not proof of inability.',
            'priority_value':4.5,'turn_ids':[],'practice_task':'Review this requirement and prepare a truthful example or a small practical exercise demonstrating it.',
            'success_check':'Explain the relevant work and its limits without claiming experience you have not demonstrated.'})
    for key in coverage['unassessed_dimensions']:
        objectives.append({'id':'coverage:'+key,'title':DIMENSIONS[key],'source':'coverage_gap',
            'why':'Not assessed in this attempt; do not interpret missing evidence as a low score.',
            'priority_value':2,'turn_ids':[],'practice_task':PRACTICE[key][0],'success_check':PRACTICE[key][1]})
    objectives=sorted(objectives,key=lambda obj:(-obj['priority_value'],obj['id']))[:6]
    for rank,objective in enumerate(objectives,1):
        objective['rank']=rank;objective['priority_value']=rounded(objective['priority_value'])
    measured=[t for t in turns if t['status']=='answered' and t.get('mode')=='voice' and t.get('raw_transcript') is not None and t.get('filler_count') is not None]
    limits=['Preparation estimates from saved rubric assessments, not a hiring prediction.',
        'Generated question and evaluation quality affects these results. Semantic repetition across different topic labels remains a known limitation.',
        'Some saved question premises may assume unclaimed experience. Review them alongside the actual answer before relying on the associated rating; question-quality correction is deferred.',
        'Exact same-topic chains within a level are combined; semantic equivalence across differently named topics is not automatically established.',
        'Eligibility conditions require separate verification.']
    if status=='ended_early':limits.append('This interview ended early; unasked and unanswered questions are not scored as failures.')
    if invalid:limits.append('Invalid historical score entries were excluded from aggregation.')
    return {'policy_version':POLICY_VERSION,'documented_job_fit':rounded(job_fit),'overall_score':rounded(overall),'answer_quality_score':rounded(answer_quality),
        'skip_adjustment':{'assessed_answers':assessed_answers,'explicit_skips':explicit_skips,'factor':skip_factor,
            'explanation':'Each assessed dimension = its answer-quality score × assessed answers / (assessed answers + explicit skips). Overall score is the equal average of these adjusted dimensions, with no further skip deduction. Each skipped question counts once in the shared factor; unasked questions, unanswered questions at early ending, and ending early itself add no penalty.'},'competencies':dimensions,
        'coverage':coverage,'readiness':{'label':label,'score':rounded(score),
            'raw_formula_score':rounded(raw) if sufficient else None,'coverage_sufficient':sufficient,
            'reasons':reasons,'caps':caps,'policy':'dimension-coverage-v1',
            'formula':('80% skip-adjusted interview performance + 20% documented job fit, then explicit readiness safeguards.' if job_fit is not None else 'Skip-adjusted interview performance only: documented job fit is unavailable and no replacement value is invented.')+' Readiness is concluded when all seven dimensions have scores; pending individual assessments do not block it.'},
        'evidence_units':units,'priorities':objectives,
        'fillers':{'measured_answers':len(measured),'total_detected':sum(t['filler_count'] for t in measured),
            'unmeasured_answers':coverage['answered']-len(measured),
            'note':'Detected in raw transcripts only; STT may omit fillers. Typed answers have no spoken-filler measurement. Normal fillers are penalty-free. In new assessments, the same redundant filler/expression occurring at least five times incurs a 2 percentage-point deduction per distinct redundant expression per answer.'},
        'limitations':limits,
        'communication':{'policy':'Grammar and sentence structure form the base. Per answer: each distinct repeated filler/expression at least 5 times: minus 2 percentage points once; confirmed unfinished-sentence audio pause over 6s: minus 2 points, or over 25s: minus 5 points maximum. Pause deductions do not stack. Scores are floored at zero. Only internal speech gaps within the recording are measured; leading and trailing silence are excluded. Ordinary fillers, completed-sentence pauses and missing measurements incur no deduction. Legacy ratings remain saved.','assessed_answers':len(communication or {}),'pending_answers':communication_pending,'answer_scores':communication or {}},
        'calculation':('Communication averages every independently assessed submitted answer equally and converts 0–4 to 0–100. ' if communication is not None else '')+'Other dimensions: average saved scores within each main-question/follow-up chain; combine same-topic chains within a level; average these evidence units per competency; convert each assessed competency to 0–100, then multiply each by assessed answers / (assessed answers + explicit skips). Overall score is the equal average of the adjusted competencies; no second skip deduction is applied. Original answer-quality ratings are preserved. Unassessed dimensions are excluded, not zero. Unasked questions and ending early have no penalty.'}
