"""Tests for SHA3-256 hashing and Merkle tree operations."""

from qp_vault.core.hasher import (
    compute_cid,
    compute_hash,
    compute_merkle_proof,
    compute_merkle_root,
    compute_resource_hash,
    verify_merkle_proof,
)


class TestCID:
    def test_cid_format(self):
        cid = compute_cid("hello world")
        assert cid.startswith("vault://sha3-256/")
        assert len(cid) == len("vault://sha3-256/") + 64

    def test_deterministic(self):
        assert compute_cid("test") == compute_cid("test")

    def test_different_content_different_cid(self):
        assert compute_cid("hello") != compute_cid("world")

    def test_bytes_input(self):
        cid = compute_cid(b"binary data")
        assert cid.startswith("vault://sha3-256/")

    def test_empty_string(self):
        cid = compute_cid("")
        assert cid.startswith("vault://sha3-256/")


class TestHash:
    def test_hex_digest(self):
        h = compute_hash("hello")
        assert len(h) == 64  # SHA3-256 hex = 64 chars
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        assert compute_hash("test") == compute_hash("test")


class TestResourceHash:
    def test_sorted_cids(self):
        cids = ["vault://sha3-256/bbb", "vault://sha3-256/aaa", "vault://sha3-256/ccc"]
        h1 = compute_resource_hash(cids)
        h2 = compute_resource_hash(list(reversed(cids)))
        assert h1 == h2  # Order-independent

    def test_empty_cids(self):
        h = compute_resource_hash([])
        assert len(h) == 64

    def test_single_cid(self):
        h = compute_resource_hash(["vault://sha3-256/abc"])
        assert len(h) == 64


class TestMerkleRoot:
    def test_single_leaf(self):
        root = compute_merkle_root(["abc123"])
        assert root == "abc123"

    def test_two_leaves(self):
        root = compute_merkle_root(["aaa", "bbb"])
        expected = compute_hash("aaa" + "bbb")
        assert root == expected

    def test_empty_leaves(self):
        root = compute_merkle_root([])
        assert len(root) == 64

    def test_odd_number_duplicates_last(self):
        root3 = compute_merkle_root(["a", "b", "c"])
        # c is duplicated: hash(hash(a+b) + hash(c+c))
        left = compute_hash("a" + "b")
        right = compute_hash("c" + "c")
        expected = compute_hash(left + right)
        assert root3 == expected

    def test_deterministic(self):
        hashes = [compute_hash(str(i)) for i in range(100)]
        r1 = compute_merkle_root(hashes)
        r2 = compute_merkle_root(hashes)
        assert r1 == r2


class TestMerkleProof:
    def test_proof_verifies(self):
        hashes = [compute_hash(str(i)) for i in range(8)]
        root = compute_merkle_root(hashes)

        for i in range(8):
            proof = compute_merkle_proof(hashes, i)
            assert verify_merkle_proof(hashes[i], proof, root)

    def test_invalid_proof_fails(self):
        hashes = [compute_hash(str(i)) for i in range(4)]
        root = compute_merkle_root(hashes)
        proof = compute_merkle_proof(hashes, 0)

        # Tamper with leaf
        assert not verify_merkle_proof("tampered_hash", proof, root)

    def test_empty_hashes(self):
        proof = compute_merkle_proof([], 0)
        assert proof == []

    def test_out_of_bounds(self):
        proof = compute_merkle_proof(["a", "b"], 5)
        assert proof == []
