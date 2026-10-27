"""Authored calibration examples v1, not real candidate transcripts or fixed questions.
Principles: OPM structured interviewing/probing and Google ML metric definitions.
"""
OPM='https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/'
METRICS='https://developers.google.com/machine-learning/crash-course/classification/accuracy-precision-recall'
EXAMPLES=[
 {'version':1,'source':OPM,'level':1,'competency':'role_fit','category':'vague','answer':'We built the chatbot.',
  'judgement':'Personal contribution not established; not evidence of dishonesty.','action':'clarify','purpose':'Establish ownership'},
 {'version':1,'source':OPM,'level':1,'competency':'depth','category':'honest_limited','answer':'I only ran it locally, not deployed.',
  'judgement':'Deployment is not demonstrated; acknowledge the boundary.','action':'new_topic','purpose':'Avoid endless probing'},
 {'version':1,'source':'https://www.sqlite.org/whentouse.html','level':2,'competency':'problem_solving','category':'alternative_valid','answer':'SQLite kept a small single-server app simple.',
  'judgement':'Reasonable in this setting; one applied clarification can be useful.','action':'deepen','purpose':'Explore one decision, then preserve coverage'},
 {'version':1,'source':METRICS,'level':3,'competency':'technical_knowledge','category':'partial','answer':'Accuracy on a test set dominated by one class.',
  'judgement':'Check baseline and minority-class performance.','action':'deepen','purpose':'Investigate metrics and evidence'},
 {'version':1,'source':METRICS,'level':3,'competency':'technical_knowledge','category':'wrong','answer':'High accuracy always proves good minority-class recall.',
  'judgement':'These metrics can diverge under class imbalance.','action':'simplify','purpose':'Diagnose metric understanding'},
 {'version':1,'source':OPM,'level':2,'competency':'behavioural_fit','category':'strong','answer':'Compared alternatives with colleagues, tested a prototype, explained my decision and the outcome.',
  'judgement':'Assess the specific reasoning and actions, not STAR wording.','action':'new_topic','purpose':'Protect coverage'},
 {'version':1,'source':OPM,'level':3,'competency':'role_fit','category':'contradictory','answer':'Earlier said I wrote the API; now says I only called an external API.',
  'judgement':'Ask a neutral clarification; do not allege dishonesty.','action':'clarify','purpose':'Resolve differing claims'}
]
EXAMPLES.extend([
 {'version':2,'source':OPM,'level':2,'competency':'depth','category':'partial_justification',
  'answer':'I chose it because it was the first method I learned; I did not compare alternatives.',
  'judgement':'Partial design justification: score technical/depth criteria lower; a clear honest limit may still merit adequate communication. These are separate dimensions, not one copied score.',
  'action':'new_topic','purpose':'Keep the gap in scoring while moving to another relevant objective'},
 {'version':2,'source':OPM,'level':3,'competency':'technical_knowledge','category':'exhausted_hypothetical',
  'answer':'I have already described the proposed preprocessing, classifier and evaluation and cannot add implementation experience.',
  'judgement':'Do not request the complete pipeline again or infer hands-on work.',
  'action':'new_topic','purpose':'Use another supported project, technology or JD competency'}
])

def examples_for(action, level=None):
    pool=[e for e in EXAMPLES if level is None or e['level']==level]
    if action=='evaluation' and level in (2,3):
        boundary=[e for e in pool if e.get('category') in ('partial_justification','exhausted_hypothetical')]
        contrast=[e for e in pool if e not in boundary]
        return (boundary+contrast)[:2]
    return ([e for e in pool if e['action']==action] or pool[:2])[:2]


# Stage-specific authored examples. Never a fixed script or candidate facts.
INTERVIEW_TRAILS = [{'id': 'broad_screening_v2',
  'scope': 'Five illustrative easy Screening exchanges; the live limit is four turns.',
  'jd': 'AI engineer intern: Python, basic ML understanding, practical learning, teamwork and communication.',
  'resume': 'A computing student with a student-score model, a small document tool and a short '
            'technical-writing internship.',
  'turns': [{'level': 1,
             'q': 'Could you briefly introduce yourself and explain what led you toward an AI engineering '
                  'internship?',
             'a': 'I am studying computer science and have enjoyed applying Python to small ML and '
                  'document-processing projects. Those experiences made me interested in building '
                  'applications people can use. I would like an internship where I can strengthen practical '
                  'engineering habits while learning from a team.',
             'next': 'Background and direction are clear. Move to motivation rather than drilling into a '
                     'named project.'},
            {'level': 1,
             'q': 'What interests you about the responsibilities in this role, and what would you most like '
                  'to learn during the internship?',
             'a': 'The combination of model evaluation and application integration interests me. I have '
                  'worked on university prototypes, but want to understand how teams test and maintain these '
                  'systems. I would particularly like feedback on how I explain technical decisions and turn '
                  'an experiment into useful work.',
             'next': 'Motivation is established. A simple concept linked to the role can check basic '
                     'understanding.'},
            {'level': 1,
             'q': 'In simple terms, why would you check a model on data it did not see during training?',
             'a': 'A model can fit its training examples without working equally well on new examples. '
                  'Testing on unseen data gives a more useful indication of how it might behave outside '
                  'training. I would still need to consider whether that test data represents the intended '
                  'use.',
             'next': 'Basic understanding is sufficient for Screening. Do not turn this into metric '
                     'calculations or evaluation design.'},
            {'level': 1,
             'q': 'Your resume mentions technical writing. How did that experience help you explain '
                  'unfamiliar ideas to other people?',
             'a': 'I had to understand an idea well enough to explain it clearly instead of repeating '
                  'terminology. I tried to use examples and check whether the explanation answered a '
                  'reader’s likely questions. It helped me notice when I was relying on a term I could not '
                  'explain simply.',
             'next': 'Relevant experience and communication are covered without a project interrogation.'},
            {'level': 1,
             'q': 'What direction would you like to take after graduation, and how could this internship '
                  'help you explore that goal?',
             'a': 'I would like to work on applied AI systems, but I am still exploring which '
                  'responsibilities suit me best. This internship could give me experience with real '
                  'engineering workflows, teamwork and testing. I would use that experience to make a '
                  'better-informed decision about my next role.',
             'next': 'Career goals and role fit are covered. End the example; follow the actual four-turn '
                     'budget in the application.'}]}]
LATER_LEVEL_EXAMPLES = {2: [{'version': 2,
      'source': 'https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/',
      'level': 2,
      'jd': 'Backend/AI intern: data preparation, evaluation, API integration, troubleshooting and '
            'collaboration.',
      'resume': 'TensorFlow/Keras image classifier; a separate scikit-learn tabular predictor; a small '
                'document API. Frameworks are project-local, not interchangeable.',
      'turns': [{'level': 2,
                 'q': 'In your TensorFlow image classifier, what guided your choice of model architecture '
                      'rather than simply using the most complex model available?',
                 'a': 'It was the first neural network I had learned, and I wanted to apply it. I used '
                      'regularization and compared the data splits, but I did not systematically compare '
                      'architecture complexity. I cannot reconstruct the exact layer choices from memory.',
                 'next': 'This is a partial justification, not full architecture-comparison evidence. Lower '
                         'only the relevant rubric rating and choose another useful objective; do not demand '
                         'the same architecture rationale again.'},
                {'level': 2,
                 'q': 'For your separate tabular predictor, how did held-out evaluation affect the way you '
                      'compared the scikit-learn models?',
                 'a': 'I compared held-out prediction errors rather than selecting the best training score. '
                      'If a model fit training data well but performed worse on held-out examples, I would '
                      'investigate overfitting or differences in the data. That comparison mattered more '
                      'than the model having more parameters.',
                 'next': 'The stack is explicitly tied to this separate project. Assess practical '
                         'evaluation, then cover another competency.'},
                {'level': 2,
                 'q': 'If the document API received a file it could not parse, what would you do to preserve '
                      'useful information for the user while keeping the failure recoverable?',
                 'a': 'I would explain that parsing failed and offer a supported file or pasted-text '
                      'fallback. I would not invent extracted content or continue as if the file had been '
                      'read. I would preserve already accepted input so the user would not need to repeat '
                      'unrelated work.',
                 'next': 'This is an explicitly hypothetical applied question, not a claim of existing '
                         'production error handling.'},
                {'level': 2,
                 'q': 'Can you describe a situation where you and a teammate approached a project decision '
                      'differently, and how you helped reach a practical next step?',
                 'a': 'We disagreed about adding a feature before stabilizing the existing flow. I suggested '
                      'testing the current workflow with a small example so we could see the problem '
                      'together. We agreed to fix the failure first and keep the feature as a later task.',
                 'next': 'Assess the candidate’s decision and collaboration. The four-turn Competency '
                         'example ends with multiple objectives, not one prolonged project '
                         'interrogation.'}]}],
 3: [{'version': 2,
      'source': 'https://developers.google.com/machine-learning/crash-course/classification/accuracy-precision-recall',
      'level': 3,
      'jd': 'ML engineer: meaningful evaluation, trustworthy model-backed services, reliability and '
            'explaining decisions.',
      'resume': 'Ticket classifier with an accuracy-improvement claim; document extraction using an external '
                'LLM with a response schema. Deployment is not claimed.',
      'turns': [{'level': 3,
                 'q': 'You reported an improvement in the ticket classifier’s accuracy. What comparison '
                      'supported that improvement claim?',
                 'a': 'We compared the new model with the previous version on held-out examples. I do not '
                      'remember all the experimental settings, but accuracy was the metric we reported.',
                 'next': 'The metric has already been supplied. Probe its appropriateness, not its name or a '
                         'complete pipeline.'},
                {'level': 3,
                 'q': 'Why was accuracy an appropriate measure for those tickets, given the consequences of '
                      'classifying one category incorrectly?',
                 'a': 'I mainly used it because it was easy to summarize. Most tickets belonged to one '
                      'category, and I did not investigate the smaller categories separately.',
                 'next': 'The justification is weak. A focused imbalance counter-question can diagnose '
                         'reasoning; save the partial assessment.'},
                {'level': 3,
                 'q': 'If a model predicted the majority category for every ticket, how would you check '
                      'whether the reported accuracy represented useful classification performance?',
                 'a': 'I would compare against that trivial baseline and inspect per-category recall and the '
                      'confusion matrix. I would also consider which errors matter for the application. A '
                      'high overall accuracy could hide a poor result on the smaller categories.',
                 'next': 'Acknowledge improvement after prompting. The two-follow-up cap is reached; move to '
                         'a different supported project rather than request another classifier pipeline.'},
                {'level': 3,
                 'q': 'Your document tool validates the LLM response with a schema. How would you handle a '
                      'structurally valid response that asserts information absent from the source?',
                 'a': 'Schema validation alone would not establish factual support. I would check source '
                      'evidence for the claim and reject or flag unsupported information. I would '
                      'distinguish a successful parse from a verified conclusion.',
                 'next': 'This follows a different supported claim and tests a distinct failure mode. A '
                         'useful counter-question can explore the proposed evidence check.'},
                {'level': 3,
                 'q': 'If the quoted source text is genuine but does not support the conclusion drawn from '
                      'it, what additional check would your proposed validation need?',
                 'a': 'It would need to distinguish finding a quote from establishing that the quote '
                      'supports the specific claim. I would keep uncertain conclusions explicit and use '
                      'review rather than treating every linked passage as proof. I have not implemented a '
                      'complete automated semantic verifier.',
                 'next': 'Respect the implementation boundary. Do not demand an existing semantic-verifier '
                         'design; select a new realistic objective.'},
                {'level': 3,
                 'q': 'If you had to expose a model-backed prototype as a service, how would you decide what '
                      'to simplify when response time was too slow?',
                 'a': 'I would first measure where time was spent and identify the user-facing constraint. I '
                      'would compare a simpler model or smaller request against the quality we needed, '
                      'rather than remove checks blindly. This is a proposed approach, since my projects '
                      'have not been deployed publicly.',
                 'next': 'A bounded JD-related hypothetical is valid. Do not spend the remaining round '
                         'requesting successive end-to-end deployment designs.'},
                {'level': 3,
                 'q': 'If a teammate wanted to describe source-linked model outputs as verified, how would '
                      'you challenge that claim using the distinction you explained earlier?',
                 'a': 'I would show an example where the quote is present but the conclusion is unsupported. '
                      'I would suggest wording that distinguishes located evidence from a checked conclusion '
                      'and agree on a small test together. That keeps the discussion about evidence rather '
                      'than personal disagreement.',
                 'next': 'This counter-question uses earlier context in a new decision/communication '
                         'setting. End the seven-turn trail instead of stretching one stack.'}]}]}

def trails_for_level(level):
    return INTERVIEW_TRAILS if level==1 else LATER_LEVEL_EXAMPLES[level]
