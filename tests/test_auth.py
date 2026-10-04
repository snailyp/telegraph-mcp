"""Admission control tests.

The constant-time comparison is the security-relevant behaviour here, and the
"never echo the credential" rule from CONTEXT.md applies to rejections too.
"""

from __future__ import annotations

import pytest

from telegraph_mcp.auth import StaticBearerVerifier


@pytest.fixture
def verifier() -> StaticBearerVerifier:
    return StaticBearerVerifier("correct-horse-battery-staple")


class TestAcceptance:
    async def test_the_configured_credential_is_accepted(self, verifier):
        assert await verifier.verify_token("correct-horse-battery-staple") is not None

    async def test_the_accepted_token_carries_a_client_id(self, verifier):
        token = await verifier.verify_token("correct-horse-battery-staple")
        assert token.client_id
        assert token.token == "correct-horse-battery-staple"


class TestRejection:
    async def test_a_wrong_credential_is_rejected(self, verifier):
        assert await verifier.verify_token("wrong") is None

    async def test_an_empty_credential_is_rejected(self, verifier):
        assert await verifier.verify_token("") is None

    async def test_a_near_miss_is_rejected(self, verifier):
        # One character short — the case a prefix-comparing check would accept.
        assert await verifier.verify_token("correct-horse-battery-stapl") is None

    async def test_a_longer_superset_is_rejected(self, verifier):
        assert (
            await verifier.verify_token("correct-horse-battery-staple-extra") is None
        )

    async def test_a_prefix_is_rejected(self, verifier):
        assert await verifier.verify_token("correct") is None

    async def test_case_difference_is_rejected(self, verifier):
        assert await verifier.verify_token("Correct-Horse-Battery-Staple") is None


class TestConstantTimeComparison:
    async def test_comparison_does_not_short_circuit_on_prefix(self, monkeypatch):
        """A timing-safe check must not compare the whole string with `==`.

        Asserted structurally rather than by timing, which is unreliable in CI:
        the module must route the comparison through `hmac.compare_digest`.
        """

        import hmac

        from telegraph_mcp import auth as auth_module

        calls: list[tuple] = []
        original = hmac.compare_digest

        def spy(a, b):
            calls.append((a, b))
            return original(a, b)

        monkeypatch.setattr(auth_module.hmac, "compare_digest", spy)
        await auth_module.StaticBearerVerifier("secret").verify_token("secret")
        assert calls, "verify_token must use hmac.compare_digest"


class TestNonAsciiTokens:
    async def test_non_ascii_credential_is_accepted(self):
        verifier = StaticBearerVerifier("clé-secrète-日本語")
        assert await verifier.verify_token("clé-secrète-日本語") is not None

    async def test_non_ascii_mismatch_is_rejected(self):
        verifier = StaticBearerVerifier("clé")
        assert await verifier.verify_token("cle") is None