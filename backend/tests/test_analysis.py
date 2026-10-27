from io import BytesIO
from uuid import uuid4
import zipfile
import pytest
from fastapi import HTTPException
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import NameObject,DictionaryObject,DecodedStreamObject
from test_foundation import fixture
from app.documents import extract_document
from app.analysis_schemas import RoleProfile,Requirement,Finding,Match,MatchOutput
from app.fit import canonical_requirements,calculate_fit
from app import analysis_routes
from app.llm import AnalysisUnavailable

JD='Backend role requires Python. SQL is preferred. Kubernetes might be useful.'
RESUME='Synthetic candidate built a Python API and tested it with pytest.'
EMPTY={'value':'Not specified','origin':'explicit','excerpt':''}

def role():
    values={key:[] for key in ('responsibilities','required_skills','preferred_skills','technical_competencies',
        'behavioural_competencies','experience_expectations','keywords','concepts','qualifications','other_requirements')}
    return RoleProfile(title=EMPTY,seniority=EMPTY,**values,requirements=[
        Requirement(key='python',label='Python',category='skill',importance='required',origin='explicit',excerpt='requires Python'),
        Requirement(key='python programming',label='Python programming',category='skill',importance='preferred',origin='explicit',excerpt='Python'),
        Requirement(key='sql',label='SQL',category='skill',importance='preferred',origin='explicit',excerpt='SQL is preferred'),
        Requirement(key='kubernetes',label='Kubernetes',category='skill',importance='required',origin='inferred',excerpt='Kubernetes might be useful')])

def matches():
    return MatchOutput(matches=[
        Match(requirement_key='python',status='strong',resume_excerpts=['built a Python API'],reason='Implementation evidenced',preparation_note='Explain API testing',probe_target='Ownership'),
        Match(requirement_key='sql',status='partial',resume_excerpts=['Python API'],reason='Synthetic partial fixture',preparation_note='Practise joins',probe_target='SQL'),
        Match(requirement_key='kubernetes',status='not_evidenced',resume_excerpts=[],reason='Not evidenced in the resume',preparation_note='Optional review',probe_target='')])

def test_fit_deduplicates_and_excludes_inferred():
    requirements=canonical_requirements(role(),JD,uuid4())
    assert len(requirements)==3
    assert [r['weight'] for r in requirements]==[3,1,0]
    fit=calculate_fit(requirements,matches(),RESUME)
    assert fit['score']==87.5

def test_invented_source_evidence_rejected():
    broken=role()
    broken.requirements[0].excerpt='invented quote'
    with pytest.raises(ValueError):
        canonical_requirements(broken,JD,uuid4())

def test_missing_duplicate_and_unknown_matches_rejected():
    requirements=canonical_requirements(role(),JD,uuid4())
    proposed=matches()
    proposed.matches.pop()
    with pytest.raises(ValueError):
        calculate_fit(requirements,proposed,RESUME)
    proposed=matches()
    proposed.matches[0].resume_excerpts=['not in resume']
    with pytest.raises(ValueError):
        calculate_fit(requirements,proposed,RESUME)
    proposed=matches()
    proposed.matches.append(proposed.matches[0])
    with pytest.raises(ValueError):
        calculate_fit(requirements,proposed,RESUME)

def test_no_scorable_requirements_has_no_percentage():
    requirements=canonical_requirements(role(),JD,uuid4())
    for requirement in requirements:
        requirement['weight']=0
    assert calculate_fit(requirements,matches(),RESUME)['score'] is None

def test_actual_txt_docx_and_pdf_extraction():
    assert extract_document(RESUME.encode(),'resume.txt')==RESUME
    doc=Document();doc.add_paragraph(RESUME)
    buf=BytesIO();doc.save(buf)
    assert RESUME in extract_document(buf.getvalue(),'resume.docx')
    writer=PdfWriter();page=writer.add_blank_page(400,400)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 20 100 Td ('+RESUME+') Tj ET').encode())
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out)
    assert RESUME in extract_document(out.getvalue(),'resume.pdf')

@pytest.mark.parametrize('data,name',[(b'','empty.txt'),(b'invalid','bad.pdf'),(b'x'*30,'bad.exe'),(b'\xff'*30,'bad.txt')])
def test_bad_documents_fail_clearly(data,name):
    with pytest.raises(HTTPException):
        extract_document(data,name)

def test_scanned_and_oversize_documents():
    writer=PdfWriter();writer.add_blank_page(100,100);buf=BytesIO();writer.write(buf)
    with pytest.raises(HTTPException):
        extract_document(buf.getvalue(),'scanned.pdf')
    with pytest.raises(HTTPException) as failure:
        extract_document(b'x'*(5*1024*1024+1),'large.txt')
    assert failure.value.status_code==413

@pytest.fixture
def configured(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(analysis_routes,'get_settings',lambda:SimpleNamespace(groq_api_key=True))

def test_saved_analysis_snapshots_and_owner_checks(fixture,configured,monkeypatch):
    client,owner,other,session_id=fixture
    calls=[]
    async def fake(session,jd,resume):
        calls.append(1)
        fit=calculate_fit(canonical_requirements(role(),jd,session),matches(),resume)
        return role().model_dump(),{},fit,{'calls':[],'synthetic':True}
    monkeypatch.setattr(analysis_routes,'analyse_documents',fake)
    path=f'/api/sessions/{session_id}'
    assert client.post(path+'/documents',json={'jd_text':JD,'resume_text':RESUME}).status_code==200
    analysed=client.post(path+'/analyse')
    assert analysed.status_code==200
    assert analysed.json()['job_fit_score']==87.5
    assert client.post(path+'/analyse').status_code==200
    assert len(calls)==1
    assert client.post(path+'/documents',json={'jd_text':JD,'resume_text':RESUME}).status_code==409
    from app.auth import current_identity,Identity
    from app.main import app
    app.dependency_overrides[current_identity]=lambda:Identity(user_id=other,display_name='Other synthetic')
    assert client.post(path+'/documents',json={'jd_text':JD,'resume_text':RESUME}).status_code==404
    assert client.post(path+'/analyse').status_code==404

def test_provider_failure_preserves_documents_and_allows_retry(fixture,configured,monkeypatch):
    client,_,_,session_id=fixture
    async def fail(*args):
        raise AnalysisUnavailable('Quota exhausted. Retry later.')
    monkeypatch.setattr(analysis_routes,'analyse_documents',fail)
    path=f'/api/sessions/{session_id}'
    client.post(path+'/documents',json={'jd_text':JD,'resume_text':RESUME})
    assert client.post(path+'/analyse').status_code==503
    saved=client.get(path).json()
    assert saved['status']=='draft'
    assert saved['jd_text']==JD and saved['resume_text']==RESUME

def test_upload_endpoint_extracts_and_rejects_invalid_kind(fixture):
    client,*_=fixture
    assert client.post('/api/documents/extract?kind=resume&filename=resume.txt',content=RESUME.encode()).json()['text']==RESUME
    assert client.post('/api/documents/extract?kind=jd&filename=bad.pdf',content=b'invalid').status_code==422
    assert client.post('/api/documents/extract?kind=bad&filename=resume.txt',content=RESUME.encode()).status_code==422

def test_unexpired_analysis_is_not_started_twice(fixture,configured):
    from app.database import get_db
    from app.main import app
    from app.models import InterviewSession
    from datetime import datetime,timezone
    client,_,_,session_id=fixture
    with next(app.dependency_overrides[get_db]()) as db:
        row=db.get(InterviewSession,session_id)
        row.status='analysing'
        row.processing_metadata={'token':'synthetic','started_at':datetime.now(timezone.utc).isoformat()}
        db.commit()
    assert client.post(f'/api/sessions/{session_id}/analyse').status_code==409

def test_structured_provider_repairs_once_and_does_not_echo_source_errors(monkeypatch):
    import asyncio
    import httpx
    from unittest.mock import AsyncMock,patch
    from types import SimpleNamespace
    from pydantic import SecretStr
    from app.llm import structured
    from app.fit import SourceEvidenceError
    response=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"matches":[]}'}}],'usage':{}})
    checks=[]
    def validator(parsed):
        checks.append(1)
        if len(checks)==1:
            raise SourceEvidenceError('synthetic non-source quote')
        return 'validated'
    with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.post=AsyncMock(return_value=response)
        _,validated,telemetry=asyncio.run(structured(MatchOutput,'Synthetic instructions',{'synthetic':True},validator))
        assert validated=='validated' and len(telemetry)==2
        assert factory.return_value.__aenter__.return_value.post.await_count==2

def test_structured_provider_stops_after_failed_repair(monkeypatch):
    import asyncio
    import httpx
    from unittest.mock import AsyncMock,patch
    from types import SimpleNamespace
    from pydantic import SecretStr
    from app.llm import structured
    response=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"matches":[]}'}}],'usage':{}})
    def validator(parsed):
        raise ValueError('Synthetic validation failure')
    with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
        factory.return_value.__aenter__.return_value.post=AsyncMock(return_value=response)
        with pytest.raises(AnalysisUnavailable):
            asyncio.run(structured(MatchOutput,'Synthetic',{},validator))
        assert factory.return_value.__aenter__.return_value.post.await_count==2



@pytest.mark.parametrize('repaired', [True, False])
def test_groq_http_schema_rejection_uses_one_bounded_repair(repaired):
    import asyncio
    import httpx
    from unittest.mock import AsyncMock,patch
    from types import SimpleNamespace
    from pydantic import SecretStr
    from app.llm import structured
    rejected=httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':'{"matches":"invalid"}'}})
    accepted=httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"matches":[]}'}}],'usage':{}})
    with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
        post=AsyncMock(side_effect=[rejected,accepted if repaired else rejected])
        factory.return_value.__aenter__.return_value.post=post
        if repaired:
            result,_,_=asyncio.run(structured(MatchOutput,'Synthetic',{},lambda value:value))
            assert result.matches==[]
        else:
            with pytest.raises(AnalysisUnavailable,match='after one repair'):
                asyncio.run(structured(MatchOutput,'Synthetic',{},lambda value:value))
        assert post.await_count==2

def test_source_whitespace_and_case_are_canonicalised_without_paraphrasing():
    from app.fit import excerpt_location
    source='Built a PYTHON\n  API with SQL.'
    evidence=excerpt_location('python API',source)
    assert evidence['excerpt']=='PYTHON\n  API'
    assert source[evidence['start']:evidence['end']]==evidence['excerpt']
    with pytest.raises(ValueError):
        excerpt_location('Python service',source)

def test_finding_label_alias_is_strictly_normalised():
    import json
    from app.llm import parse_generated
    value=role().model_dump()
    value['title']={'label':'Not specified','origin':'explicit','excerpt':''}
    parsed=parse_generated(RoleProfile,json.dumps(value))
    assert parsed.title.value=='Not specified'
    value['title']['unexpected']='must not be ignored'
    with pytest.raises(ValueError):
        parse_generated(RoleProfile,json.dumps(value))

def test_http_rejected_alias_output_still_requires_schema_and_source_validation():
    import asyncio,json,httpx
    from unittest.mock import AsyncMock,patch
    from types import SimpleNamespace
    from pydantic import SecretStr
    from app.llm import structured
    value=role().model_dump()
    value['title']={'label':'Not specified','origin':'explicit','excerpt':''}
    response=httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':json.dumps(value)}})
    with patch('app.llm.get_settings',return_value=SimpleNamespace(groq_api_key=SecretStr('synthetic'),groq_model='synthetic')),patch('app.llm.httpx.AsyncClient') as factory:
        post=AsyncMock(return_value=response)
        factory.return_value.__aenter__.return_value.post=post
        _,requirements,telemetry=asyncio.run(structured(RoleProfile,'Synthetic',{},lambda parsed:canonical_requirements(parsed,JD,uuid4())))
        assert len(requirements)==3 and telemetry[0]['local_schema_normalisation']
        assert post.await_count==1



def test_numbered_source_evidence_expands_to_the_saved_original():
    from app.fit import source_lines,excerpt_location
    source='Python API development.\nSQL reporting.'
    lines=source_lines(source)
    assert lines['S001']=='Python API development.'
    evidence=excerpt_location('S002',source)
    assert evidence['excerpt']=='SQL reporting.'
    assert source[evidence['start']:evidence['end']]==evidence['excerpt']
    with pytest.raises(ValueError):
        excerpt_location('S999',source)
