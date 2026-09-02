class RepositoryError(RuntimeError):
    """Domain-level repository failure for validation and storage errors."""


class RepositoryNotFoundError(RepositoryError, KeyError):
    """Raised when a requested record does not exist."""
