"""Output parsing and validation for agent responses.

This module provides functions for validating agent output against
declared output schemas.
"""

from __future__ import annotations

from typing import Any

from conductor.config.schema import OutputField
from conductor.exceptions import ValidationError

# JSON-schema metadata keys an LLM may echo instead of returning the bare value.
# When a dict's keys are entirely within this set, it is a schema-echo wrapper
# and the real payload should be extracted (see _unwrap_string).
_SCHEMA_ECHO_KEYS = frozenset(
    {
        "type",
        "description",
        "title",
        "default",
        "example",
        "examples",
        "enum",
        "format",
        "value",
        "content",
        "properties",
        "items",
        "required",
    }
)


def validate_output(
    content: dict[str, Any],
    schema: dict[str, OutputField],
) -> None:
    """Validate agent output against declared schema.

    Checks that all required fields are present, have the correct type, and
    satisfy any declared constraints (``enum``, ``pattern``, ``minimum``/
    ``maximum``, ``min_length``/``max_length``). A field marked ``optional``
    may be absent; a field marked ``nullable`` may be JSON ``null``. Only
    fields present in ``content`` are mutated (e.g. string-unwrapping);
    undeclared keys are left untouched.

    Args:
        content: Agent's output content as a dictionary.
        schema: Expected output schema with field definitions.

    Raises:
        ValidationError: If output doesn't match schema (missing fields,
            wrong types, or a violated constraint).

    Example:
        >>> from conductor.config.schema import OutputField
        >>> schema = {"answer": OutputField(type="string")}
        >>> validate_output({"answer": "Hello"}, schema)  # OK
        >>> validate_output({}, schema)  # Raises ValidationError
    """
    for field_name, field_def in schema.items():
        if field_name not in content:
            if field_def.optional:
                continue
            raise ValidationError(
                f"Missing required output field: {field_name}",
                suggestion=f"Ensure agent returns '{field_name}' in output",
            )

        value = content[field_name]

        if value is None:
            if field_def.nullable:
                continue
            raise ValidationError(
                f"Output field '{field_name}' is null but is not marked 'nullable'",
                suggestion=f"Ensure agent returns a non-null '{field_name}', or set nullable: true",
            )

        expected_type = field_def.type

        # Unwrap dict-wrapped strings: some LLMs (e.g. DeepSeek via
        # Anthropic-compatible endpoints) return {"text": "..."} or
        # {"type": "text", "text": "..."} instead of a plain string.
        if expected_type == "string" and isinstance(value, dict):
            unwrapped = _unwrap_string(value)
            if unwrapped is not None:
                content[field_name] = unwrapped
                value = unwrapped

        # Type checking
        if not _check_type(value, expected_type):
            raise ValidationError(
                f"Output field '{field_name}' has wrong type: "
                f"expected {expected_type}, got {type(value).__name__}",
                suggestion=f"Ensure agent returns correct type for '{field_name}'",
            )

        _check_constraints(field_name, value, field_def)

        # Recursively validate nested structures
        if expected_type == "object" and field_def.properties and isinstance(value, dict):
            validate_output(value, field_def.properties)

        if expected_type == "array" and field_def.items and isinstance(value, list):
            item_def = field_def.items
            for i, item in enumerate(value):
                item_label = f"Array item {i} in '{field_name}'"
                if item is None:
                    if item_def.nullable:
                        continue
                    raise ValidationError(
                        f"{item_label} is null but items are not marked 'nullable'",
                        suggestion=f"Ensure every item in '{field_name}' is non-null, "
                        "or set items.nullable: true",
                    )
                if not _check_type(item, item_def.type):
                    raise ValidationError(
                        f"{item_label} has wrong type: "
                        f"expected {item_def.type}, got {type(item).__name__}",
                        suggestion=f"Ensure all items in '{field_name}' have correct type",
                    )
                _check_constraints(item_label, item, item_def)
                if item_def.type == "object" and item_def.properties and isinstance(item, dict):
                    validate_output(item, item_def.properties)


def _check_constraints(label: str, value: Any, field_def: OutputField) -> None:
    """Enforce enum/pattern/range/length constraints on an already type-checked value.

    Args:
        label: Human-readable field label for error messages (e.g. the field
            name, or ``"Array item 2 in 'foo'"``).
        value: The already type-checked value.
        field_def: The field's schema, carrying the optional constraints.

    Raises:
        ValidationError: If a declared constraint is violated.
    """
    if field_def.enum is not None and value not in field_def.enum:
        raise ValidationError(
            f"Output field '{label}' has value {value!r}, "
            f"which is not one of the allowed values: {field_def.enum!r}",
            suggestion=f"Ensure '{label}' is one of {field_def.enum!r}",
        )

    if field_def.pattern is not None and isinstance(value, str):
        import re

        if not re.search(field_def.pattern, value):
            raise ValidationError(
                f"Output field '{label}' with value {value!r} does not match "
                f"pattern {field_def.pattern!r}",
                suggestion=f"Ensure '{label}' matches the pattern {field_def.pattern!r}",
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if field_def.minimum is not None and value < field_def.minimum:
            raise ValidationError(
                f"Output field '{label}' with value {value!r} is below the "
                f"minimum of {field_def.minimum!r}",
                suggestion=f"Ensure '{label}' is >= {field_def.minimum!r}",
            )
        if field_def.maximum is not None and value > field_def.maximum:
            raise ValidationError(
                f"Output field '{label}' with value {value!r} is above the "
                f"maximum of {field_def.maximum!r}",
                suggestion=f"Ensure '{label}' is <= {field_def.maximum!r}",
            )

    if isinstance(value, (str, list)):
        length = len(value)
        if field_def.min_length is not None and length < field_def.min_length:
            raise ValidationError(
                f"Output field '{label}' has length {length}, "
                f"below the minimum of {field_def.min_length}",
                suggestion=f"Ensure '{label}' has at least {field_def.min_length} "
                f"{'characters' if isinstance(value, str) else 'items'}",
            )
        if field_def.max_length is not None and length > field_def.max_length:
            raise ValidationError(
                f"Output field '{label}' has length {length}, "
                f"above the maximum of {field_def.max_length}",
                suggestion=f"Ensure '{label}' has at most {field_def.max_length} "
                f"{'characters' if isinstance(value, str) else 'items'}",
            )


def _unwrap_string(value: dict[str, Any]) -> str | None:
    """Try to extract a string value from a dict-wrapped LLM output.

    Some LLMs (e.g. DeepSeek via Anthropic-compatible endpoints) return
    ``{"text": "actual content"}`` or ``{"type": "text", "text": "..."}``
    instead of a plain string. This helper attempts to unwrap such dicts.

    As a fallback for complex nested dicts (parsed YAML/JSON), the dict is
    re-serialized as YAML so downstream scripts receive the original text.

    Returns the extracted string, or None if the dict doesn't look like
    a wrapped string.
    """
    # Anthropic content block: {"type": "text", "text": "..."}
    if "text" in value and isinstance(value.get("text"), str):
        return str(value["text"])
    # Schema-echo dict: some models (e.g. DeepSeek via Anthropic-compatible
    # endpoints) parrot the output field's JSON schema instead of returning the
    # bare string, e.g. {"type": "string", "description": "...", "value": "..."}.
    # When every key is JSON-schema metadata, extract the real payload (commonly
    # under "value") rather than re-serializing the whole schema as YAML.
    if value and set(value.keys()) <= _SCHEMA_ECHO_KEYS:
        for payload_key in ("value", "content", "default", "example"):
            if isinstance(value.get(payload_key), str):
                return value[payload_key]
        # Pure {type, description} echo where the content landed in description.
        if "type" in value and isinstance(value.get("description"), str):
            return value["description"]
    # Generic single-string-key dict: {"content": "..."}
    str_vals = {k: v for k, v in value.items() if isinstance(v, str)}
    if len(str_vals) == 1 and len(value) <= 2:
        return list(str_vals.values())[0]
    # Complex nested dict (parsed YAML/JSON): re-serialize as YAML
    try:
        from io import StringIO

        from ruamel.yaml import YAML

        yaml = YAML()
        buf = StringIO()
        yaml.dump(value, buf)
        return buf.getvalue()
    except Exception:
        return None


def _check_type(value: Any, expected: str) -> bool:
    """Check if value matches expected type.

    Args:
        value: The value to check.
        expected: The expected type name (string, number, boolean, array, object).

    Returns:
        True if value matches expected type, False otherwise.
    """
    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    expected_types = type_map.get(expected)
    if expected_types is None:
        # Unknown type - accept any value
        return True

    # Special handling for number type to exclude booleans
    # (in Python, bool is a subclass of int)
    if expected == "number" and isinstance(value, bool):
        return False

    return isinstance(value, expected_types)


def parse_json_output(raw_response: str) -> dict[str, Any]:
    """Parse JSON from an agent's raw response.

    Attempts to extract JSON from the response, handling common cases
    like markdown code blocks.

    Args:
        raw_response: The raw text response from the agent.

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        ValidationError: If JSON parsing fails.
    """
    import json
    import re

    text = raw_response.strip()

    # Try to extract JSON from markdown code blocks. Two-stage strategy:
    # 1. Non-greedy findall + try-parse each candidate (first valid wins).
    #    Handles the common case of multiple fenced blocks in one response
    #    (e.g. "initial answer ... revised answer") where the first complete
    #    JSON block is the authoritative one.
    # 2. Greedy single capture as fallback. Handles the case where the JSON
    #    contains literal ``` inside a string field, which breaks non-greedy
    #    matching at the inner fence but is recovered by closing at the LAST
    #    fence in the response.
    candidates = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    for candidate in candidates:
        stripped = candidate.strip()
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
            return {"result": result}
        except json.JSONDecodeError:
            continue
    greedy = re.search(r"```(?:json)?\s*\n?(.*)\n?```", text, re.DOTALL)
    if greedy:
        text = greedy.group(1).strip()

    # Try to find JSON object or array
    if not text.startswith(("{", "[")):
        # Try to find first { or [
        obj_start = text.find("{")
        arr_start = text.find("[")

        if obj_start >= 0 and (arr_start < 0 or obj_start < arr_start):
            text = text[obj_start:]
        elif arr_start >= 0:
            text = text[arr_start:]

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        # If result is not a dict, wrap it
        return {"result": result}
    except json.JSONDecodeError as e:
        raise ValidationError(
            f"Failed to parse JSON from agent response: {e}",
            suggestion="Ensure agent outputs valid JSON format",
        ) from e
