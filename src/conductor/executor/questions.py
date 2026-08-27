"""Execution for `type: questions` workflow steps.

A `questions` step asks a human a SET of questions inside one workflow step,
holding the cursor and the answers internally. This is the CLI-only,
terminal-driven half of the feature: there is no web-dashboard rendering
(the JSON output is still visible in the dashboard's generic agent-output
panel, just without a dedicated interactive widget) and no mid-node resume
(a crash mid-question-set restarts the whole node — the engine's checkpoint
only captures state between steps, same as any other step type).

Two ways to get a question list:

- ``source:`` — a dotted-path reference to a runtime array (same convention
  as `for_each`'s ``source:``), resolved by the engine and normalized here
  via :func:`normalize_source_questions`. Entries may be plain strings (each
  becomes a question with no choices) or dicts with a ``question``/``text``
  key and optionally ``choices``. Text is used VERBATIM — never Jinja2
  rendered — because it may itself contain literal ``{{ }}`` content read
  from evidence a prior agent inspected, and rendering that would raise
  instead of asking the human.
- ``questions:`` — an inline, author-written list of ``QuestionDef``, fully
  Jinja2-rendered (``text``/``hint``) via :func:`resolve_inline_questions`.

``--skip-gates`` never invents an answer: questions with a ``default`` take
it (recorded as ``source="default"``); every other question is skipped. No
suggested ``choices`` value is ever auto-selected, since that would feed
model-invented candidates back into the workflow as though a human typed
them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from rich.panel import Panel
from rich.prompt import Prompt as _RichPrompt

from conductor.exceptions import ExecutionError

if TYPE_CHECKING:
    from conductor.config.schema import QuestionDef


class Prompt(_RichPrompt):
    """Rich's ``Prompt`` with no decorative ``": "`` suffix.

    Conductor's own control tokens (``:back``, ``:skip``, ...) already own
    the leading colon. Rich's default ``prompt_suffix = ": "`` would render
    a second, purely decorative colon right next to them — e.g. ``"> : "`` —
    which reads as part of the command and led a real user to type ``back``
    instead of ``:back``, expecting the colon they saw on screen to already
    be there. Suppressing it removes the ambiguity.
    """

    prompt_suffix = ""


AnswerSource = Literal["choice", "free_text", "default", "skipped"]
QuestionsOutcome = Literal["completed", "skipped_remaining", "aborted"]

# Control tokens recognized instead of an answer. Colon-prefixed so a
# free-text answer that happens to be the bare word "skip" isn't misread as
# a command.
_BACK = ":back"
_SKIP = ":skip"
_SKIP_ALL = ":skip-all"
_ABORT = ":abort"


@dataclass
class ResolvedQuestion:
    """One question ready to present, regardless of its original source."""

    id: str
    text: str
    hint: str | None = None
    choices: list[str] | None = None
    allow_free_text: bool = True
    default: str | None = None
    required: bool = False
    multiline: bool = True


@dataclass
class AnswerRecord:
    """One recorded answer (or skip)."""

    id: str
    question: str
    answer: str | None
    source: AnswerSource

    @property
    def skipped(self) -> bool:
        return self.source == "skipped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "skipped": self.skipped,
        }


@dataclass
class QuestionsOutput:
    """Result of a ``questions`` step, stored as ``<step>.output``."""

    answers: dict[str, str]
    items: list[dict[str, Any]]
    transcript: str
    answered_count: int
    skipped_count: int
    answered_any: bool
    outcome: QuestionsOutcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "answers": self.answers,
            "items": self.items,
            "transcript": self.transcript,
            "answered_count": self.answered_count,
            "skipped_count": self.skipped_count,
            "answered_any": self.answered_any,
            "outcome": self.outcome,
        }


def normalize_source_questions(raw: list[Any]) -> list[ResolvedQuestion]:
    """Normalize ``source:``-resolved entries into :class:`ResolvedQuestion`.

    Entries are plain strings or dicts; text is used verbatim (no Jinja2
    rendering — see module docstring). IDs default to ``q1``..``qN`` by
    position.

    Args:
        raw: The resolved array from workflow context.

    Returns:
        Ordered list of resolved questions.

    Raises:
        ExecutionError: If an entry is neither a string nor a dict with a
            ``question``/``text`` key, or the resolved array is empty.
    """
    if not raw:
        raise ExecutionError(
            "questions step: 'source' resolved to an empty list",
            suggestion="Ensure the upstream agent produced at least one question.",
        )

    resolved: list[ResolvedQuestion] = []
    for i, entry in enumerate(raw, start=1):
        default_id = f"q{i}"
        if isinstance(entry, str):
            resolved.append(ResolvedQuestion(id=default_id, text=entry))
            continue
        if isinstance(entry, dict):
            text = entry.get("question") or entry.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ExecutionError(
                    f"questions step: source entry {i} has no 'question'/'text' string",
                    suggestion="Each source entry must be a string, or a dict with a "
                    "'question' or 'text' key.",
                )
            choices = entry.get("choices")
            if choices is not None and not (
                isinstance(choices, list) and all(isinstance(c, str) for c in choices)
            ):
                raise ExecutionError(
                    f"questions step: source entry {i}'s 'choices' must be a list of strings"
                )
            resolved.append(
                ResolvedQuestion(
                    id=str(entry.get("id") or default_id),
                    text=text,
                    hint=entry.get("hint"),
                    choices=choices,
                    allow_free_text=bool(entry.get("allow_free_text", True)),
                    default=entry.get("default"),
                    required=bool(entry.get("required", False)),
                    multiline=bool(entry.get("multiline", True)),
                )
            )
            continue
        raise ExecutionError(
            f"questions step: source entry {i} is a {type(entry).__name__}, "
            "expected a string or a dict",
            suggestion="Each source entry must be a plain string or a dict with a "
            "'question'/'text' key.",
        )
    return resolved


def resolve_inline_questions(
    defs: list[QuestionDef],
    render: Any,
) -> list[ResolvedQuestion]:
    """Render an inline ``questions:`` list's Jinja2 fields.

    Unlike ``source:`` entries, inline questions are author-written YAML and
    get full Jinja2 rendering on ``text``/``hint`` (matching how the rest of
    the workflow is authored).

    Args:
        defs: The validated ``QuestionDef`` list from the workflow YAML.
        render: A ``str -> str`` callable that renders one Jinja2 template
            (typically ``TemplateRenderer.render`` bound to the step context).

    Returns:
        Ordered list of resolved questions.
    """
    resolved: list[ResolvedQuestion] = []
    for i, q in enumerate(defs, start=1):
        resolved.append(
            ResolvedQuestion(
                id=q.id or f"q{i}",
                text=render(q.text),
                hint=render(q.hint) if q.hint else None,
                choices=q.choices,
                allow_free_text=q.allow_free_text,
                default=q.default,
                required=q.required,
                multiline=q.multiline,
            )
        )
    return resolved


class QuestionsExecutor:
    """Runs one ``type: questions`` step's terminal interaction.

    Example::

        executor = QuestionsExecutor(skip_gates=skip_gates)
        output = await executor.execute(questions, intro=agent.prompt_rendered,
                                         allow_back=True, allow_skip=True,
                                         allow_skip_all=True, allow_abort=False)
    """

    def __init__(self, console: Console | None = None, skip_gates: bool = False) -> None:
        self.console = console or Console()
        self.skip_gates = skip_gates

    async def execute(
        self,
        questions: list[ResolvedQuestion],
        *,
        intro: str | None = None,
        allow_back: bool = True,
        allow_skip: bool = True,
        allow_skip_all: bool = True,
        allow_abort: bool = False,
    ) -> QuestionsOutput:
        """Present every question and return the collected answers.

        Args:
            questions: Ordered questions to present.
            intro: Optional intro text rendered once above the first question.
            allow_back: Allow revising the previous answer.
            allow_skip: Allow skipping one question.
            allow_skip_all: Allow skipping every remaining question.
            allow_abort: Allow abandoning the node entirely.

        Returns:
            The collected :class:`QuestionsOutput`.
        """
        if self.skip_gates:
            return self._skip_gates_output(questions)

        if intro:
            self.console.print()
            self.console.print(
                Panel(
                    RichMarkdown(intro),
                    title="[bold cyan]Questions[/bold cyan]",
                    border_style="cyan",
                )
            )

        answers: dict[str, AnswerRecord] = {}
        aborted = False
        used_skip_all = False
        idx = 0
        while idx < len(questions):
            q = questions[idx]
            # skip_all is blocked outright when ANY remaining question is
            # required with no default -- computed fresh every question
            # since "remaining" shrinks as idx advances. Without this, one
            # ':skip-all' bypasses every required question's own guard, the
            # exact bug upstream's questions-node review caught.
            skip_all_ok = allow_skip_all and not any(
                later.required and later.default is None for later in questions[idx:]
            )
            action, value = await self._ask_one(
                q,
                idx,
                len(questions),
                allow_back=allow_back and idx > 0,
                allow_skip=allow_skip and (not q.required or q.default is not None),
                allow_skip_all=skip_all_ok,
                allow_abort=allow_abort,
            )

            if action == "abort":
                aborted = True
                break
            if action == "back":
                idx -= 1
                answers.pop(questions[idx].id, None)
                continue
            if action == "skip":
                answers[q.id] = self._skip_record(q)
                idx += 1
                continue
            if action == "skip_all":
                used_skip_all = True
                for remaining in questions[idx:]:
                    answers[remaining.id] = self._skip_record(remaining)
                idx = len(questions)
                continue
            # action == "answer"
            assert value is not None
            source: AnswerSource = "choice" if q.choices and value in q.choices else "free_text"
            answers[q.id] = AnswerRecord(id=q.id, question=q.text, answer=value, source=source)
            idx += 1

        outcome: QuestionsOutcome = (
            "aborted" if aborted else "skipped_remaining" if used_skip_all else "completed"
        )
        return self._build_output(questions, answers, outcome)

    @staticmethod
    def _skip_record(q: ResolvedQuestion) -> AnswerRecord:
        if q.default is not None:
            return AnswerRecord(id=q.id, question=q.text, answer=q.default, source="default")
        return AnswerRecord(id=q.id, question=q.text, answer=None, source="skipped")

    def _skip_gates_output(self, questions: list[ResolvedQuestion]) -> QuestionsOutput:
        self.console.print(
            "\n[dim]Auto-resolving questions (--skip-gates): "
            "defaults where set, skipped otherwise[/dim]"
        )
        answers = {q.id: self._skip_record(q) for q in questions}
        outcome: QuestionsOutcome = "skipped_remaining"
        return self._build_output(questions, answers, outcome)

    def _build_output(
        self,
        questions: list[ResolvedQuestion],
        answers: dict[str, AnswerRecord],
        outcome: QuestionsOutcome,
    ) -> QuestionsOutput:
        items: list[dict[str, Any]] = []
        transcript_lines: list[str] = []
        answered_count = 0
        skipped_count = 0
        answered_any = False
        final_answers: dict[str, str] = {}

        for i, q in enumerate(questions, start=1):
            record = answers.get(q.id) or AnswerRecord(
                id=q.id, question=q.text, answer=None, source="skipped"
            )
            items.append(record.to_dict())
            if record.skipped:
                skipped_count += 1
                transcript_lines.append(f"Q{i}. {q.text}\nA: (skipped)")
            else:
                answered_count += 1
                final_answers[record.id] = record.answer or ""
                if record.source in ("choice", "free_text"):
                    answered_any = True
                transcript_lines.append(f"Q{i}. {q.text}\nA: {record.answer}")

        return QuestionsOutput(
            answers=final_answers,
            items=items,
            transcript="\n\n".join(transcript_lines),
            answered_count=answered_count,
            skipped_count=skipped_count,
            answered_any=answered_any,
            outcome=outcome,
        )

    async def _ask_one(
        self,
        q: ResolvedQuestion,
        index: int,
        total: int,
        *,
        allow_back: bool,
        allow_skip: bool,
        allow_skip_all: bool,
        allow_abort: bool,
    ) -> tuple[Literal["answer", "skip", "skip_all", "back", "abort"], str | None]:
        """Present one question and return the resolved action.

        Loops on invalid input (an unrecognized control token, a choice
        index out of range, or free text when free text isn't allowed)
        rather than guessing — a workflow author's typo shouldn't silently
        record the wrong answer.
        """
        body_lines = [q.text]
        if q.hint:
            body_lines.append(f"\n_{q.hint}_")
        if q.choices:
            body_lines.append("")
            body_lines.extend(f"  {i + 1}. {c}" for i, c in enumerate(q.choices))
        self.console.print()
        self.console.print(
            Panel(
                RichMarkdown("\n".join(body_lines)),
                title=f"[bold cyan]Question {index + 1}/{total}[/bold cyan]",
                border_style="cyan",
            )
        )

        commands = []
        if q.choices:
            commands.append(f"1-{len(q.choices)}=choose")
        if q.allow_free_text:
            commands.append("multi-line" if (q.multiline and not q.choices) else "type an answer")
        if allow_back:
            commands.append(f"{_BACK}=back")
        if allow_skip:
            commands.append(f"{_SKIP}=skip" + (f" (default: {q.default!r})" if q.default else ""))
        if allow_skip_all:
            commands.append(f"{_SKIP_ALL}=skip all remaining")
        if allow_abort:
            commands.append(f"{_ABORT}=abort")
        self.console.print(f"[dim]{' | '.join(commands)}[/dim]")

        while True:
            if q.multiline and not q.choices and q.allow_free_text:
                first_line = await self._read_line("> ")
                control = self._check_control(
                    first_line, allow_back, allow_skip, allow_skip_all, allow_abort
                )
                if control == "disallowed":
                    continue
                if control is not None:
                    return control, None
                if not first_line:
                    self.console.print("[red]Empty answer — type a value or a command.[/red]")
                    continue
                lines = [first_line]
                self.console.print("[dim]Multi-line — end with a line containing only '.'[/dim]")
                while True:
                    line = await self._read_line("")
                    if line == ".":
                        break
                    lines.append(line)
                return "answer", "\n".join(lines)

            raw = await self._read_line("> ")
            control = self._check_control(raw, allow_back, allow_skip, allow_skip_all, allow_abort)
            if control == "disallowed":
                continue
            if control is not None:
                return control, None

            if q.choices and raw.strip().isdigit():
                choice_index = int(raw.strip())
                if 1 <= choice_index <= len(q.choices):
                    return "answer", q.choices[choice_index - 1]
                self.console.print(
                    f"[red]'{raw}' is not a valid choice (1-{len(q.choices)}).[/red]"
                )
                continue

            if not raw:
                self.console.print("[red]Empty answer — type a value or a command.[/red]")
                continue

            if not q.allow_free_text:
                self.console.print(
                    "[red]Free text isn't allowed for this question — "
                    f"choose 1-{len(q.choices or [])}.[/red]"
                )
                continue

            return "answer", raw

    def _check_control(
        self,
        raw: str,
        allow_back: bool,
        allow_skip: bool,
        allow_skip_all: bool,
        allow_abort: bool,
    ) -> Literal["back", "skip", "skip_all", "abort", "disallowed"] | None:
        """Recognize a control token and check whether it's currently allowed.

        Recognition and permission are deliberately separate: returning
        ``None`` for a disallowed-but-recognized token would fall straight
        through to the free-text branch, silently recording the literal
        control string (e.g. ``":skip"``) as the answer -- worse than a
        typo, since it looks like a real answer downstream. A recognized,
        disallowed token always returns ``"disallowed"`` (after printing
        why) so the caller re-prompts instead of falling through.

        Returns ``None`` only when ``raw`` isn't a control token at all.
        """
        token = raw.strip().lower()
        control_map: dict[str, tuple[str, bool]] = {
            _BACK: ("back", allow_back),
            _SKIP: ("skip", allow_skip),
            _SKIP_ALL: ("skip_all", allow_skip_all),
            _ABORT: ("abort", allow_abort),
        }
        match = control_map.get(token)
        if match is None:
            return None
        action, allowed = match
        if allowed:
            return cast(Literal["back", "skip", "skip_all", "abort"], action)
        self.console.print(f"[red]'{token}' isn't available for this question right now.[/red]")
        return "disallowed"

    async def _read_line(self, prompt: str) -> str:
        """Read one line from stdin.

        Raises rather than looping on closed stdin (CI without
        ``--skip-gates``, piped input with no more lines): retrying a
        ``Prompt.ask`` against an already-closed stdin raises the same
        ``EOFError`` on every attempt, and looping on it is a tight
        zero-latency spin, not a hang — this is the difference between
        "fails loudly once" and "burns CPU forever." Unconditional
        regardless of ``allow_abort``: there is no configured escape hatch
        to route to and no more input to read, so continuing to ask isn't
        an option either way.
        """
        try:
            return await asyncio.to_thread(Prompt.ask, prompt, console=self.console)
        except EOFError as exc:
            raise ExecutionError(
                "questions step: stdin closed while waiting for an answer",
                suggestion="Run this workflow attended, or pass --skip-gates for "
                "unattended runs (defaults apply, the rest are skipped).",
            ) from exc
