"""End-to-end runs of the whole graph, offline.

A fake chat model stands in for the on-prem endpoint, so these exercise ingestion,
selection, tracing, planning, the ``Send`` fan-out, validation, the repair loop and
rendering without touching the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.core.artifacts.sys5 import Sys5Error, generate
from app.core.artifacts.sys5.indexing import VocabularyIndex
from app.core.artifacts.sys5.llm import StructuredCaller
from app.core.artifacts.sys5.validation import parse_step, validate_case

from .conftest import REQ_FILENAME
from .fake_llm import FakeChatModel


@pytest.fixture
def fake_model() -> FakeChatModel:
    return FakeChatModel(prompts=[], generation_calls=0)


@pytest.fixture
def run(monkeypatch, fake_model, input_dir: Path, tmp_path: Path):
    """Runs :func:`generate` with the fake model injected."""

    def _run(**overrides):
        monkeypatch.setattr(
            "app.core.artifacts.sys5.sys5.build_chat_model", lambda settings: fake_model
        )
        config = {
            "project_name": "tmhc_demo",
            "username": "test@tataelxsi.co.in",
            "version": "V1.0",
            "domain": "automotive",
            "artifact": "SYS5",
            "model": "llm-1-gpt-oss-120b",
            "input_folder_path": str(input_dir),
            "output_folder_path": str(tmp_path / "out"),
            "work_dir": str(tmp_path / "work"),
            "uploaded_files": [],
            "agent_chain": [
                {"agent_name": "generation_agent", "agent_version": "V1.0", "prompt_content": ""},
            ],
            "req_filename": REQ_FILENAME,
            "req_sheet_name": "005",
            "llm_base_url": "http://fake/v1",
            "llm_api_key": "fake-key",
        }
        config.update(overrides)
        return Path(generate(config))

    return _run


class TestSingleSheetRun:
    def test_produces_one_xlsx_in_the_output_directory(self, run, tmp_path: Path):
        output = run()
        assert output.suffix == ".xlsx"
        assert output.parent == tmp_path / "out"
        assert output.name.startswith("sys5_005_")

    def test_only_the_workbook_lands_in_the_output_directory(self, run, tmp_path: Path):
        run()
        produced = list((tmp_path / "out").iterdir())
        assert [p.suffix for p in produced] == [".xlsx"]

    def test_intermediates_are_written_to_the_working_directory(self, run, tmp_path: Path):
        run()
        names = {p.name for p in (tmp_path / "work").rglob("*.json")}
        assert {"inventory.json", "selected_005.json", "plans_005.json",
                "generated_005.json", "summary_005.json"} <= names

    def test_workbook_has_the_expected_structure(self, run):
        workbook = load_workbook(run())
        assert workbook.sheetnames == [
            "Cover", "Test Pattern", "Item_List", "005", "Configurable_Parameters"
        ]
        assert workbook["Cover"]["C3"].value == "005 - Ramp / Slope Control"

    def test_one_case_per_selected_requirement(self, run):
        sheet = load_workbook(run())["005"]
        ids = {
            sheet.cell(row=r, column=1).value
            for r in range(2, sheet.max_row + 1)
            if sheet.cell(row=r, column=1).value
        }
        # Two requirements are selected; the fake planner returns one case each.
        assert ids == {"TMHC_SQTC_01", "TMHC_SQTC_02"}

    def test_requirement_id_column_uses_the_section_number(self, run):
        sheet = load_workbook(run())["005"]
        values = {
            sheet.cell(row=r, column=4).value
            for r in range(2, sheet.max_row + 1)
            if sheet.cell(row=r, column=4).value
        }
        assert values == {"5.1.1.3", "5.1.1.4"}

    def test_doors_id_is_preserved_in_the_first_remark(self, run):
        sheet = load_workbook(run())["005"]
        remarks = " ".join(
            str(sheet.cell(row=r, column=16).value or "") for r in range(2, sheet.max_row + 1)
        )
        assert "TMHC_SYSRS_GR005010" in remarks
        assert "TMHC_SYSRS_GR005011" in remarks

    def test_every_step_name_exists_in_the_source_sheets(self, run, index: VocabularyIndex, profile):
        """The anti-hallucination guarantee, checked against the rendered workbook."""
        sheet = load_workbook(run())["005"]
        checked = 0
        for row in range(2, sheet.max_row + 1):
            text = sheet.cell(row=row, column=10).value
            if not text:
                continue
            node = parse_step(str(text), profile.allowed_verbs)
            assert node.is_valid, f"row {row}: {text!r} is not a legal step"
            if node.target:
                assert node.target in index, f"row {row}: {node.target!r} is not in any input sheet"
                checked += 1
        assert checked > 0


class TestRepairLoop:
    def test_invalid_first_draft_is_repaired(self, run, fake_model):
        fake_model.fail_first_generation = True
        sheet = load_workbook(run())["005"]

        texts = [
            sheet.cell(row=r, column=10).value
            for r in range(2, sheet.max_row + 1)
            if sheet.cell(row=r, column=10).value
        ]
        # The broken draft's contents must be gone from the output entirely.
        assert not any("Nonexistent_Signal" in str(t) for t in texts)
        assert not any(str(t).startswith("Read ") for t in texts)

        remarks = " ".join(
            str(sheet.cell(row=r, column=16).value or "") for r in range(2, sheet.max_row + 1)
        )
        assert "VALIDATION_FAILED" not in remarks

    def test_repair_is_attempted_only_within_budget(self, run, fake_model):
        fake_model.fail_first_generation = True
        run(max_correction_attempts=0)
        repair_prompts = [p for p in fake_model.prompts if "failed automated validation" in p]
        assert repair_prompts == []

    def test_unrepaired_case_is_marked_rather_than_dropped(self, run, fake_model):
        fake_model.fail_first_generation = True
        sheet = load_workbook(run(max_correction_attempts=0))["005"]
        remarks = " ".join(
            str(sheet.cell(row=r, column=16).value or "") for r in range(2, sheet.max_row + 1)
        )
        # The case still ships, flagged, so a reviewer can see what needs a human.
        assert "VALIDATION_FAILED" in remarks


class TestStructuredOutputLadder:
    def test_falls_back_to_text_when_the_endpoint_lacks_structured_output(
        self, run, fake_model
    ):
        run()
        # The fake model refuses every native method, so the caller must have landed on
        # the plain-text rung and still produced usable output.
        assert fake_model.generation_calls > 0

    def test_caller_records_the_working_method(self, fake_model):
        from app.core.artifacts.sys5.prompts import PlanResponse

        caller = StructuredCaller(fake_model, method="auto")
        caller.invoke(PlanResponse, "system", "Plan every SYS5 test case for this")
        assert caller.method == "text"
        assert caller.calls == 1


class TestMultiSheetRun:
    def test_empty_sheet_name_zips_one_workbook_per_feature(self, run, tmp_path: Path):
        import zipfile

        output = run(req_sheet_name="")
        assert output.suffix == ".zip"

        with zipfile.ZipFile(output) as archive:
            names = sorted(archive.namelist())
        assert len(names) == 2
        assert any(n.startswith("sys5_005_") for n in names)
        assert any(n.startswith("sys5_006_") for n in names)

    def test_each_feature_workbook_is_titled_for_its_own_feature(self, run, tmp_path: Path):
        import zipfile

        output = run(req_sheet_name="")
        extracted = tmp_path / "extracted"
        with zipfile.ZipFile(output) as archive:
            archive.extractall(extracted)

        titles = {}
        for path in extracted.glob("*.xlsx"):
            workbook = load_workbook(path)
            titles[path.name.split("_")[1]] = workbook["Cover"]["C3"].value
        assert titles == {
            "005": "005 - Ramp / Slope Control",
            "006": "006 - Parking Brake",
        }

    def test_feature_tracing_does_not_leak_across_sheets(self, run, tmp_path: Path):
        """A signal marked only against 006 must not appear in the 005 workbook."""
        import json

        run(req_sheet_name="005")
        traced = json.loads(
            next((tmp_path / "work").rglob("plans_005.json")).read_text(encoding="utf-8")
        )
        assert traced, "expected at least one plan for sheet 005"

        sheet = load_workbook(run(req_sheet_name="005"))["005"]
        body = " ".join(
            str(sheet.cell(row=r, column=c).value or "")
            for r in range(2, sheet.max_row + 1)
            for c in (10, 11, 13)
        )
        assert "Fork_Height_Sensor" not in body


class TestFailFast:
    def test_unknown_output_template_aborts_before_any_llm_call(self, run, fake_model):
        with pytest.raises(Sys5Error, match="unknown output template"):
            run(output_template="does_not_exist")
        assert fake_model.prompts == []

    def test_unknown_requirement_sheet_is_an_error(self, run):
        with pytest.raises(Sys5Error, match="not found"):
            run(req_sheet_name="999")

    def test_empty_input_directory_is_an_error(self, run, tmp_path: Path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        with pytest.raises(Sys5Error, match="no .xlsx inputs"):
            run(input_folder_path=str(empty))

    def test_missing_llm_credentials_are_reported_clearly(self, input_dir: Path, tmp_path: Path,
                                                          monkeypatch):
        for name in ("SYS5_LLM_BASE_URL", "SYS5_LLM_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(Sys5Error, match="base_url"):
            generate(
                {
                    "project_name": "tmhc_demo",
                    "input_folder_path": str(input_dir),
                    "output_folder_path": str(tmp_path / "out2"),
                    "work_dir": str(tmp_path / "work2"),
                    "req_filename": REQ_FILENAME,
                    "req_sheet_name": "005",
                }
            )


class TestGeneratedCasesValidate:
    def test_rendered_cases_pass_a_fresh_validation_pass(self, run, index, profile, tmp_path):
        """Re-validate from the persisted JSON, independently of the run that made it."""
        import json

        run()
        payload = json.loads(
            next((tmp_path / "work").rglob("generated_005.json")).read_text(encoding="utf-8")
        )
        from app.core.artifacts.sys5.models import TestCase

        for raw in payload:
            case = TestCase.model_validate(raw)
            assert validate_case(case, index, profile).ok, case.tc_id
