"""Exception hierarchy for qp-vault."""


class VaultError(Exception):
    """Base exception for all vault errors."""


class StorageError(VaultError):
    """Error in storage backend operations."""


class VerificationError(VaultError):
    """Content integrity verification failed."""


class LifecycleError(VaultError):
    """Invalid lifecycle state transition."""


class PolicyError(VaultError):
    """Policy evaluation denied the operation."""


class ChunkingError(VaultError):
    """Error during text chunking."""


class ParsingError(VaultError):
    """Error parsing a file format."""
