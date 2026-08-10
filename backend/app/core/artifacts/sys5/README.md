# SYS5 — System Qualification Test Case generation

Generates SYS5 test cases from SYS2 System Requirements plus the project's supporting
workbooks, using LangGraph and `ChatOpenAI` against an on-prem gpt-oss-120b endpoint.

```python
from app.core.artifacts.sys5 import generate

path = generate({
    "project_name": "tmhc_demo",
    "input_folder_path": "_input_dir",
    "output_folder_path": "_output_dir",
    "req_filename": "TE_TMHC_HILS Development & Testing_System Requirements.xlsx",
    "req_sheet_name": "005",     # "" runs every feature sheet
})
```

Returns the path of the generated `.xlsx`, or of a `.zip` when several feature sheets
were run. Connection settings come from the environment — see `backend/.env.example`.

## The guarantee

Every signal, command, compound command, library, tolerance and parameter value written
into a test step must exist in one of the input sheets. This is enforced structurally,
not by prompting alone:

1. **Deterministic Python does the extraction.** Ingestion, tracing, validation and
   rendering never ask the model anything. The LLM is used for exactly two judgement
   calls — which aspects of a requirement need testing, and the ordered steps for one
   aspect.
2. **One Vocabulary Index serves both sides.** The list of legal names handed to the
   model in the prompt *is* the list the validator checks against, so the model cannot
   be permitted something the validator would reject, and vice versa.
3. **Every generated case is validated and repaired.** Grammar, vocabulary, structure,
   semantics and coverage are checked; failures carry machine-readable codes and
   suggestions that drive a bounded repair round.
4. **Unfixable cases ship marked, not dropped.** A case that exhausts its repair budget
   is written with `[VALIDATION_FAILED: …]` in its first remark so a reviewer can see
   what needs a human.

## Pipeline

```
discover → classify → parse → select → index → trace
   → plan (LLM)  → Send fan-out → generate (LLM) → validate → repair (LLM) ⟲
   → render → finalise
```

| Stage | What it does |
|---|---|
| `ingest/` | Classifies every sheet by fingerprint (not filename), then parses it. Handles offset header rows, floating notes, merged cells and block-structured sheets. |
| `indexing/` | Builds the Vocabulary Index; traces each requirement to its data via feature-column `○` marks, explicit id references and fuzzy matching; renders a token-budgeted context pack. |
| `prompts/`, `llm/` | Planner / generator / repair prompts. `StructuredCaller` walks a capability ladder (`json_schema → json_mode → function_calling → text`) so a self-hosted endpoint without `response_format` still works. |
| `validation/` | Grammar, vocabulary, structure, semantics, coverage. |
| `output/` | Pluggable templates. `tmhc_v1` ships; see below. |
| `projects/` | Per-customer rules: step verbs, id formats, tab naming, requirement-id policy. |

## Step grammar

`Set <name>` · `Wait` · `Verify <name>` · `Lib_<Fn> <signal>(K=V,…)` ·
`Compound <Name>` · `Test_start` / `End_of_test`

`Lib_*` is legal only if that exact signature is in *Library List*; `Compound` only if
that block exists in the compound-commands workbook. `Read` is rejected — it prints, it
does not assert.

## Adding the next output format

The pipeline produces canonical `TestCase` objects that know nothing about columns or
sheets. To add a layout:

1. Copy `output/templates/_skeleton/` to `output/templates/<name>/`.
2. Fill in `columns()`, `sheets()` and, if the row shape differs, `emit_rows()`.
3. Add the module path to `registry._BUILTIN_MODULES`.
4. Select it with `SYS5_OUTPUT_TEMPLATE=<name>` or `config["output_template"]`.

Nothing in `ingest/`, `indexing/`, `validation/` or `graph.py` changes. The contract test
in `tests/artifacts/sys5/test_output_templates.py` picks up the new template
automatically, so the existing layout cannot regress. An unknown template name aborts the
run in milliseconds, before any LLM call.

## Adding a project

Add a `ProjectProfile` in `projects/` and register it. If the new project's supporting
workbooks have shapes the registry does not know, add a `SheetFingerprint` in
`ingest/registry.py` and a parser under `ingest/sources/`.

## Known gaps

The **Test Pattern**, **Item_List** and **Configurable_Parameters** sheets are rendered
as labelled placeholders pending their reference layouts. Filling them in touches
`output/templates/tmhc_v1/` only.
