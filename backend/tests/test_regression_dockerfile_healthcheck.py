r"""Regression pins for the Dockerfile ``HEALTHCHECK``/``curl`` ordering fix (#309).

The container image defines a Docker ``HEALTHCHECK`` that shells out to ``curl``::

    HEALTHCHECK ... CMD curl -f http://localhost:8000/health || exit 1

``curl`` is **not** in the ``python:3.11-slim`` base image — it has to be installed
explicitly with ``apt-get``. Bug #309 was that the ``RUN apt-get install ... curl``
layer sat *after* the ``HEALTHCHECK`` directive, so the health probe referenced a
binary that the preceding layers had not provided. The fix (commit ``c940e62``)
moved the ``curl`` install ahead of the ``HEALTHCHECK``.

This failure mode is invisible to the entire Python test suite: ``app/main.py`` is at
100 % coverage and the ``/health`` *endpoint* is exhaustively tested, but nothing
exercises the *image build / health-probe contract*. A regression here would only
surface as a container that never reports healthy — caught (if at all) in the
production smoke/canary path, not in CI. These tests close that gap by parsing the
Dockerfile and pinning the invariants the #309 fix established:

* a ``HEALTHCHECK`` directive exists and there is **exactly one** of it;
* its command invokes ``curl`` against the ``/health`` endpoint;
* ``curl`` is installed by an ``apt-get`` layer that appears **before** the
  ``HEALTHCHECK`` (the exact ordering #309 corrected); and
* that install layer cleans the apt lists (``rm -rf /var/lib/apt/lists/*``) so the
  fix did not regress image-size hygiene.

The tests parse the Dockerfile into *logical* instructions (joining ``\``-continued
lines) so a purely cosmetic reformat — e.g. splitting the ``HEALTHCHECK`` across more
lines — does not make them flap; only a real reordering or a dropped ``curl`` install
trips them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The Dockerfile lives at backend/Dockerfile; this test file is backend/tests/...,
# so parents[1] is the backend/ package root.
DOCKERFILE_PATH = Path(__file__).resolve().parents[1] / "Dockerfile"


class _Instruction:
    """One logical Dockerfile instruction with its keyword, joined text, and line."""

    __slots__ = ("keyword", "text", "line")

    def __init__(self, keyword: str, text: str, line: int) -> None:
        self.keyword = keyword
        self.text = text
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"_Instruction({self.keyword!r}, line={self.line}, text={self.text!r})"


def _logical_instructions(dockerfile_text: str) -> list[_Instruction]:
    """Parse ``dockerfile_text`` into logical instructions, joining ``\\`` continuations.

    Blank lines and ``#`` comments are skipped. A trailing backslash continues the
    instruction onto the next physical line; the parts are joined with a single space
    so a multi-line ``HEALTHCHECK`` reads as one searchable string. ``keyword`` is the
    uppercased first token (``RUN``/``HEALTHCHECK``/...), ``line`` is the 0-based index
    of the instruction's first physical line (used to assert ordering).
    """
    instructions: list[_Instruction] = []
    parts: list[str] = []
    start_line: int | None = None

    for index, raw in enumerate(dockerfile_text.splitlines()):
        stripped = raw.strip()
        if not parts:
            # Looking for the start of a new instruction.
            if not stripped or stripped.startswith("#"):
                continue
            start_line = index
        continues = stripped.endswith("\\")
        content = stripped[:-1].rstrip() if continues else stripped
        parts.append(content)
        if not continues:
            full = " ".join(part for part in parts if part)
            keyword = full.split(maxsplit=1)[0].upper()
            assert start_line is not None
            instructions.append(_Instruction(keyword, full, start_line))
            parts = []
            start_line = None

    if parts:  # pragma: no cover - only if the file ends mid-continuation
        full = " ".join(part for part in parts if part)
        keyword = full.split(maxsplit=1)[0].upper()
        assert start_line is not None
        instructions.append(_Instruction(keyword, full, start_line))

    return instructions


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    """The raw text of ``backend/Dockerfile``."""
    assert DOCKERFILE_PATH.is_file(), (
        f"expected the backend Dockerfile at {DOCKERFILE_PATH} — the health-probe "
        "regression pins below cannot run without it"
    )
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def instructions(dockerfile_text: str) -> list[_Instruction]:
    """The Dockerfile parsed into logical instructions."""
    return _logical_instructions(dockerfile_text)


def _healthcheck(instructions: list[_Instruction]) -> _Instruction:
    """Return the single ``HEALTHCHECK`` instruction, asserting there is exactly one."""
    matches = [ins for ins in instructions if ins.keyword == "HEALTHCHECK"]
    assert len(matches) == 1, (
        f"expected exactly one HEALTHCHECK directive, found {len(matches)}: "
        f"{[m.text for m in matches]!r}"
    )
    return matches[0]


def _curl_install(instructions: list[_Instruction]) -> _Instruction:
    """Return the ``RUN`` instruction that installs ``curl`` via ``apt-get``."""
    matches = [
        ins
        for ins in instructions
        if ins.keyword == "RUN" and "apt-get install" in ins.text and "curl" in ins.text
    ]
    assert matches, (
        "no `RUN apt-get install ... curl` layer found — the HEALTHCHECK shells out to "
        "curl, which is absent from python:3.11-slim and must be installed explicitly "
        "(regression of #309)"
    )
    assert len(matches) == 1, (
        f"expected a single curl-installing RUN layer, found {len(matches)}: "
        f"{[m.text for m in matches]!r}"
    )
    return matches[0]


class TestHealthcheckExistsAndUsesCurlAgainstHealth:
    """The HEALTHCHECK directive is present and probes ``/health`` with ``curl``.

    This anchors the rest of the suite: the ordering pin only matters because the
    health probe genuinely depends on ``curl`` hitting the ``/health`` endpoint. If a
    future edit swapped ``curl`` for an in-image tool (e.g. a Python one-liner) the
    dependency would vanish — these tests would then need revisiting, and failing here
    flags exactly that change rather than letting it pass silently.
    """

    def test_exactly_one_healthcheck_directive_exists(
        self, instructions: list[_Instruction]
    ) -> None:
        """There is one and only one HEALTHCHECK in the Dockerfile."""
        health = _healthcheck(instructions)
        assert health.keyword == "HEALTHCHECK"

    def test_healthcheck_command_invokes_curl(self, instructions: list[_Instruction]) -> None:
        """The HEALTHCHECK command shells out to ``curl`` (the #309 dependency)."""
        health = _healthcheck(instructions)
        assert "curl" in health.text, (
            f"HEALTHCHECK no longer invokes curl: {health.text!r} — if this is "
            "intentional the curl-install ordering pins below are obsolete and should "
            "be revisited"
        )

    def test_healthcheck_targets_the_health_endpoint(
        self, instructions: list[_Instruction]
    ) -> None:
        """The probe curls the ``/health`` liveness endpoint, not some other path."""
        health = _healthcheck(instructions)
        assert "/health" in health.text, (
            f"HEALTHCHECK should probe the /health endpoint, got: {health.text!r}"
        )


class TestCurlInstalledBeforeHealthcheck:
    """The #309 invariant: the ``curl`` install layer precedes the HEALTHCHECK.

    This is the exact bug #309 fixed — ``curl`` was installed *after* the HEALTHCHECK
    was declared. Parsing into logical instructions and comparing first-physical-line
    positions pins the ordering directly, so a Dockerfile edit that moves the apt layer
    back below the HEALTHCHECK (or drops it) fails here in CI instead of in production.
    """

    def test_curl_install_layer_exists(self, instructions: list[_Instruction]) -> None:
        """A dedicated apt-get layer installs curl (it is not in the slim base image)."""
        install = _curl_install(instructions)
        assert install.keyword == "RUN"

    def test_curl_install_appears_before_healthcheck(
        self, instructions: list[_Instruction]
    ) -> None:
        """The curl-installing RUN comes earlier in the file than the HEALTHCHECK."""
        install = _curl_install(instructions)
        health = _healthcheck(instructions)
        assert install.line < health.line, (
            "regression of #309: the `apt-get install curl` layer (line "
            f"{install.line}) must come BEFORE the HEALTHCHECK directive (line "
            f"{health.line}). With curl installed afterwards the health probe "
            "references a binary the image does not yet provide and the container "
            "never reports healthy."
        )

    def test_curl_install_cleans_apt_lists(self, instructions: list[_Instruction]) -> None:
        """The install layer removes apt lists, keeping the fix image-size-clean.

        Pinning the cleanup guards against a well-meaning reorder that drops
        ``rm -rf /var/lib/apt/lists/*`` and silently bloats every image layer — a
        quieter but real regression of the same Dockerfile line.
        """
        install = _curl_install(instructions)
        assert "rm -rf /var/lib/apt/lists/*" in install.text, (
            "the curl-install layer should clean the apt lists "
            f"(`rm -rf /var/lib/apt/lists/*`) in the same RUN, got: {install.text!r}"
        )


class TestDockerfileBaseImageProvidesNoCurl:
    """Documents *why* the explicit install is load-bearing: the base is ``-slim``.

    The whole #309 dependency exists because ``python:3.11-slim`` ships no ``curl``. If
    a future change moved to a fat base image that bundles curl, the explicit install
    (and its ordering) would stop being necessary. Pinning the slim base keeps the
    suite's premise honest: a base-image swap surfaces here so the curl pins can be
    re-evaluated deliberately rather than becoming silently redundant.
    """

    def test_base_image_is_python_slim(self, instructions: list[_Instruction]) -> None:
        """The first instruction is ``FROM python:3.11-slim`` (no bundled curl)."""
        from_instructions = [ins for ins in instructions if ins.keyword == "FROM"]
        assert from_instructions, "Dockerfile has no FROM instruction"
        assert "slim" in from_instructions[0].text, (
            "base image is no longer a -slim variant: "
            f"{from_instructions[0].text!r}. The explicit curl install exists because "
            "slim images omit curl; a non-slim base may bundle it, making the #309 "
            "ordering pins worth revisiting."
        )
