# Placement Eligibility Checker

Capstone project, CIT AI-Native Engineering Programme, Semester 1, Assessment 5.
Author: Akarshana R (M.Sc. DCS, Coimbatore Institute of Technology)

A console Python tool for the college placement cell. It reads job posts, uses an
LLM to pull out each post's eligibility criteria, checks those criteria in Python,
and drafts a list of eligible students for each job. **Every list is a draft. The
placement officer must check it before it is shared.**

## How it works

1. `jobs.csv` (job posts) and `students.csv` (student records) are loaded.
2. For each post, **only the post text** is sent to the LLM, with the system prompt
   in `system_prompt.txt`. Student records never go to the LLM.
3. The LLM returns five fields: `branches`, `min_cgpa`, `max_backlogs`, `batch`, `summary`.
4. Python validates the reply (`is_valid`), retries once if it is bad, and falls back
   to `needs_review` if it is still bad.
5. Python fact-checks the reply against the post (`check_facts`): a branch, CGPA or
   batch that the post does not actually say is removed.
6. A post with no branches or no CGPA after the fact check is `needs_review`.
   Otherwise it is `matched`, and students are matched with plain Python rules.

Eligibility rule: branch is in the list (or ALL), CGPA >= cut-off, backlogs <= limit
(if stated), and batch matches (if stated).

## Setup (Windows, PowerShell)

```
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a file named `.env` in the project folder with one line (get a free key from
openrouter.ai/keys):

```
OPENROUTER_API_KEY=your-key-here
```

`.env` is listed in `.gitignore`, so the key is never committed. Optional: add
`LLM_MODEL=<model name>` to `.env` to use one fixed model. By default the tool uses
`openrouter/free`, which picks a free model for each call.

## Run

```
python placement_checker.py     # process all jobs, write the 4 output files
python eval.py                  # run the 5 test posts and 3 red-team inputs
```

## Files

| File | Purpose |
|---|---|
| `placement_checker.py` | Main program: loading, LLM call, validation, fact checks, matching, reports |
| `system_prompt.txt` | System prompt (Authority, Exemplar, Constraint, Rubric, Metadata) |
| `jobs.csv`, `students.csv` | Input data (made-up students) |
| `output/job_summary.csv` | Each post's criteria, status and eligible count |
| `output/eligible.csv` | One row per eligible student per job |
| `output/review.csv` | Posts the placement officer must read, with the reason |
| `output/summary.txt` | Eligible count per job, and students eligible for no job yet |
| `eval.py`, `eval_results.txt` | Eval harness (5 posts), red-team tests (3 inputs) and their results |

## Testing

`eval.py` compares results with answers worked out by hand from `students.csv`.
The red-team inputs are: a post that tries to add a student, a percentage cut-off,
and a vague cut-off ("top 10 percent"). Last run: eval 5/5, red-team 3/3.
Free models can answer differently from run to run. If a model gives no valid reply,
the test is reported as INCONCLUSIVE and should be re-run.

## Known limits

- A post that names two batches (for example 2026 and 2027) does not fit the single
  `batch` field, so the placement officer must check it.
- The free tier has a daily request limit. Hitting it makes the LLM calls fail, and
  the posts then fall back to `needs_review`.
