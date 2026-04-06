"""SHA3-256 content hashing and Merkle tree operations.

All content-addressing in qp-vault uses SHA3-256 (FIPS 202).
CID format: vault://sha3-256/{hex_digest}
"""

from __future__ import annotations

import hashlib


def compute_cid(content: str | bytes) -> str:
    """Compute a content ID (CID) using SHA3-256.

    Args:
        content: Text or bytes to hash.

    Returns:
        CID in format: vault://sha3-256/{hex_digest}
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    digest = hashlib.sha3_256(content).hexdigest()
    return f"vault://sha3-256/{digest}"


def compute_hash(content: str | bytes) -> str:
    """Compute raw SHA3-256 hex digest.

    Args:
        content: Text or bytes to hash.

    Returns:
        Hex-encoded SHA3-256 digest.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha3_256(content).hexdigest()


def compute_resource_hash(chunk_cids: list[str]) -> str:
    """Compute resource hash from sorted chunk CIDs.

    Args:
        chunk_cids: List of chunk CIDs.

    Returns:
        SHA3-256 hash over sorted, concatenated chunk CIDs.
    """
    sorted_cids = sorted(chunk_cids)
    combined = "".join(sorted_cids)
    return compute_hash(combined)


def compute_merkle_root(hashes: list[str]) -> str:
    """Compute Merkle root from a list of leaf hashes.

    Uses SHA3-256 for internal nodes. If the number of leaves
    is odd, the last leaf is duplicated.

    Args:
        hashes: List of hex-encoded leaf hashes.

    Returns:
        Hex-encoded Merkle root hash.
    """
    if not hashes:
        return compute_hash("")

    if len(hashes) == 1:
        return hashes[0]

    # Build tree bottom-up
    current_level = list(hashes)

    while len(current_level) > 1:
        next_level: list[str] = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            combined = left + right
            next_level.append(compute_hash(combined))
        current_level = next_level

    return current_level[0]


def compute_merkle_proof(hashes: list[str], leaf_index: int) -> list[dict[str, str]]:
    """Compute Merkle proof path for a specific leaf.

    Args:
        hashes: List of all leaf hashes.
        leaf_index: Index of the leaf to prove.

    Returns:
        List of proof nodes, each with 'hash' and 'position' ('left' or 'right').
    """
    if not hashes or leaf_index >= len(hashes):
        return []

    proof: list[dict[str, str]] = []
    current_level = list(hashes)

    idx = leaf_index
    while len(current_level) > 1:
        next_level: list[str] = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            combined = left + right
            next_level.append(compute_hash(combined))

            # If our index is in this pair, record the sibling
            if i == idx or i + 1 == idx:
                if i == idx:
                    sibling = right
                    position = "right"
                else:
                    sibling = left
                    position = "left"
                proof.append({"hash": sibling, "position": position})

        idx = idx // 2
        current_level = next_level

    return proof


def verify_merkle_proof(
    leaf_hash: str,
    proof: list[dict[str, str]],
    expected_root: str,
) -> bool:
    """Verify a Merkle proof against an expected root.

    Args:
        leaf_hash: The hash of the leaf being verified.
        proof: Proof path from compute_merkle_proof.
        expected_root: The expected Merkle root.

    Returns:
        True if the proof is valid.
    """
    current = leaf_hash

    for node in proof:
        combined = node["hash"] + current if node["position"] == "left" else current + node["hash"]
        current = compute_hash(combined)

    return current == expected_root
