"""Coverage guidance from actual saved assessments; never fills missing scores."""
import math
from .controller import BUDGETS
from .report_scoring import DIMENSIONS


def competency_coverage(turns, evaluations, communication, level):
    evidence={key:[] for key in DIMENSIONS}
    attempted={key:[] for key in DIMENSIONS}
    for turn in turns:
        ref=f"L{turn['level']}Q{turn['number']}"
        targets=set(turn.get('target_competencies',[])) & set(DIMENSIONS)
        for key in targets:attempted[key].append(ref)
        if turn['status']!='answered':continue
        evaluation=evaluations.get(turn['id'],{})
        if evaluation.get('assessment_label')!='Unassessable':
            for score in evaluation.get('competency_scores',[]):
                key,value=score.get('competency'),score.get('score')
                if key=='communication':continue # Independent language assessment is authoritative.
                if key in targets and not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and 0<=value<=4:
                    if ref not in evidence[key]:evidence[key].append(ref)
        if turn['id'] in communication:evidence['communication'].append(ref)
    missing=[key for key,refs in evidence.items() if not refs]
    preferred={1:['role_fit','confidence','behavioural_fit'],2:['technical_knowledge','problem_solving','behavioural_fit','confidence'],3:list(DIMENSIONS)}[level]
    priority=[key for key in preferred if key in missing and key!='communication']
    remaining=max(0,sum(BUDGETS.values())-len(turns))
    missing_question_dimensions=[key for key in missing if key!='communication']
    reserve=level>=2 and bool(missing_question_dimensions) and remaining<=len(missing_question_dimensions)+1
    if reserve:priority=missing_question_dimensions
    return {
        'dimensions':[{'key':key,'label':label,'assessed_question_refs':evidence[key],
            'attempted_question_refs':attempted[key],'status':'assessed' if evidence[key] else 'unassessed'} for key,label in DIMENSIONS.items()],
        'assessed_dimensions':[key for key,refs in evidence.items() if refs],
        'unassessed_dimensions':missing,'priority_dimensions':priority,
        'remaining_interview_questions':remaining,
        'reserve_for_unassessed':reserve,
        'policy':'Use missing dimensions to choose useful, personalised objectives at this level. A skip or unassessable response leaves a gap. A valid low rating still establishes assessed coverage, not mastery. Communication is assessed independently from every answer; do not ask an artificial language question to fill it. Coverage is guidance, never permission to invent scores or repeat a declined objective.'}
