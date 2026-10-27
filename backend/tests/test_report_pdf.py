from io import BytesIO
from copy import deepcopy
from unittest.mock import AsyncMock
from pypdf import PdfReader
from app.report_pdf import render_report_pdf
from app.auth import current_identity,Identity
from app.main import app
from app import report_service as reports
from test_reports import report_fixture
from test_interview import interview,evaluation,qdict
from test_foundation import fixture


def test_pdf_export_is_read_only_owned_and_does_not_call_model(report_fixture,monkeypatch):
    client,_,other,sid=report_fixture;route=f'/api/sessions/{sid}/report'
    generated=client.post(route)
    assert generated.status_code==200
    before=client.get(route).json()
    monkeypatch.setattr(reports,'synthesize_report',AsyncMock(side_effect=AssertionError('No model on export')))
    response=client.get(route+'/pdf')
    assert response.status_code==200,response.text
    assert response.headers['content-type']=='application/pdf'
    assert 'attachment;' in response.headers['content-disposition']
    assert 'no-store' in response.headers['cache-control']
    reader=PdfReader(BytesIO(response.content))
    text='\n'.join(page.extract_text() for page in reader.pages)
    assert text.index('Interview report')<text.index('Summary and preparation')<text.index('Prioritised preparation plan')
    assert 'Synthetic saved-evidence summary.' in text
    assert 'Technical knowledge' in text and 'Communication' in text
    assert 'Response durations' not in text and 'Not measured (typed answer)' not in ' '.join(text.split())
    assert 'Candidate answer' in text and 'What was good' in text and 'Ideal direction' in text
    assert client.get(route).json()==before
    assert reports.synthesize_report.await_count==0
    app.dependency_overrides[current_identity]=lambda:Identity(user_id=other,display_name='Other')
    assert client.get(route+'/pdf').status_code==404


def test_pdf_handles_ungenerated_summary_and_escapes_long_text(report_fixture):
    client,_,_,sid=report_fixture
    report=client.get(f'/api/sessions/{sid}/report').json()
    report['title']='A <script> & personalised report'
    report['metrics']['priorities'][0]['practice_task']=('A long practice exercise <with markup> & details. '*130)+'END OF EXERCISE'
    before=deepcopy(report)
    reader=PdfReader(BytesIO(render_report_pdf(report)))
    text='\n'.join(page.extract_text() for page in reader.pages)
    assert 'A <script> & personalised report' in text
    assert 'has not been generated' in text
    assert 'END OF EXERCISE' in text
    assert len(reader.pages)>=3
    assert report==before


def test_pdf_is_not_available_before_finalisation(interview):
    client,_,_,sid=interview
    assert client.get(f'/api/sessions/{sid}/report/pdf').status_code==409


def test_pdf_omits_unavailable_readiness_estimate_line(report_fixture):
    client,_,_,sid=report_fixture
    report=client.get(f'/api/sessions/{sid}/report').json()
    report['metrics']['readiness']['score']=None
    report['metrics']['readiness']['label']='Insufficient evidence to establish readiness'
    text=' '.join(page.extract_text() for page in PdfReader(BytesIO(render_report_pdf(report))).pages)
    assert 'Readiness estimate' not in text
    assert 'Readiness status' in text and 'Insufficient evidence to establish readiness' in ' '.join(text.split())
