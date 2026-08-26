"""Tests for the `type: questions` executor.

Covers:
- normalize_source_questions / resolve_inline_questions.
- The interactive loop (answer, skip, skip-all, back, abort) via a
  scripted _read_line.
- --skip-gates: defaults win, everything else is skipped, no suggested
  choice is ever auto-selected.
- Output shape: answers/items/transcript/counts/answered_any/outcome.
- Closed-stdin (EOFError) raises rather than spinning.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from rich.console import Console

from conductor.exceptions import ExecutionError
from conductor.executor.questions import (
    QuestionsExecutor,
    ResolvedQuestion,
    normalize_source_questions,
    resolve_inline_questions,
)


def _quiet_console() -> Console:
    return Console(file=open("/dev/null", "w"), force_terminal=False)  # noqa: SIM115


def _executor(lines: list[str], skip_gates: bool = False) -> QuestionsExecutor:
    ex = QuestionsExecutor(console=_quiet_console(), skip_gates=skip_gates)
    ex._read_line = AsyncMock(side_effect=lines)  # type: ignore[method-assign]
    return ex


class TestNormalizeSourceQuestions:
    def test_plain_strings(self) -> None:
        resolved = normalize_source_questions(["Why?", "When?"])
        assert [q.id for q in resolved] == ["q1", "q2"]
        assert resolved[0].text == "Why?"
        assert resolved[0].choices is None

    def test_dicts_with_choices(self) -> None:
        resolved = normalize_source_questions(
            [{"question": "Server or client?", "choices": ["Server", "Client"]}]
        )
        assert resolved[0].text == "Server or client?"
        assert resolved[0].choices == ["Server", "Client"]

    def test_text_key_alias(self) -> None:
        resolved = normalize_source_questions([{"text": "hi"}])
        assert resolved[0].text == "hi"

    def test_verbatim_no_jinja_rendering(self) -> None:
        """Text that looks like a template must NOT be rendered."""
        resolved = normalize_source_questions(["Should this use {{ user.id }}?"])
        assert resolved[0].text == "Should this use {{ user.id }}?"

    def test_explicit_id_preserved(self) -> None:
        resolved = normalize_source_questions([{"id": "rollout", "text": "How?"}])
        assert resolved[0].id == "rollout"

    def test_empty_source_rejected(self) -> None:
        with pytest.raises(ExecutionError, match="empty list"):
            normalize_source_questions([])

    def test_entry_missing_text_rejected(self) -> None:
        with pytest.raises(ExecutionError, match="no 'question'/'text'"):
            normalize_source_questions([{"choices": ["a"]}])

    def test_non_string_non_dict_entry_rejected(self) -> None:
        with pytest.raises(ExecutionError, match="expected a string or a dict"):
            normalize_source_questions([42])

    def test_non_string_choices_rejected(self) -> None:
        with pytest.raises(ExecutionError, match="'choices' must be a list of strings"):
            normalize_source_questions([{"text": "q", "choices": [1, 2]}])


class TestResolveInlineQuestions:
    def test_renders_text_and_hint(self) -> None:
        from conductor.config.schema import QuestionDef

        defs = [QuestionDef(text="Use {{ x }}?", hint="context: {{ x }}")]
        resolved = resolve_inline_questions(defs, lambda t: t.replace("{{ x }}", "flag"))
        assert resolved[0].text == "Use flag?"
        assert resolved[0].hint == "context: flag"

    def test_default_id_by_position(self) -> None:
        from conductor.config.schema import QuestionDef

        defs = [QuestionDef(text="a"), QuestionDef(text="b")]
        resolved = resolve_inline_questions(defs, lambda t: t)
        assert [q.id for q in resolved] == ["q1", "q2"]


class TestQuestionsExecutorInteractive:
    @pytest.mark.asyncio
    async def test_simple_free_text_answers(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="Name?", choices=None, multiline=False),
            ResolvedQuestion(id="q2", text="Age?", choices=None, multiline=False),
        ]
        ex = _executor(["Alice", "30"])
        out = await ex.execute(questions)
        assert out.answers == {"q1": "Alice", "q2": "30"}
        assert out.answered_count == 2
        assert out.skipped_count == 0
        assert out.answered_any is True
        assert out.outcome == "completed"
        assert "Q1. Name?" in out.transcript
        assert "A: Alice" in out.transcript

    @pytest.mark.asyncio
    async def test_choice_by_index(self) -> None:
        questions = [ResolvedQuestion(id="q1", text="Pick", choices=["A", "B", "C"])]
        ex = _executor(["2"])
        out = await ex.execute(questions)
        assert out.answers == {"q1": "B"}
        assert out.items[0]["source"] == "choice"

    @pytest.mark.asyncio
    async def test_invalid_choice_index_reprompts(self) -> None:
        questions = [ResolvedQuestion(id="q1", text="Pick", choices=["A", "B"])]
        ex = _executor(["99", "1"])
        out = await ex.execute(questions)
        assert out.answers == {"q1": "A"}

    @pytest.mark.asyncio
    async def test_free_text_override_when_choices_present(self) -> None:
        questions = [ResolvedQuestion(id="q1", text="Pick", choices=["A", "B"])]
        ex = _executor(["Something else entirely"])
        out = await ex.execute(questions)
        assert out.answers == {"q1": "Something else entirely"}
        assert out.items[0]["source"] == "free_text"

    @pytest.mark.asyncio
    async def test_free_text_disallowed_forces_choice(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="Pick", choices=["A", "B"], allow_free_text=False)
        ]
        ex = _executor(["nope", "1"])
        out = await ex.execute(questions)
        assert out.answers == {"q1": "A"}

    @pytest.mark.asyncio
    async def test_skip_records_default(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="Rollout?", default="Behind a flag", multiline=False)
        ]
        ex = _executor([":skip"])
        out = await ex.execute(questions, allow_skip=True)
        assert out.answers == {"q1": "Behind a flag"}
        assert out.items[0]["source"] == "default"
        assert out.answered_count == 1
        assert out.skipped_count == 0
        # Only a default was consumed -- the human didn't actually engage.
        assert out.answered_any is False

    @pytest.mark.asyncio
    async def test_skip_without_default_omitted_from_answers(self) -> None:
        questions = [ResolvedQuestion(id="q1", text="Optional?", multiline=False)]
        ex = _executor([":skip"])
        out = await ex.execute(questions, allow_skip=True)
        assert out.answers == {}
        assert out.skipped_count == 1
        assert out.items[0]["skipped"] is True

    @pytest.mark.asyncio
    async def test_skip_all(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="a", multiline=False),
            ResolvedQuestion(id="q2", text="b", multiline=False),
            ResolvedQuestion(id="q3", text="c", multiline=False),
        ]
        ex = _executor([":skip-all"])
        out = await ex.execute(questions, allow_skip_all=True)
        assert out.outcome == "skipped_remaining"
        assert out.skipped_count == 3

    @pytest.mark.asyncio
    async def test_back_overwrites_previous_answer(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="a", multiline=False),
            ResolvedQuestion(id="q2", text="b", multiline=False),
        ]
        # Answer q1="first", move to q2, go back, re-answer q1="second", answer q2="ok".
        ex = _executor(["first", ":back", "second", "ok"])
        out = await ex.execute(questions, allow_back=True)
        assert out.answers == {"q1": "second", "q2": "ok"}

    @pytest.mark.asyncio
    async def test_back_disallowed_at_first_question_reprompts(self) -> None:
        """allow_back only applies once idx > 0; at q1 the flag is forced
        False. ':back' must be rejected and re-prompted -- NEVER recorded as
        the literal answer, which would corrupt the reviewer's real answer."""
        questions = [ResolvedQuestion(id="q1", text="a", multiline=False)]
        ex = _executor([":back", "real answer"])
        out = await ex.execute(questions, allow_back=True)
        assert out.answers == {"q1": "real answer"}

    @pytest.mark.asyncio
    async def test_abort(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="a", multiline=False),
            ResolvedQuestion(id="q2", text="b", multiline=False),
        ]
        ex = _executor([":abort"])
        out = await ex.execute(questions, allow_abort=True)
        assert out.outcome == "aborted"
        assert out.answers == {}

    @pytest.mark.asyncio
    async def test_required_question_cannot_skip_without_default(self) -> None:
        """allow_skip is computed by the caller (engine): passing
        allow_skip=False simulates a required, default-less question.
        ':skip' must be rejected and re-prompted, never recorded as the
        literal answer."""
        questions = [ResolvedQuestion(id="q1", text="a", required=True, multiline=False)]
        ex = _executor([":skip", "answered anyway"])
        out = await ex.execute(questions, allow_skip=False)
        assert out.answers == {"q1": "answered anyway"}

    @pytest.mark.asyncio
    async def test_skip_all_blocked_when_a_remaining_question_is_required(self) -> None:
        """One ':skip-all' must not bypass a later required question's own
        guard -- the exact bug upstream's questions-node review caught."""
        questions = [
            ResolvedQuestion(id="q1", text="a", multiline=False),
            ResolvedQuestion(id="q2", text="b", required=True, multiline=False),
        ]
        ex = _executor([":skip-all", "answer1", "answer2"])
        out = await ex.execute(questions, allow_skip=True, allow_skip_all=True)
        # skip-all is rejected at q1 (q2 is required with no default), so
        # both questions are answered normally instead.
        assert out.answers == {"q1": "answer1", "q2": "answer2"}
        assert out.outcome == "completed"

    @pytest.mark.asyncio
    async def test_skip_all_allowed_once_no_remaining_required_question(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="a", multiline=False),
            ResolvedQuestion(id="q2", text="b", required=True, default="d", multiline=False),
        ]
        ex = _executor([":skip-all"])
        out = await ex.execute(questions, allow_skip_all=True)
        assert out.answers == {"q2": "d"}
        assert out.outcome == "skipped_remaining"

    @pytest.mark.asyncio
    async def test_multiline_free_text_joins_lines(self) -> None:
        questions = [ResolvedQuestion(id="q1", text="Explain", multiline=True)]
        ex = _executor(["line one", "line two", "."])
        out = await ex.execute(questions)
        assert out.answers == {"q1": "line one\nline two"}


class TestQuestionsExecutorSkipGates:
    @pytest.mark.asyncio
    async def test_defaults_win_rest_skipped(self) -> None:
        questions = [
            ResolvedQuestion(id="q1", text="a", default="fallback"),
            ResolvedQuestion(id="q2", text="b"),
        ]
        ex = QuestionsExecutor(console=_quiet_console(), skip_gates=True)
        out = await ex.execute(questions)
        assert out.answers == {"q1": "fallback"}
        assert out.items[0]["source"] == "default"
        assert out.items[1]["source"] == "skipped"
        assert out.outcome == "skipped_remaining"
        assert out.answered_any is False

    @pytest.mark.asyncio
    async def test_never_auto_selects_a_suggested_choice(self) -> None:
        questions = [ResolvedQuestion(id="q1", text="Pick", choices=["A", "B"])]
        ex = QuestionsExecutor(console=_quiet_console(), skip_gates=True)
        out = await ex.execute(questions)
        assert out.answers == {}
        assert out.items[0]["source"] == "skipped"


class TestQuestionsExecutorClosedStdin:
    @pytest.mark.asyncio
    async def test_eof_raises_instead_of_looping(self) -> None:
        """Closed stdin must fail loudly once, not spin retrying forever."""
        questions = [ResolvedQuestion(id="q1", text="a", multiline=False)]
        ex = QuestionsExecutor(console=_quiet_console())
        with (
            patch("conductor.executor.questions.Prompt.ask", side_effect=EOFError()),
            pytest.raises(ExecutionError, match="stdin closed"),
        ):
            await ex.execute(questions)
