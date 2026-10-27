import re

BUDGETS={1:4,2:4,3:7}
CHAIN_CAPS={1:1,2:1,3:2}

def permitted_action(level,turns_used,chain_depth,uncovered,recommendation,answer=None):
    if turns_used>=BUDGETS[level]:
        return 'level_complete'
    if BUDGETS[level]-turns_used<=uncovered or chain_depth>=CHAIN_CAPS[level]:
        return 'new_topic'
    # Meaning and conversational routing belong to the model, not phrase matching.
    return recommendation if recommendation in ('clarify','deepen','simplify','new_topic') else 'new_topic'

def filler_count(raw):
    return len(re.findall(r'\b(?:um+|uh+|erm|basically|actually|literally|essentially)\b',raw,re.I)) if raw is not None else None

def normal_question(text):
    return re.sub(r'[^a-z0-9]+',' ',text.lower()).strip()

def validate_question(question,topic,difficulty,previous):
    if (topic is not None and question.topic_key!=topic) or question.difficulty!=difficulty:
        raise ValueError('Respect the procedural topic/difficulty constraints')
    if not question.topic_key.strip() or len(question.topic_key)>200:
        raise ValueError('Save a concise topic key')
    if not 3<=len(question.question_text.split())<=60:
        raise ValueError('Ask one question in 3 to 60 words inclusive')
    if not question.target_competencies or len(set(question.target_competencies))!=len(question.target_competencies):
        raise ValueError('Choose unique assessed competencies')
    if not question.rubric.adequate_criteria or len(question.rubric.adequate_criteria)>6:
        raise ValueError('Save a concise assessment rubric')
    if any(normal_question(old)==normal_question(question.question_text) for old in previous):
        raise ValueError('Do not repeat an existing question')
    return question
