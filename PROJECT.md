\# AI QA Evaluation Harness



\## Project summary



Build a narrow, credible repository around this claim:



\*\*I can evaluate whether an LLM produces useful QA test cases from requirements, using a gold dataset, measurable scoring, human review, and trend reporting across model and prompt versions.\*\*



This project is meant to demonstrate:

\- test design judgment

\- evaluation rigor

\- dataset thinking

\- human-in-the-loop review

\- repeatable reporting

\- versioned prompt/model comparison



\## MVP



Given a requirement snippet, an LLM generates a list of test cases in structured JSON.



The harness then evaluates that output against a gold dataset and produces:

\- per-sample scores

\- pass/fail result

\- borderline review queue

\- summary report by prompt version and model version



\## Why this project



This repo is intentionally centered on \*\*AI-generated QA test cases from requirement snippets\*\* because that is the most credible AI-era QA artifact for a first serious project.



It maps cleanly to:

\- requirements analysis

\- coverage assessment

\- risk detection

\- review workflow

\- quality gates

\- regression trends



\## Strict non-goals



Do not include these in MVP:

\- UI

\- multi-artifact support

\- autonomous defect generation

\- agent workflows

\- RAG

\- vector databases

\- large datasets

\- complex CI/CD

\- dashboards



This should remain a small, serious evaluation system rather than a platform.



\## Primary users



The main audience for the results is:

\- a QA lead

\- an engineering stakeholder

\- a person comparing prompt/model reliability for assisted QA work



The core decision question is:



\*\*Is this model/prompt combination reliable enough to assist QA test design, and where does it still require human review?\*\*



\## Technical stack



Recommended MVP stack:

\- Python

\- pydantic for schemas

\- pandas for result analysis/report generation

\- pytest for scoring logic

\- yaml/jsonl/csv for config and data

\- standard logging for run traceability



\## Repo structure



\~\~\~text

ai-qa-eval-harness/

&#x20; README.md

&#x20; pyproject.toml

&#x20; configs/

&#x20;   run\_v1.yaml

&#x20; src/

&#x20;   harness/

&#x20;     run\_eval.py

&#x20;     generate.py

&#x20;     evaluate.py

&#x20;     score.py

&#x20;     report.py

&#x20;     review\_queue.py

&#x20;     schemas.py

&#x20;     model\_adapter.py

&#x20;     prompts/

&#x20;       v1.txt

&#x20;       v2.txt

&#x20; data/

&#x20;   requirements/

&#x20;     mvp\_dataset.jsonl

&#x20;   gold/

&#x20;     gold\_test\_cases.jsonl

&#x20;   generated/

&#x20;   runs/

&#x20;   reviews/

&#x20; reports/

&#x20; docs/

&#x20;   rubric.md

&#x20;   dataset\_design.md

&#x20;   architecture.md

&#x20; examples/

&#x20;   sample\_run/

&#x20; tests/

&#x20;   test\_scoring.py

&#x20;   test\_parsing.py

&#x20;   test\_thresholds.py

\~\~\~



\## Core design rules



\### 1. Force structured output



The model must return JSON, not freeform prose.



Target shape:



\~\~\~json

{

&#x20; "requirement\_id": "REQ-001",

&#x20; "test\_cases": \[

&#x20;   {

&#x20;     "title": "Login succeeds with valid credentials",

&#x20;     "preconditions": \["User account exists"],

&#x20;     "steps": \["Open login page", "Enter valid username/password", "Submit"],

&#x20;     "expected\_result": "User is authenticated and redirected to dashboard",

&#x20;     "priority": "high",

&#x20;     "type": "positive"

&#x20;   }

&#x20; ],

&#x20; "assumptions": \[],

&#x20; "notes": ""

}

\~\~\~



This is required for:

\- schema validation

\- repeatable scoring

\- lower ambiguity

\- more realistic QA artifacts



\### 2. Gold dataset philosophy



Do not assume one perfect answer exists.



Each requirement should define:

\- required coverage points

\- acceptable variants

\- known bad assumptions

\- review notes



The gold dataset should support scoring, not exact string matching.



\### 3. Hybrid scoring only



The scoring model is intentionally hybrid.



Use automatic checks for:

\- schema validity

\- required coverage point matching

\- forbidden assumption detection

\- obvious contradiction checks



Use human review for:

\- borderline semantic cases

\- reviewer usefulness

\- adjudication when automatic signals are inconclusive



\## Dataset design



\### MVP size

\- first working milestone: 10 requirement snippets

\- real MVP: 30 to 50 requirement snippets



\### Dataset mix

Include:

\- happy-path requirements

\- validation/error-handling requirements

\- permission/role-based requirements

\- edge-case requirements

\- ambiguous requirements

\- incomplete requirements that should trigger caution



\### Per-requirement fields

Each requirement record should include:

\- requirement\_id

\- requirement\_text

\- domain\_tag

\- difficulty

\- gold\_test\_cases

\- required\_coverage\_points

\- disallowed\_assumptions

\- review\_notes



\## Scoring model



Each scoring dimension uses a 0 to 2 scale.



\### Dimensions

1\. Correctness

2\. Completeness

3\. Hallucination risk

4\. Reviewer usefulness



\### Definitions

\- \*\*Correctness\*\*

&#x20; - 2 = materially correct

&#x20; - 1 = mostly correct, minor issues

&#x20; - 0 = materially wrong, misleading, or off-target



\- \*\*Completeness\*\*

&#x20; - 2 = all must-cover points addressed

&#x20; - 1 = partial coverage

&#x20; - 0 = major omissions



\- \*\*Hallucination risk\*\*

&#x20; - 2 = low hallucination risk

&#x20; - 1 = minor unsupported assumptions

&#x20; - 0 = substantial invention



\- \*\*Reviewer usefulness\*\*

&#x20; - 2 = clear, usable, time-saving

&#x20; - 1 = somewhat useful but noisy or vague

&#x20; - 0 = not worth using



\### Suggested weights

\- correctness: 0.35

\- completeness: 0.30

\- hallucination\_risk: 0.20

\- reviewer\_usefulness: 0.15



\### Pass rule

A sample passes if:

\- correctness >= 1

\- completeness >= 1

\- hallucination\_risk >= 1

\- weighted total >= threshold



\### Suggested decision bands

\- Pass: 1.6 to 2.0 average

\- Borderline: 1.2 to 1.59

\- Fail: below 1.2



\## Human review queue



Borderline review is a core design feature, not an afterthought.



Route a sample to review when:

\- weighted score falls in the borderline band

\- correctness is uncertain

\- coverage matching is inconclusive

\- forbidden-assumption detection is ambiguous

\- output is structurally valid but semantically questionable



Store review records with:

\- run\_id

\- requirement\_id

\- review\_decision

\- reviewer\_notes

\- final\_scores



Human review exists to:

\- avoid false certainty

\- preserve auditability

\- support override traceability

\- reflect realistic QA process



\## Reporting



Each run should produce:

\- raw CSV with per-sample results

\- markdown summary report

\- review queue output

\- run manifest



\### Report sections

1\. Run summary

2\. Quality gate recommendation

3\. Failure analysis

4\. Trend comparison



\### Quality gate recommendation examples

\- Recommended for assisted internal use with reviewer oversight

\- Not recommended for routine use

\- Promising, but high hallucination risk in ambiguous requirements



\### Failure analysis should highlight

\- top failure categories

\- common missing coverage points

\- common hallucinated assumptions

\- hardest requirement domains

\- low-usefulness outputs



\## Versioning and reproducibility



Every run must track:

\- model\_name

\- model\_version

\- prompt\_version

\- dataset\_version

\- scoring\_version

\- threshold\_version

\- timestamp

\- git\_commit\_hash

\- config\_file



This is what makes the repo an evaluation harness instead of a one-off script.



\## Run flow



Primary command:



\~\~\~bash

python -m harness.run\_eval --config configs/run\_v1.yaml

\~\~\~



That command should:

1\. load run config

2\. generate model outputs

3\. evaluate them

4\. create a review queue

5\. write the report

6\. save the run manifest



Secondary commands may exist for development:

\- generate

\- evaluate

\- report



\## Implementation phases



\### Phase 1: foundation

Deliver:

\- JSON schema for requirements and outputs

\- 10 requirement snippets

\- gold annotations

\- one prompt

\- one model adapter

\- scoring script

\- markdown report



\### Phase 2: real MVP

Deliver:

\- 30 to 50 snippets

\- all four scoring dimensions

\- borderline review queue

\- run metadata

\- prompt/model comparison

\- trend summary report



\### Phase 3: polish

Only after MVP works:

\- charts

\- better CLI

\- CI checks

\- stronger docs

\- stronger tests

\- second model

\- second prompt version



\## First milestone



The first real milestone is:



\*\*Evaluate 10 requirement snippets with one prompt and one model, and produce a scored markdown report.\*\*



Do not start with:

\- dashboards

\- generalized framework building

\- many artifact types

\- broad platform features



\## Readme priorities



The README should explain:

1\. the problem

2\. the MVP

3\. the evaluation method

4\. why this matters

5\. how to run it

6\. what a sample report looks like

7\. known limitations



Be explicit about limitations:

\- gold set subjectivity

\- narrow domain coverage

\- heuristic scoring limits



\## Senior-level project signal



This repo should communicate:



\*\*AI outputs are variable, so I built QA controls around them.\*\*



That means the project should visibly emphasize:

\- reproducibility

\- measurement over hype

\- controlled experiments

\- explicit risk handling

\- reviewer escalation

\- dataset versioning

\- audit trail

\- failure analysis



\## One-sentence pitch



Built a Python evaluation harness for AI-generated QA test cases, using a gold dataset, rubric-based scoring, human review for borderline outputs, and trend reporting across prompt/model versions.

