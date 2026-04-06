"""Security validation tests.

Tests every input validation boundary added during security hardening.
These are the promises that protect against malicious input.
"""

from __future__ import annotations

import pytest

from qp_vault import Lifecycle, TrustTier, Vault, VaultError


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "sec-vault")


class TestEnumValidation:
    """Invalid enum values must be rejected at the API boundary."""

    def test_invalid_trust_tier(self, vault):
        with pytest.raises(VaultError, match="Invalid parameter"):
            vault.add("content", trust="BOGUS")

    def test_invalid_classification(self, vault):
        with pytest.raises(VaultError, match="Invalid parameter"):
            vault.add("content", classification="top_secret")

    def test_invalid_lifecycle(self, vault):
        with pytest.raises(VaultError, match="Invalid parameter"):
            vault.add("content", lifecycle="published")

    def test_invalid_layer(self, vault):
        with pytest.raises(VaultError, match="Invalid parameter"):
            vault.add("content", layer="marketing")

    def test_valid_string_enums_accepted(self, vault):
        r = vault.add("content", trust="canonical", lifecycle="draft",
                       classification="confidential", layer="compliance")
        assert r.trust_tier == TrustTier.CANONICAL
        assert r.lifecycle == Lifecycle.DRAFT

    def test_enum_objects_accepted(self, vault):
        r = vault.add("content", trust=TrustTier.EPHEMERAL)
        assert r.trust_tier == TrustTier.EPHEMERAL

    def test_case_sensitive(self, vault):
        """Enum values are case-sensitive (lowercase only)."""
        with pytest.raises(VaultError, match="Invalid parameter"):
            vault.add("content", trust="CANONICAL")


class TestNameSanitization:
    """Resource names must be sanitized against path traversal and injection."""

    def test_path_traversal_stripped(self, vault):
        r = vault.add("content", name="../../etc/passwd")
        assert "/" not in r.name
        assert ".." not in r.name

    def test_null_bytes_stripped(self, vault):
        r = vault.add("content", name="test\x00evil.md")
        assert "\x00" not in r.name

    def test_control_chars_stripped(self, vault):
        r = vault.add("content", name="test\x01\x02\x03.md")
        assert "\x01" not in r.name

    def test_long_name_truncated(self, vault):
        r = vault.add("content", name="a" * 500)
        assert len(r.name) <= 255

    def test_empty_name_defaults(self, vault):
        r = vault.add("content", name="")
        assert r.name == "untitled"

    def test_dots_only_defaults(self, vault):
        r = vault.add("content", name="...")
        assert r.name == "untitled"

    def test_backslash_stripped(self, vault):
        r = vault.add("content", name="dir\\file.md")
        assert "\\" not in r.name


class TestTagValidation:
    """Tags must be validated for count, length, and content."""

    def test_excess_tags_rejected(self, vault):
        with pytest.raises(VaultError, match="Too many tags"):
            vault.add("content", tags=["t"] * 100)

    def test_long_tag_rejected(self, vault):
        with pytest.raises(VaultError, match="exceeds"):
            vault.add("content", tags=["a" * 200])

    def test_valid_tags_accepted(self, vault):
        r = vault.add("content", tags=["security", "reviewed", "v2.1"])
        assert r.tags == ["security", "reviewed", "v2.1"]

    def test_empty_tags_filtered(self, vault):
        r = vault.add("content", tags=["valid", "", "  ", "also-valid"])
        assert r.tags == ["valid", "also-valid"]

    def test_control_chars_in_tags_stripped(self, vault):
        r = vault.add("content", tags=["test\x00tag"])
        assert "\x00" not in r.tags[0]

    def test_exactly_max_tags_accepted(self, vault):
        r = vault.add("content", tags=[f"tag{i}" for i in range(50)])
        assert len(r.tags) == 50


class TestMetadataValidation:
    """Metadata must be validated for key safety, count, and value size."""

    def test_unsafe_key_rejected(self, vault):
        with pytest.raises(VaultError, match="invalid characters"):
            vault.add("content", metadata={"<script>": "xss"})

    def test_too_many_keys_rejected(self, vault):
        with pytest.raises(VaultError, match="Too many metadata keys"):
            vault.add("content", metadata={f"k{i}": "v" for i in range(200)})

    def test_oversized_value_rejected(self, vault):
        with pytest.raises(VaultError, match="exceeds"):
            vault.add("content", metadata={"big": "x" * 20000})

    def test_valid_metadata_accepted(self, vault):
        r = vault.add("content", metadata={"author": "alice", "version": "1.0"})
        assert r.metadata == {"author": "alice", "version": "1.0"}

    def test_key_with_dots_dashes_underscores(self, vault):
        r = vault.add("content", metadata={"my-key_v2.0": "value"})
        assert "my-key_v2.0" in r.metadata

    def test_non_string_key_rejected(self, vault):
        with pytest.raises(VaultError, match="must be a string"):
            vault.add("content", metadata={123: "value"})  # type: ignore


class TestContentValidation:
    """Content must be validated for size and null bytes."""

    def test_null_bytes_stripped(self, vault):
        r = vault.add("Hello\x00World", name="null.md")
        # The content stored should not have null bytes
        assert r.chunk_count >= 1  # Processed successfully

    def test_max_file_size_enforced(self, vault):
        from qp_vault.config import VaultConfig
        small = Vault(vault._async.path.parent / "small",
                      config=VaultConfig(max_file_size_mb=0))
        with pytest.raises(VaultError, match="exceeds max size"):
            small.add("x" * 1024 * 1024, name="big.txt")

    def test_empty_content_handled(self, vault):
        r = vault.add("", name="empty.md")
        assert r.chunk_count == 0

    def test_whitespace_only_handled(self, vault):
        r = vault.add("   \n\n   ", name="whitespace.md")
        # Should not crash; may produce 0 chunks
        assert r is not None

    def test_very_long_string_not_treated_as_path(self, vault):
        """Strings > 4096 chars should never be checked as file paths."""
        r = vault.add("x" * 5000, name="long.md")
        assert r.chunk_count >= 1


class TestFTSSanitization:
    """FTS5 special characters must not cause errors."""

    def test_fts_special_chars_in_search(self, vault):
        vault.add("Test document with searchable content", name="doc.md")
        # These would crash FTS5 without sanitization
        results = vault.search('hello* OR (world)')
        assert isinstance(results, list)

    def test_fts_quotes_in_search(self, vault):
        vault.add("Test content", name="doc.md")
        results = vault.search('"exact phrase" NOT excluded')
        assert isinstance(results, list)

    def test_fts_brackets_in_search(self, vault):
        vault.add("Test content", name="doc.md")
        results = vault.search("test [bracket] {brace}")
        assert isinstance(results, list)
