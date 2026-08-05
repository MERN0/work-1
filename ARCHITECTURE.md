# SYS5 Qualification Test Case Generator — Architecture (Phase 1)

Status: **DRAFT — awaiting sign-off.** No implementation code has been written. This
document exists to get the design right before Phase 2 starts.

## 0. What changed since the master prompt

Five images were supplied against open items §12.2–§12.4 (default-format image, TMHC
image, optional-sheet examples). They turned out to be **one reference workbook**
(`sys5_test_cases.xlsx`), five tabs: `Cover`, `Test Pattern`, `Item_List`, `Test_Cases`,
`Configurable_Parameters`. That resolves the "what do the optional sheets look like"
question directly, but it also contradicts three assumptions baked into the master
prompt. Those are called out inline below and collected in §8 — they're genuine
open risks, not something I resolved by guessing.

This repository (`mern0/work-1`) has a single initial commit and no prior SYS5 code,
so §4/§4' (directory structure) is a **from-scratch proposal**, not a correction of
existing code — flagged in §8 as well.

LangGraph syntax was checked against current sources before writing this doc (§7).

---

## 1. Inputs

1.1. **SYS2 requirements workbook(s)** — xlsx, multi-sheet, loaded via openpyxl/pandas.

1.2. **Supporting docs** — zero or more xlsx, each possibly multi-sheet. No key join to
requirements exists; relevance is inferred by an LLM node (§3.2). The
`Configurable_Parameters` tab in the reference workbook (Parameter Name / Description /
per-variant value, e.g. `CAN_HIL_PwrCtrlMode`, `MDL_SWH_Park_Brake`,
`Config_Tol_Spd`) is the clearest concrete example of what a supporting doc looks like
downstream — it's the kind of table `set`/`verify` steps pull literal values and units from.

1.3. **Domain** — run parameter, one of `bcm | telematics | chassis | adas | powertrain`
per the master prompt. **The reference workbook's domain is "Forklift"** (`GeneB`,
variants `A1`/`A2`/`B`), which is not in that list. Flagged in §8 — need to know if this
is a 6th domain to add or if the workbook is structure-only and its domain values
shouldn't be read literally.

1.4. **Config set** — output-format YAML(s), ID-format rule, per-project guideline
file(s), domain prompt files. Revised against the reference workbook in §6.

1.5. **Reference-output workbook** (new, from the images) — treated as the ground-truth
example of the "default" formatter's shape until told otherwise. See §4.1 for the
sheet-by-sheet spec extracted from it.

---

## 2. Preprocessing (pure Python, no LLM calls)

2.1. **Workbook loading** — every sheet from every input workbook, pandas/openpyxl.

2.2. **Row filter** — keep rows where any cell case-insensitively matches
`"sys qualification"` or `"sys5"`; keep the entire row. Configurable to a specific
column instead of whole-row search, via config.

2.3. **Junk-row exclusion** — heuristic (mostly-empty rows, known non-requirement
patterns); the rule set lives in config, not hardcoded.

2.4. **Supporting-doc registry** — in-memory, tagged by `(source_file, sheet_name)`.
Pipeline must run correctly with zero supporting docs supplied.

2.5. **Config loading** — domain param, guideline file(s), ID-format rule,
output-format selection(s).

No changes from the master prompt here; the reference workbook doesn't affect
preprocessing.

---

## 3. Agents (LangGraph nodes)

3.1. `domain_prompt_injector` (pure Python) — domain param → matching
`config/domain_prompts/*.md` snippet.

3.2. `supporting_doc_planner` (LLM) — filtered requirements + supporting-doc registry
→ `SupportingDocUsagePlan`.

3.3. `clustering_agent` (LLM, strict) — requirements + usage plan →
`RequirementCluster[]`. Never merges two requirements if it would drop coverage of
either's testable behavior.

3.4. `test_case_generator` (LLM, domain-aware) — one cluster → `TestCase[]`. **Revised
scope** based on the reference workbook: a generated test case is not a flat
step list. It has three phases (`PRECONDITION` / `ACTION` / `POSTCONDITION`, see §4.1c),
and where a cluster covers multiple behavior variations, the generator is also implicitly
producing the combinatorial design shown in the `Test Pattern` tab (fixed factors held
constant, variable factors swept per test case). Whether that design table is emitted
by this node or reconstructed in postprocessing is an open question (§8).

3.5. `verification_correction_agent` (LLM, loop, max 2 attempts) — checks: correct use
of supporting docs, traceability accuracy, steps-vs-expected-results count parity,
correct `set`/`wait`/`verify` usage. **Revised**: must also validate against whatever
step vocabulary config comes out of §8's step-grammar question, and check phase
completeness (every test case has at least an ACTION phase; PRE/POST optional per
config). Still-failing-after-2 → keep the test case, `needs_review = true`. Never drop,
never halt the run.

3.6. `postprocess` (pure Python) — verified test cases → workbook(s) per §4.

3.7. **Graph wiring** — confirmed against current LangGraph docs (§7):

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

graph = StateGraph(RunState)
graph.add_node("domain_prompt_injector", domain_prompt_injector)
graph.add_node("supporting_doc_planner", supporting_doc_planner)
graph.add_node("clustering_agent", clustering_agent)
graph.add_node("test_case_generator", test_case_generator)
graph.add_node("verification_correction_agent", verification_correction_agent)
graph.add_node("postprocess", postprocess)

graph.add_edge(START, "domain_prompt_injector")
graph.add_edge("domain_prompt_injector", "supporting_doc_planner")
graph.add_edge("supporting_doc_planner", "clustering_agent")
graph.add_edge("clustering_agent", "test_case_generator")
graph.add_edge("test_case_generator", "verification_correction_agent")
graph.add_conditional_edges(
    "verification_correction_agent",
    route_after_verification,   # -> "test_case_generator" (retry) | "postprocess"
)
graph.add_edge("postprocess", END)

app = graph.compile(checkpointer=InMemorySaver())
```

The per-cluster loop (generate → verify → correct, max 2 attempts, mark
`needs_review` on exhaustion) is a conditional edge back into `test_case_generator`
gated on `correction_attempts` in the JSON run-state (§5 of master prompt, unchanged),
not on LangGraph's own checkpoint — the checkpointer complements it for
within-thread resumability but the JSON file is what survives a process restart, per
the original design.

**Shared LLM instantiation** unchanged from the master prompt — `ChatOpenAI` passed
as an object instance (`openai_api_key`, `openai_api_base` pointing at the internal
endpoint), never a provider string, reused across all LLM nodes.

---

## 4. Output generation (pure Python, no LLM)

### 4.1 Sheet-by-sheet spec, extracted from the reference workbook

**(a) `Cover`** — Document No., Version, Created By, Verified By, a free-text change
summary ("Added aliases for Power keep, Battery Over discharge warning"), and a
Revision History table: Revision No. / Change Description / Date / Created by /
Approved by / Description. `Created By` and `Verified By` are literally `"SYS5 AI
Pipeline"` in the example, and Revision 1.0's description reads "Auto-generated for
TICO_HILS_2.0" — implying the pipeline is aware of a **previous revision** and
summarizes what changed. That's new scope not in the original 12-section spec —
flagged in §8, not assumed.

**(b) `Test Pattern`** — two tables: a Factors table (Factor / Element / Ease of
Adjustment, e.g. `Power_Control_Mode: H/P/S/E/L`) and a combinatorial Test Pattern
table splitting factors into **Fixed Factors** (held constant across the cluster's
test cases) and **Variable Factors** (swept per test case), one row per Test Case No.
This is a design-of-experiments worksheet, not the original spec's flat "Test Pattern"
placeholder — needs a new schema (§6).

**(c) `Item_List`** — one row per test case: Test type (`Normal_system` /
`Boundary` observed — an equivalence-class-vs-boundary-value taxonomy), Feature Name,
Test Case ID, Applicable Variants (e.g. `A1/A2/B`), Execution Required (Yes/No),
Remarks. Functions as an index sheet.

**(d) `Test_Cases`** — the main sheet. Columns: Test Case ID, Feature, Applicable
Variants, Requirement IDs, Priority, Mode of Execution, Test Case Description, **Test
Phase** (`PRECONDITION`/`ACTION`/`POSTCONDITION`), Step #, Test Steps, Parameter
Settings, Units, Expected Value, Units, a per-step execute flag, Remarks. Step rows
observed go well beyond `set`/`wait`/`verify` — see §4.4.

**(e) `Configurable_Parameters`** — Forklift Models header → variant columns
(`A1`/`A2`/`B`) → Parameter Name / Description / per-variant value (`-` where not
applicable). This is what a supporting doc looks like once normalized; it's also
plausibly regenerated as an output sheet summarizing which parameters the generated
test cases actually touched.

All five tabs appear together in one workbook with no separate "optional" toggle
visible in the example — see §8 on whether "optional sheets" is still the right
framing.

### 4.2 Backward traceability sheet
Per the master prompt, still built deterministically from `TraceabilityEntry`
(cluster membership + generation metadata, never LLM-guessed). Note: `Test_Cases`
already carries a `Requirement IDs` column per test case, so there may be overlap
with a dedicated sheet — flagged in §8.

### 4.3 Test-case ID
Reference IDs are `TMHC_SQMTC_001`, `TMHC_SQMTC_002`, … — prefix + a fixed-width
sequence, per `config/id_format.yaml`. Whether `TMHC` is project-specific (this
workbook's prefix) or has independent meaning as an output *format* is exactly the
open question in §8 — the ID-prefix reading is the simpler one and is what this doc
assumes unless corrected.

### 4.4 Step grammar — expanded from the master prompt's §7
The master prompt specifies exactly three keywords: `set`, `wait`, `verify`. The
reference `Test_Cases` sheet uses a materially larger vocabulary: `Test_Start`,
`End_of_Test`, `Compound_<name>` (e.g. `Compound Power_On_A1` — looks like a
named macro/sequence, not a primitive), `Wait_Until_<signal>`, and function-call-style
steps carrying inline parameters (e.g. `MDL_SEN_Accelerator_Pedal(Start=30,Stop=0,
Step=5,Time=…)`, `Lib_Ramp`). Steps also carry separate Parameter Settings/Units and
Expected Value/Units columns rather than being a single `keyword + expression`
string. This is a significant deviation from §7 and reshapes the `TestStep` schema
(§6) — not something to silently reconcile; needs your call in §8.

### 4.5 Formatter registry
Unchanged shape from the master prompt (`OutputFormatter` ABC, `FORMATTERS` dict).
What's unresolved is whether `"default"` and `"tmhc"` are actually two different
formatters, or one formatter (matching §4.1's five-sheet shape) parameterized by
per-project config (`config/id_format.yaml` prefix, `config/project_guidelines/`).
See §8.

### 4.6 Merged cells / blank rows
Consistent with the master prompt: one blank row between test cases, and where a
test case's steps span multiple rows, ID/Feature/Requirement IDs/etc. cells merge
across that span — this matches the reference `Test_Cases` layout (e.g. rows 22–31
under one Test Case ID, cells merged down that block).

---

## 5. State / Checkpoint design

Unchanged from the master prompt §5: `state/run_<id>.json`, one entry per cluster
(`cluster_id, requirement_ids, stage, correction_attempts, needs_review`), read/updated
by every node, primary resume mechanism because it must survive process restarts.
LangGraph's own checkpointer (§3.7, §7) complements it for within-thread state but
isn't a substitute.

---

## 6. Pydantic schemas (revised scaffold)

Carried over unchanged: `RequirementRow`, `SupportingDocItem`, `SupportingDocUsagePlan`,
`RequirementCluster`, `TraceabilityEntry`, `VerificationResult`, `RunState`.

Revised / new, based on the reference workbook:

- `TestPatternFactor` — `name, element, ease_of_adjustment` (new — Test Pattern tab, §4.1b).
- `TestPatternRow` — `test_case_no, fixed_values: dict[str, str], variable_values: dict[str, str]` (new).
- `TestStep` — revised: `step_no: int, phase: Literal["precondition","action","postcondition"], keyword: str, raw_text: str, parameters: dict[str, str] | None, parameter_units: str | None, expected_value: str | None, expected_units: str | None, execute: bool = True, remarks: str | None`. `keyword` is validated against a config-driven vocabulary (§8) rather than a hardcoded 3-value `Literal`, since the reference data already exceeds `set/wait/verify`.
- `TestCase` — revised: adds `test_type: Literal["normal_system","boundary"] | str` (Item_List tab) and groups `steps` by phase rather than a flat list; everything else (`id, feature, module, variant, traceability, objective, description, precondition, test_input_data, mode_of_execution, priority, odc_trigger, needs_review`) unchanged.
- `ItemListEntry` — new — `test_type, feature_name, test_case_id, applicable_variants: List[str], execution_required: bool, remarks`.
- `ConfigurableParameterEntry` — new — `name, description, values_by_variant: dict[str, str]`, mirrors the Configurable_Parameters tab for both supporting-doc ingestion and output regeneration.

---

## 7. LangGraph API — verified before writing this doc

`docs.langchain.com` and `reference.langchain.com` returned HTTP 403 to direct fetch
from this environment, so the following is sourced from current search-indexed
snippets (PyPI, LangChain reference index, 2026 walkthroughs) rather than a raw page
fetch — recommend one more live check against the actually-pinned `langgraph` version's
changelog at the start of Phase 2, per your original instruction, since this is a fast-moving API.

Confirmed current shape:
- `from langgraph.graph import StateGraph, START, END`
- `StateGraph(SomeStateType)`, `.add_node(name, fn)`, `.add_edge(a, b)`,
  `.add_conditional_edges(name, router_fn, {...} | [...])`
- `.compile(checkpointer=...)` → `CompiledStateGraph` (Runnable interface)
- Checkpointers live under `langgraph.checkpoint.*`: `InMemorySaver` (current
  preferred name; `MemorySaver` also exists) in `langgraph.checkpoint.memory`,
  `SqliteSaver` in `langgraph.checkpoint.sqlite`, `PostgresSaver` /
  `AsyncPostgresSaver` in `langgraph.checkpoint.postgres[.aio]`.

Sources: [langgraph-checkpoint · PyPI](https://pypi.org/project/langgraph-checkpoint/),
[InMemorySaver reference](https://reference.langchain.com/python/langgraph.checkpoint/memory/InMemorySaver),
[Persistence — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/persistence).

---

## 8. Open risks / questions — need your answer before Phase 2 schema is final

1. **Domain mismatch.** Reference workbook's domain is "Forklift" (`GeneB`,
   variants `A1`/`A2`/`B`), not in `{bcm, telematics, chassis, adas, powertrain}`.
   Add Forklift as a domain, or is the workbook structure-only (ignore its literal
   domain values)?
2. **What is TMHC, actually?** Only one reference workbook was supplied, containing
   all five sheets together, with `TMHC_SQMTC_###` as the ID prefix. That reads as
   "TMHC is this project's ID prefix" rather than "TMHC is a second, differently-shaped
   output format." If so, §9's two-formatter split (default vs. tmhc) may collapse
   into one formatter driven by `id_format.yaml`. Confirm, or provide a second example
   that's actually structured differently from this one.
3. **Step grammar.** The reference sheet's vocabulary (`Test_Start`, `End_of_Test`,
   `Compound_*`, `Wait_Until_*`, function-call-style steps with inline params, plus
   separate Parameter Settings/Units/Expected Value/Units columns) is much richer than
   `set`/`wait`/`verify`. Do you want the grammar expanded to a config-driven keyword
   set (with set/wait/verify as the enforced minimum, `=`/`==` rule kept for those two),
   or is the reference sheet itself non-conformant with the target grammar (i.e. should
   generation be constrained down to exactly the 3 keywords regardless of the example)?
4. **Test Phase as a first-class field.** PRECONDITION/ACTION/POSTCONDITION isn't in
   the master prompt at all. Should every test case always have this three-phase
   structure, or is it domain/project-config-driven?
5. **Test Pattern sheet's origin.** Is it generated automatically (documenting the
   clustering/generation agents' combinatorial reasoning), or is it meant to be a
   human-authored input that steers `test_case_generator`? Assumed auto-generated
   unless corrected.
6. **Sheet optionality.** All five reference sheets appear together with no visible
   on/off toggle. Should the default formatter always emit all five, contradicting the
   master prompt's "generate optional sheets only when explicitly requested"?
7. **Cover-sheet revision diffing.** The free-text change summary and revision history
   imply the pipeline knows what changed vs. a prior run. That's new scope. Should
   Phase 2 implement revision diffing against a previous output workbook, or does a
   human fill in Cover-sheet narrative fields after generation (pipeline leaves them
   templated/blank)?
8. **Traceability sheet vs. `Requirement IDs` column.** `Test_Cases` already carries
   per-test-case requirement IDs. Is the separate backward-traceability sheet still
   required for a different consumer, or does the inline column satisfy that need?
9. **Directory structure.** This repo has no prior SYS5 code — §4 of the master prompt
   is a from-scratch proposal I'm carrying forward with the schema/formatter
   adjustments above, not a correction of an existing layout. Confirm you want a fresh
   build in `mern0/work-1`, or point at the repo that actually holds the prior build.
10. **LLM endpoint details.** Model name, `openai_api_base` internal URL, and API-key
    source (env var vs. secrets manager) aren't provided yet — needed to wire the
    shared `ChatOpenAI` instance in Phase 2.
11. Still pending from the original open-items list: the RTM/output-columns YAML
    itself (§4.1d gives the *columns*, but not things like ID zero-padding width,
    which fields are mandatory vs. optional, or validation rules) — worth providing
    explicitly even though the reference workbook covers most of it.

---

## 9. Sign-off

This document is Phase 1 output. No code will be written until you respond to §8 (or
tell me to proceed with the stated assumptions where I've called them out). Once
resolved, Phase 2 starts incrementally against a small sample workbook before scaling up.
