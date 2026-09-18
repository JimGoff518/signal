---
name: investigate
description: Research a SIGNAL cluster with Descrybe (certification precedent, manufacturer history, Texas authority, memo citation check) and save the addendum to the cluster row so it shows on the dashboard. Use when Jim or Jack says "/investigate <cluster id>", "research cluster N", or asks which clusters are worth investigating.
---

# /investigate — Descrybe research addendum for one cluster

You are working for Goff Law PLLC. The output is read by lawyers deciding
whether to open a file. Only cite what Descrybe returns. Never fill a gap from
memory: an empty search is reported as empty.

Descrybe tools are the `mcp__claude_ai_Descrybe_Legal_Engine__*` tools. If they
are deferred, load them first with ToolSearch:
`select:mcp__claude_ai_Descrybe_Legal_Engine__search_cases_by_concept,mcp__claude_ai_Descrybe_Legal_Engine__search_case_text,mcp__claude_ai_Descrybe_Legal_Engine__check_case_status,mcp__claude_ai_Descrybe_Legal_Engine__search_laws_and_rules,mcp__claude_ai_Descrybe_Legal_Engine__extract_case_references,mcp__claude_ai_Descrybe_Legal_Engine__find_case_from_reference`

Python is always `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`.

## 1. Pick the cluster

- Argument given (a cluster id, or a dashboard URL like `/cluster/1234`): use it.
- No argument: run `python scripts/research.py candidates` and ask which one.
  Do not pick for the user.

## 2. Read the dossier

Run `python scripts/research.py show <id>`. From the component and the
narratives, write one sentence describing the defect in litigation terms
(e.g. "dual-clutch transmission shudder and loss of power, uniform across
2012–2016 model years"). If the dossier says an addendum already exists, tell
the user and confirm before overwriting.

## 3. Research, in this order

Run the searches for one section, read them, then move on. Keep 4–6
authorities per section; drop anything Descrybe marks as negatively treated
unless the negative treatment is itself the point.

**a. Certification precedent.** `search_cases_by_concept`, focus
`legal_issue`, jurisdiction `Federal`, term = the defect sentence plus
"class certification Rule 23(b)(3) predominance economic loss". Then the same
with jurisdiction `Texas`. Flag Fifth Circuit and Texas federal district
decisions. Run `check_case_status` on every case you keep.

**b. Manufacturer history.** `search_case_text` for the make and model plus
two or three component words from the narratives (e.g. "Ford Focus PowerShift
transmission"). Keep opinions about this manufacturer and this defect or a
close cousin: certification rulings, motions to dismiss, settlement approvals.

**c. Texas authority.** `search_laws_and_rules`, jurisdiction `Texas`,
`doc_type` `statute`, one query per cause of action the memo names. Defaults if
there is no memo: DTPA (Tex. Bus. & Com. Code §§ 17.46, 17.50), implied
warranty of merchantability (§ 2.314), products liability (Civ. Prac. & Rem.
Code ch. 82), limitations and the 15-year repose (§§ 16.003, 16.012).

**d. Memo citation check.** If a viability memo exists, run
`extract_case_references` on it. For each reference, `find_case_from_reference`
then `check_case_status`. Report any citation Descrybe cannot find as
"NOT FOUND IN DESCRYBE — do not rely on it".

## 4. Write the addendum

Plain text, under 900 words, this shape exactly. The dashboard renders it
pre-wrapped and turns URLs into links, so put each Descrybe URL on the same
line as its case.

```
BOTTOM LINE
Two or three sentences: does the precedent favor certifying this defect as an
economic-loss class, what is the strongest authority, what is the biggest risk.

CERTIFICATION PRECEDENT
- Case name, citation (court year). One-line holding. Treatment: <indicator>.
  <descrybe url>
...

MANUFACTURER HISTORY
- Same format. If nothing relevant came back: "Descrybe returned no opinions
  involving <make> <model> and this defect."

TEXAS AUTHORITY
- Statute citation — what it gives this case in one line. <url>
...

MEMO CITATION CHECK
- <as cited in memo> → found as <case, cite>, treatment <indicator>
  | NOT FOUND IN DESCRYBE — do not rely on it
(or "No viability memo on file.")

WHAT TO PULL NEXT
1. ...
2. ...
3. ...

Sources: Descrybe Legal Engine, <today's date>. Every authority above was
returned by Descrybe; nothing was added from memory.
```

Save it to the scratchpad as `research-<id>.txt`.

## 5. Save and report

Run `python scripts/research.py save <id> --file <path>`. Confirm the word
count it prints. Tell the user the cluster page now carries the addendum
(`/cluster/<id>` on the dashboard) and give the bottom line in one sentence.
