from uuid import UUID
from .analysis_schemas import RoleProfile,CandidateProfile,MatchOutput
from .fit import canonical_requirements,validate_candidate,calculate_fit,source_lines
from .llm import structured

async def analyse_documents(session_id:UUID,jd:str,resume:str):
    role,requirements,t1=await structured(RoleProfile,
        'Extract every role field. Requirements must be atomic and deduplicated: use one canonical key per distinct skill '
        '(e.g. python, sql), never repeat it as a keyword and competency requirement. Required/preferred must be explicit '
        'in the JD to be scored; importance not stated is unspecified. Inferred concepts can guide preparation only. '
        'Separate explicit eligibility conditions (e.g. degree/visa/location) as eligibility. At most 40 requirements.',
        {'source_lines':source_lines(jd)},lambda parsed:canonical_requirements(parsed,jd,session_id))
    candidate,_,t2=await structured(CandidateProfile,
        'Extract evidence-backed candidate skills, experience, projects, achievements, education, certifications and '
        'claims needing clarification. Claims to probe are neutral, not allegations. Keep at most 70 findings.',
        {'source_lines':source_lines(resume)},lambda parsed:validate_candidate(parsed,resume))
    proposed,fit,t3=await structured(MatchOutput,
        'Compare every canonical requirement exactly once using requirement_key. Strong requires a concrete relevant '
        'implementation/experience example. A technology name alone is normally partial. Calling an API does not establish '
        'building an API. Missing evidence is not_evidenced: say Not evidenced in the resume, never cannot do. '
        'Support strong/partial with exact resume excerpts. Explain gaps and give specific practice tasks. '
        'Do not score or calculate percentages; Python does that.',
        {'source_lines':source_lines(resume),'requirements':[{k:r[k] for k in ('key','label','category','importance','origin','evidence')} for r in requirements]},
        lambda parsed:calculate_fit(requirements,parsed,resume))
    return role.model_dump(),candidate.model_dump(),fit,{'prompt_version':'analysis-v2-source-lines','calls':t1+t2+t3}
