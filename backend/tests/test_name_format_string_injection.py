"""Format-string / template-injection metacharacters in ``name`` echo verbatim.

``app/main.py`` already sits at 100% line + branch coverage, so these tests chase
*behaviour*, not lines. They pin a slice of the ``POST /api/hello`` name-echo
contract that the existing suites leave unpinned.

``TestSecurityInputs`` (test_main.py) pins that SQL-injection, emoji, RTL and
zero-width names echo back unchanged; ``TestNameEchoBoundaries`` (test_edge_cases.py)
pins length, whitespace and control-character boundaries. **None** of them pins the
one adversarial class most coupled to *how the greeting is built* — **format-string
and template metacharacters**:

* Python ``str.format`` replacement fields — ``{}``, ``{0}``, ``{name}``,
  ``{0.__class__}`` (the classic attribute-traversal info-leak vector).
* ``printf``/``%``-style conversions — ``%s``, ``%d``, ``%(name)s``.
* shell / JS template-literal syntax — ``${name}``, ``$name``.
* unbalanced braces — a lone ``{`` or ``}``.

The handler builds the greeting with an **f-string** (``f"Hello, {request.name}! …"``),
which substitutes ``request.name`` as a *value* — so every string above must come
back **verbatim**, byte-for-byte, with a 200. The danger these pins guard against is
a refactor of the greeting to interpolate the *user value* as a format template —
e.g. ``GREETING_TEMPLATE.format(request.name)`` (positional) or ``template % name``.
Under such a refactor:

* ``{0}`` / ``%s`` would consume a positional arg that does not exist →
  ``IndexError`` / ``TypeError`` → **500** on parseable input (a
  format-string-injection-shaped DoS).
* a lone ``{`` / ``}`` would raise ``ValueError`` → **500**.
* ``{0.__class__}`` could resolve attributes on an internal object and **leak
  internals** into the response body.

Pinning verbatim echo keeps the greeting a value-substitution — never a
user-controlled format template.
"""

import pytest
from fastapi.testclient import TestClient

from .conftest import expected_greeting

# Names that are legal, ordinary strings but that carry meaning to one templating
# engine or another. Every one must round-trip *verbatim* through the value-only
# f-string the handler uses. Grouped by the dialect that would (mis)interpret them.
FORMAT_METACHAR_NAMES = [
    # --- Python str.format replacement fields ---
    ("{}", "empty-format-field"),
    ("{0}", "positional-format-field"),
    ("{name}", "named-format-field"),
    ("{0.__class__}", "attribute-traversal-format-field"),
    ("{0[0]}", "index-traversal-format-field"),
    ("Hi {name}, welcome", "named-field-embedded-in-text"),
    # --- printf / %-style conversions ---
    ("%s", "printf-string-conversion"),
    ("%d", "printf-int-conversion"),
    ("%(name)s", "printf-mapping-key"),
    ("100%", "trailing-percent"),
    # --- shell / JS template-literal syntax ---
    ("${name}", "dollar-brace-template"),
    ("$name", "bare-dollar-var"),
    ("`${x}`", "js-backtick-template"),
    # --- unbalanced / stray braces ---
    ("{", "lone-open-brace"),
    ("}", "lone-close-brace"),
    ("a{b}c{d", "unbalanced-mixed-braces"),
    ("{{escaped}}", "doubled-braces"),
]


class TestFormatStringMetacharactersEchoVerbatim:
    """A ``name`` full of format/template metacharacters echoes back byte-for-byte.

    The greeting is built by value-substituting ``request.name`` into an f-string,
    so none of these strings is ever *interpreted* as a format template. Each is
    asserted against :func:`~tests.conftest.expected_greeting`, which pins the
    **exact** final message — not just ``name in message`` — so a regression that
    dropped, escaped, or re-interpreted any metacharacter fails loudly.
    """

    @pytest.mark.parametrize(
        "name,why",
        FORMAT_METACHAR_NAMES,
        ids=[why for _, why in FORMAT_METACHAR_NAMES],
    )
    def test_metacharacter_name_round_trips_exactly(
        self, client: TestClient, name: str, why: str
    ) -> None:
        """A format/template metacharacter name yields 200 with the exact greeting."""
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200, (
            f"{why}: a name containing format/template metacharacters must be treated "
            f"as an opaque value, not a format template — got {response.status_code}: "
            f"{response.text!r}"
        )
        assert response.json()["message"] == expected_greeting(name), (
            f"{why}: greeting for {name!r} was not a verbatim value substitution — "
            f"the name may be getting re-interpreted as a format template"
        )


class TestFStringDoesNotReInterpolateName:
    """The name is substituted once, as a value — never re-scanned for more fields.

    ``{name}`` is the *literal replacement field* the handler's own greeting
    template would use if it were built with ``str.format``. Sending that exact
    string as the name is the sharpest probe for a double-interpolation bug: with
    the current f-string it is echoed verbatim; a naive
    ``GREETING_TEMPLATE.format(name=request.name)`` **followed by a second
    ``.format()``**, or any code that formats the user value itself, would either
    raise or substitute the *template's* name back in — collapsing ``{name}`` into
    something else. Pinning the verbatim echo of the literal field token catches
    that class of regression directly.
    """

    def test_literal_name_field_token_is_not_expanded(self, client: TestClient) -> None:
        """A name of exactly ``{name}`` echoes as ``{name}`` — no re-expansion."""
        response = client.post("/api/hello", json={"name": "{name}"})
        assert response.status_code == 200
        message = response.json()["message"]
        assert message == expected_greeting("{name}")
        # The literal braces must survive; a re-``format`` pass would have consumed
        # them (and either raised or substituted the greeting's own name back in).
        assert "{name}" in message, (
            f"the literal replacement-field token {{name}} was expanded away: {message!r}"
        )

    def test_attribute_traversal_field_does_not_leak_internals(self, client: TestClient) -> None:
        """``{0.__class__}`` is echoed verbatim and leaks no object internals.

        Under a ``template.format(request.name)`` refactor this token would resolve
        ``request.name.__class__`` and splice the class repr into the response — the
        canonical Python format-string information-disclosure vector. The verbatim
        echo proves no attribute traversal happened: the response contains the raw
        token and none of the tell-tale leak strings.
        """
        name = "{0.__class__}"
        response = client.post("/api/hello", json={"name": name})
        assert response.status_code == 200
        message = response.json()["message"]
        assert message == expected_greeting(name)
        # Nothing resembling a resolved attribute/class repr leaked into the body.
        assert "class '" not in message and "<class" not in message, (
            f"attribute-traversal token appears to have been resolved: {message!r}"
        )
