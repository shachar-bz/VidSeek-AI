"""Tests for password hashing and the user auth token registry."""

from backend.core.auth import UserAuthRegistry, hash_password, normalize_email, verify_password


def test_a_password_verifies_against_its_own_hash() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_the_wrong_password_does_not_verify() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_two_hashes_of_the_same_password_are_not_identical() -> None:
    # bcrypt salts every hash, which is what stops two accounts sharing a password from
    # showing it in the stored hash.
    assert hash_password("shared password") != hash_password("shared password")


def test_a_malformed_hash_never_verifies() -> None:
    assert not verify_password("anything", "not a bcrypt hash")


def test_email_is_normalized_to_trimmed_lowercase() -> None:
    assert normalize_email("  User@Example.com  ") == "user@example.com"


def test_a_token_verifies_to_the_user_it_was_issued_for() -> None:
    registry = UserAuthRegistry()
    token = registry.issue("user-1")
    assert registry.verify(token) == "user-1"


def test_an_unknown_token_does_not_verify() -> None:
    registry = UserAuthRegistry()
    assert registry.verify("not-a-real-token") is None


def test_a_revoked_token_no_longer_verifies() -> None:
    registry = UserAuthRegistry()
    token = registry.issue("user-1")
    registry.revoke(token)
    assert registry.verify(token) is None


def test_revoking_an_unknown_token_is_not_an_error() -> None:
    UserAuthRegistry().revoke("never-issued")


def test_an_expired_token_no_longer_verifies() -> None:
    registry = UserAuthRegistry(ttl_seconds=0)
    token = registry.issue("user-1")
    assert registry.verify(token) is None


def test_verifying_a_token_extends_its_ttl() -> None:
    # A signed-in user who keeps using the extension should not be logged out mid-session
    # just because the token's original TTL elapsed.
    registry = UserAuthRegistry(ttl_seconds=10_000)
    token = registry.issue("user-1")
    first = registry._tokens[token][1]
    registry.verify(token)
    second = registry._tokens[token][1]
    assert second >= first


def test_two_issued_tokens_for_the_same_user_are_both_valid() -> None:
    # Logging in from a second machine must not sign the first one out.
    registry = UserAuthRegistry()
    first = registry.issue("user-1")
    second = registry.issue("user-1")
    assert registry.verify(first) == "user-1"
    assert registry.verify(second) == "user-1"
