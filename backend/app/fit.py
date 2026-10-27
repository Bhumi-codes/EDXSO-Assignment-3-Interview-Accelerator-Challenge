import re
import json
from uuid import uuid5
from .analysis_schemas import RoleProfile, CandidateProfile, MatchOutput

def concept_key(value):
    key = re.sub(r'[^a-z0-9+#]+',' ',value.lower()).strip()
    aliases = {'python programming':'python','python language':'python','postgres':'postgresql',
               'postgresql database':'postgresql','react js':'react','reactjs':'react',
               'javascript programming':'javascript','js':'javascript','sql language':'sql'}
    return aliases.get(key,key)

class SourceEvidenceError(ValueError):
    def __init__(self, excerpt):
        super().__init__('Source excerpt is absent from the document')
        self.invalid_excerpts=excerpt if isinstance(excerpt,list) else [excerpt]
        self.repair_feedback='This proposed excerpt is not present verbatim in its source: '+json.dumps(excerpt)+'. Use the valid source_lines ID for the evidence, or omit the finding if absent.'

def source_lines(source):
    parts=[]
    for line in re.split(r'(?<=[.;])\s+|\n+',source):
        line=line.strip()
        if line:
            parts.extend(line[start:start+500] for start in range(0,len(line),500))
    return {f'S{index:03d}':line for index,line in enumerate(parts,1)}

def excerpt_location(excerpt, source):
    if isinstance(excerpt,str) and re.fullmatch(r'S\d{3,}',excerpt):
        original=source_lines(source).get(excerpt)
        if not original:
            raise SourceEvidenceError(excerpt)
        excerpt=original
    if not excerpt:
        raise SourceEvidenceError(excerpt)
    if excerpt in source:
        start=source.index(excerpt)
        end=start+len(excerpt)
    else:
        # PDF line wrapping and capitalization do not change the evidence.
        # Preserve punctuation/words, then return the actual original source slice.
        pattern=r'\s+'.join(re.escape(part) for part in excerpt.split())
        match=re.search(pattern,source,re.IGNORECASE) if pattern else None
        if not match:
            raise SourceEvidenceError(excerpt)
        start,end=match.span()
    return {'excerpt':source[start:end],'start':start,'end':end}

def validate_findings(profile, source):
    errors=[]
    for name in type(profile).model_fields:
        if name == 'requirements':
            continue
        value=getattr(profile,name)
        for finding in value if isinstance(value,list) else [value]:
            if finding.value == 'Not specified' and not finding.excerpt:
                continue
            try:
                finding.excerpt=excerpt_location(finding.excerpt,source)['excerpt']
            except SourceEvidenceError as error:
                errors.extend(error.invalid_excerpts)
    if errors:
        raise SourceEvidenceError(errors)

def canonical_requirements(role: RoleProfile, jd: str, session_id):
    errors=[]
    try:
        validate_findings(role,jd)
    except SourceEvidenceError as error:
        errors.extend(error.invalid_excerpts)
    for requirement in role.requirements:
        try:
            requirement.excerpt=excerpt_location(requirement.excerpt,jd)['excerpt']
        except SourceEvidenceError as error:
            errors.extend(error.invalid_excerpts)
    if errors:
        raise SourceEvidenceError(errors)
    if len(role.requirements) > 40:
        raise ValueError('Too many requirements')
    output={}
    for req in role.requirements:
        evidence=excerpt_location(req.excerpt,jd)
        req.excerpt=evidence['excerpt']
        key=concept_key(req.key)
        if not key or len(key)>200:
            raise ValueError('Empty requirement key')
        weight = 3 if req.importance=='required' else 1 if req.importance=='preferred' else 0
        if req.origin=='inferred':
            weight=0
        item={**req.model_dump(),'key':key,'id':str(uuid5(session_id,key)),
              'evidence':[evidence],'weight':weight,'include_in_fit':weight>0}
        if key in output:
            prior=output[key]
            evidence_list=prior['evidence']+[evidence] if evidence not in prior['evidence'] else prior['evidence']
            if weight > prior['weight']:
                output[key]=item
            output[key]['evidence']=evidence_list
        else:
            output[key]=item
    return list(output.values())

def validate_candidate(profile: CandidateProfile, resume):
    validate_findings(profile,resume)
    if sum(len(value) for value in profile.model_dump().values()) > 70:
        raise ValueError('Candidate profile too large')

def calculate_fit(requirements, proposed: MatchOutput, resume):
    lookup={r['key']:r for r in requirements}
    matches={}
    for match in proposed.matches:
        key=concept_key(match.requirement_key)
        if key not in lookup or key in matches:
            raise ValueError('Unknown or duplicate requirement match')
        evidence=[excerpt_location(x,resume) for x in match.resume_excerpts]
        if match.status in ('strong','partial') and not evidence:
            raise ValueError('A match needs resume evidence')
        matches[key]={**match.model_dump(),'requirement_key':key,'resume_evidence':evidence}
    if set(matches)!=set(lookup):
        raise ValueError('Every canonical requirement needs exactly one match')
    denominator=sum(r['weight'] for r in requirements)
    numerator=sum(r['weight']*{'strong':1,'partial':.5,'not_evidenced':0}[matches[r['key']]['status']] for r in requirements)
    return {'score':round(100*numerator/denominator,1) if denominator else None,
            'scored_weight':denominator,
            'explanation':'100 × weighted match evidence / scored requirement weights. Required: 3; preferred: 1; strong: 1; partial: 0.5. Inferred/unspecified requirements are excluded.',
            'requirements':requirements,'matches':list(matches.values()),
            'eligibility_keys':[r['key'] for r in requirements if r['category']=='eligibility' and r['origin']=='explicit']}
