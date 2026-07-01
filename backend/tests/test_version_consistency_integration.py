"""Cross-endpoint runtime version-consistency integration tests.

A client can learn the API's version through **two independent HTTP surfaces**:

* the runtime endpoint ``GET /api/version`` → ``.version``; and
* the served contract ``GET /openapi.json`` → ``.info.version``.

Both values currently originate from ``app.__version__``, but that shared origin
is an *implementation detail*. From a black-box client's perspective these are
two separate responses produced by two separate code paths (a hand-written
handler vs. FastAPI's schema generator), and nothing guarantees they stay in
lockstep. If a future change hardcoded a literal in either path — or read one
from an env var and the other from the package — a client that trusts the
OpenAPI contract to advertise the running version would silently be lied to.

Existing coverage pins each surface *in isolation*:

* ``test_openapi_schema_metadata`` ties ``info.version`` to the ``__version__``
  **source constant** (a white-box check that imports the value); and
* ``test_integration.TestAPIContractVersion`` pins the ``/api/version`` response
  *shape* (a ``version`` key holding a non-empty string).

Neither compares the two **runtime responses** to each other, and none does so
across the sync/async ASGI transports. These tests close that gap by treating
the app strictly as a black box — no ``__version__`` import — so they assert the
contract a real client actually observes over HTTP.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from tests.conftest import get_openapi_schema


class TestRuntimeVersionConsistencyAcrossEndpoints:
    """The version a client discovers via ``/api/version`` matches the served OpenAPI schema."""

    def test_api_version_matches_served_openapi_info_version(self, client: TestClient) -> None:
        """``GET /api/version`` ``.version`` equals ``GET /openapi.json`` ``.info.version``.

        The core black-box guarantee: the version advertised by the running
        endpoint is byte-identical to the version documented in the served
        contract. A client may trust either surface and get the same answer.
        """
        endpoint_version = client.get("/api/version").json()["version"]
        schema_version = get_openapi_schema(client)["info"]["version"]

        assert endpoint_version == schema_version, (
            "Runtime version drifted from the served OpenAPI contract: "
            f"/api/version reported {endpoint_version!r} but /openapi.json "
            f"info.version reported {schema_version!r}. A client trusting the "
            "OpenAPI schema would advertise the wrong running version."
        )

    def test_version_consistency_is_stable_across_repeated_requests(
        self, client: TestClient
    ) -> None:
        """Both surfaces report a single, unchanging version across interleaved calls.

        Guards against a version value that is accidentally per-request (e.g.
        derived from a timestamp, PID or random seed): every ``/api/version``
        call and every ``/openapi.json`` call must yield the *same* string, so
        the consistency in the primary test is a stable property rather than a
        one-shot coincidence.
        """
        endpoint_versions = {client.get("/api/version").json()["version"] for _ in range(5)}
        schema_versions = {get_openapi_schema(client)["info"]["version"] for _ in range(5)}

        assert len(endpoint_versions) == 1, (
            f"/api/version reported differing versions across requests: {endpoint_versions!r}"
        )
        assert len(schema_versions) == 1, (
            f"/openapi.json info.version differed across requests: {schema_versions!r}"
        )
        assert endpoint_versions == schema_versions, (
            "The (single) /api/version value and the (single) OpenAPI info.version "
            f"disagree: {endpoint_versions!r} vs {schema_versions!r}."
        )

    @pytest.mark.asyncio
    async def test_api_version_matches_openapi_over_async_transport(
        self, async_client: AsyncClient
    ) -> None:
        """The cross-endpoint agreement also holds over the async ASGI transport.

        The two endpoints run through different call machinery under the async
        transport than under :class:`TestClient`. Pinning the agreement here
        ensures neither transport observes a divergence the other hides.
        """
        endpoint_version = (await async_client.get("/api/version")).json()["version"]
        schema_version = (await async_client.get("/openapi.json")).json()["info"]["version"]

        assert endpoint_version == schema_version, (
            "Over the async transport, /api/version reported "
            f"{endpoint_version!r} but /openapi.json info.version reported "
            f"{schema_version!r}."
        )

    @pytest.mark.asyncio
    async def test_version_agrees_across_both_endpoints_and_both_transports(
        self, client: TestClient, async_client: AsyncClient
    ) -> None:
        """All four (endpoint × transport) version reads collapse to one value.

        The strongest form of the invariant: ``/api/version`` and
        ``/openapi.json``, read over both the sync and async transports, must
        all agree. This pins that transport choice never leaks into the
        advertised version and that the two endpoints never diverge on either.
        """
        observed = {
            client.get("/api/version").json()["version"],
            get_openapi_schema(client)["info"]["version"],
            (await async_client.get("/api/version")).json()["version"],
            (await async_client.get("/openapi.json")).json()["info"]["version"],
        }

        assert len(observed) == 1, (
            "Version disagreement across endpoints/transports — expected a single "
            f"value but observed {observed!r}."
        )
