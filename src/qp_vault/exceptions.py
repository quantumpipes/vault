"""Exception hierarchy for qp-vault with structured error codes.

Each exception has a machine-readable code for operator tooling.
Codes follow the pattern VAULT_XXX where XXX is a 3-digit number.
"""


class VaultError(Exception):
    """Base exception for all vault errors. Code: VAULT_000."""

    code: str = "VAULT_000"


class StorageError(VaultError):
    """Error in storage backend operations. Code: VAULT_100."""

    code = "VAULT_100"


class VerificationError(VaultError):
    """Content integrity verification failed. Code: VAULT_200."""

    code = "VAULT_200"


class LifecycleError(VaultError):
    """Invalid lifecycle state transition. Code: VAULT_300."""

    code = "VAULT_300"


class PolicyError(VaultError):
    """Policy evaluation denied the operation. Code: VAULT_400."""

    code = "VAULT_400"


class ChunkingError(VaultError):
    """Error during text chunking. Code: VAULT_500."""

    code = "VAULT_500"


class ParsingError(VaultError):
    """Error parsing a file format. Code: VAULT_600."""

    code = "VAULT_600"


class PermissionError(VaultError):
    """RBAC permission denied. Code: VAULT_700."""

    code = "VAULT_700"
