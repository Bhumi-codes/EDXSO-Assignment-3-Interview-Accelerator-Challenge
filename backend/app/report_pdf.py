"""Read-only PDF export of saved report evidence and preparation guidance."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,PageBreak,KeepTogether,CondPageBreak

GREEN=colors.HexColor('#174d40')
MUTED=colors.HexColor('#61756e')
INK=colors.HexColor('#273b35')
PALE=colors.HexColor('#edf3ef')
NAMES={1:'Screening',2:'Competency',3:'Deep Dive'}


def render_report_pdf(report):
    fonts=Path(reportlab.__file__).parent/'fonts'
    if 'ReportVera' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('ReportVera',str(fonts/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('ReportVeraBold',str(fonts/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('ReportVera',normal='ReportVera',bold='ReportVeraBold',italic='ReportVera',boldItalic='ReportVeraBold')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyReport',fontName='ReportVera',fontSize=9.5,leading=15,spaceAfter=9,textColor=INK,splitLongWords=True))
    styles.add(ParagraphStyle(name='TitleReport',parent=styles['BodyReport'],fontName='ReportVeraBold',fontSize=25,leading=32,spaceAfter=18,textColor=GREEN))
    styles.add(ParagraphStyle(name='HeadingReport',parent=styles['BodyReport'],fontName='ReportVeraBold',fontSize=12,leading=17,spaceBefore=20,spaceAfter=12,keepWithNext=True,textColor=colors.white,backColor=GREEN,borderPadding=(9,11,9,11)))
    styles.add(ParagraphStyle(name='SmallReport',parent=styles['BodyReport'],fontSize=8,leading=12,textColor=MUTED))
    styles.add(ParagraphStyle(name='SubheadingReport',parent=styles['BodyReport'],fontName='ReportVeraBold',fontSize=11,leading=16,textColor=GREEN,spaceBefore=14,spaceAfter=8,keepWithNext=True))
    styles.add(ParagraphStyle(name='QuestionReport',parent=styles['SubheadingReport'],fontSize=12,leading=18,backColor=PALE,borderPadding=10,spaceBefore=18,spaceAfter=14))
    styles.add(ParagraphStyle(name='FieldReport',parent=styles['BodyReport'],fontName='ReportVeraBold',fontSize=9,leading=13,textColor=GREEN,spaceBefore=12,spaceAfter=5,keepWithNext=True))
    styles.add(ParagraphStyle(name='TableHead',parent=styles['BodyReport'],fontName='ReportVeraBold',textColor=colors.white,spaceAfter=0))
    styles.add(ParagraphStyle(name='BulletReport',parent=styles['BodyReport'],leftIndent=12,firstLineIndent=-9,spaceAfter=5))
    story=[]
    def text(value):
        value=str(value).replace('\r','').replace('\u2011','-').replace('\u2013','-').replace('\u2014',' - ')
        return escape(value).replace('\n','<br/>')
    def p(value,style='BodyReport'):return Paragraph(text(value),styles[style])
    def add(value,style='BodyReport'):story.append(p(value,style))
    def heading(value):
        story.append(CondPageBreak(105));add(value,'HeadingReport')
    def subheading(value):
        story.append(CondPageBreak(85));add(value,'SubheadingReport')
    def field(label,value=None):
        add(label,'FieldReport')
        if value:
            for paragraph in str(value).split('\n\n'):
                if paragraph.strip():add(paragraph.strip())
    def bullet(value):add('- '+str(value),'BulletReport')
    def percent(value):return 'Not established' if value is None else f'{value:.1f}%'
    by_id={t['id']:t for t in report['feedback']}
    def refs(ids):
        values=[f"{NAMES[by_id[key]['level']]} Q{by_id[key]['number']}" for key in ids if key in by_id]
        return ', '.join(values) or 'No question-specific evidence reference.'
    metrics=report['metrics'];coverage=metrics['coverage']
    add('ACE-IT','SmallReport')
    add(report['title'],'TitleReport')
    add('Interview report','SubheadingReport')
    add('Attempt: '+report['attempt_status'].replace('_',' '),'SmallReport')
    add('Preparation estimates from saved rubric assessments. These are separate from documented job fit and do not predict hiring.','SmallReport')
    if report.get('generated_at'):add('Summary saved: '+report['generated_at'],'SmallReport')
    heading('Performance and coverage')
    performance=[('Overall interview score',percent(metrics['overall_score'])),('Readiness status',metrics['readiness']['label'])]
    if metrics['readiness']['score'] is not None:performance.append(('Readiness estimate',percent(metrics['readiness']['score'])))
    performance.append(('Documented job fit',percent(metrics['documented_job_fit'])))
    score_rows=[[p(label,'FieldReport'),p(value,'SubheadingReport')] for label,value in performance]
    score_table=Table(score_rows,colWidths=[223,264],hAlign='LEFT')
    score_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,-1),0.5,colors.white)]))
    story.append(score_table);story.append(Spacer(1,14))
    add(f"{coverage['evaluated']} assessed answers / {coverage['answered']} submitted; {coverage['skipped']} skipped. {coverage['assessed_dimensions']}/7 dimensions assessed; {coverage['evidence_units']} level/topic evidence units.")
    if metrics.get('communication',{}).get('pending_answers'):
        add(f"Communication: {metrics['communication']['pending_answers']} submitted answers still need assessment. The current communication estimate covers the assessed subset only.",'SmallReport')
    for reason in metrics['readiness']['reasons']:add('- '+reason,'SmallReport')
    heading('Seven competency dimensions')
    rows=[[p(v,'TableHead') for v in ('Dimension','Rating / 4','Percentage','Evidence')]]
    for d in metrics['competencies']:
        rows.append([p(d['label']),p('Not assessed' if d['score_0_4'] is None else str(d['score_0_4'])),p(percent(d['score_percent'])),p(str(d['assessed_units'])+(' answers' if d['key']=='communication' else ' level/topic units'))])
    table=Table(rows,colWidths=[180,73,84,150],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),GREEN),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),4),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#d6dfd2'))]))
    story.append(table)
    heading('Assessment evidence')
    for d in metrics['competencies']:
        if d['turn_ids']:add(d['label']+': '+refs(d['turn_ids']),'SmallReport')
    heading('How the scores are calculated')
    add(metrics['calculation'])
    if metrics.get('skip_adjustment'):add(metrics['skip_adjustment']['explanation'],'SmallReport')
    add(metrics.get('communication',{}).get('policy',''),'SmallReport')
    for turn_id,rating in metrics.get('communication',{}).get('answer_scores',{}).items():
        delivery=rating.get('delivery')
        if delivery and delivery.get('total_deduction_points'):
            turn=by_id.get(turn_id,{})
            add(f"{NAMES.get(turn.get('level'),'Interview')} Q{turn.get('number','')}: repetition deduction {delivery['filler_deduction_points']} percentage points; unfinished-sentence pause deduction {delivery['pause_deduction_points']} percentage points.",'SmallReport')
    add(metrics['readiness']['formula'])
    for cap in metrics['readiness']['caps']:add(f"Readiness ceiling {cap['maximum']}%: {cap['reason']}",'SmallReport')
    heading('Scope and limitations')
    for note in metrics['limitations']:add('- '+note,'SmallReport')
    story.append(PageBreak())
    heading('Question-level feedback')
    add('Each question is followed by the submitted answer, its assessment and specific preparation feedback.','SmallReport')
    for turn in report['feedback']:
        story.append(CondPageBreak(190))
        add(f"{NAMES[turn['level']]} / Question {turn['number']}",'FieldReport')
        add(turn['question'],'QuestionReport')
        add('Status: '+turn['status'].replace('_',' '),'SmallReport')
        if turn.get('answer'):field('Candidate answer',turn['answer'])
        evaluation=turn.get('evaluation')
        if not evaluation:
            add('No accepted assessable answer is available for this question. No competency score is invented.','SmallReport')
            continue
        field('Assessment - '+evaluation['assessment_label'],evaluation['reasoning'])
        field('What was good')
        for point in evaluation.get('strengths',[]):bullet(point)
        if not evaluation.get('strengths'):add('No specific strength established.','SmallReport')
        field('What could be better')
        for point in evaluation.get('improvements',[]):bullet(point)
        if not evaluation.get('improvements'):add('No specific improvement recorded.','SmallReport')
        field('Ideal direction',evaluation['ideal_direction'])
        story.append(Spacer(1,15))
    story.append(PageBreak())
    add('Summary and preparation','TitleReport')
    narrative=report.get('narrative')
    if narrative:
        heading('Your preparation summary');add(narrative['summary'])
        for key,title in [('strengths','Demonstrated strengths'),('weaknesses','Areas to strengthen')]:
            heading(title)
            if not narrative[key]:add('No items established from the saved evidence.','SmallReport')
            for insight in narrative[key]:
                group_start=len(story)
                add(insight['title'],'SubheadingReport');add(insight['explanation']);add('Evidence: '+refs(insight['turn_ids']),'SmallReport')
                story[group_start:]=[KeepTogether(story[group_start:])]
    else:
        add('A current personalised summary has not been generated. This export contains saved scores and the available preparation priorities; it does not generate new model guidance.')
    heading('Prioritised preparation plan')
    steps={step['objective_id']:step for step in narrative['preparation_plan']} if narrative else {}
    for objective in metrics['priorities']:
        group_start=len(story)
        step=steps.get(objective['id'],{})
        subheading(f"Priority {objective['rank']} - {objective['title']}")
        add('Source: '+objective['source'].replace('_',' '),'SmallReport')
        add(step.get('evidence_summary') or objective['why'])
        if step.get('review_topics'):
            field('Review')
            for topic in step['review_topics']:bullet(topic)
        field('Practical exercise',step.get('action',objective['practice_task']))
        field('Success check',step.get('success_check',objective['success_check']))
        add('Evidence: '+refs(step.get('turn_ids',objective['turn_ids'])),'SmallReport')
        story[group_start:]=[KeepTogether(story[group_start:])]
    add('Full accepted answers and question feedback remain available in the saved interview.','SmallReport')
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=54,leftMargin=54,topMargin=59,bottomMargin=49,title='Interview report - '+report['title'],author='Ace-it')
    def page(canvas,doc):
        canvas.saveState()
        if doc.page>1:
            canvas.setFont('ReportVeraBold',8);canvas.setFillColor(GREEN);canvas.drawString(54,A4[1]-29,'ACE-IT / INTERVIEW REPORT')
            canvas.setFont('ReportVera',8);canvas.setFillColor(MUTED);canvas.drawRightString(A4[0]-54,A4[1]-29,report['title'][:65])
        canvas.setStrokeColor(colors.HexColor('#d6dfd2'));canvas.line(54,38,A4[0]-54,38)
        canvas.setFont('ReportVera',8);canvas.setFillColor(MUTED)
        canvas.drawString(54,25,'Ace-it | Saved interview report')
        canvas.drawRightString(A4[0]-54,25,'Page '+str(doc.page));canvas.restoreState()
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return buffer.getvalue()
