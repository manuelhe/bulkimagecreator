"""Exceptions for Bulk Image Creator."""


class BulkImageCreatorError(Exception):
    """Base exception for Bulk Image Creator errors."""

    pass


class ValidationError(BulkImageCreatorError, ValueError):
    """Raised when user arguments or source image files fail validation."""

    pass


class StorageError(BulkImageCreatorError):
    """Raised when file storage or directory operations fail."""

    pass


class ManifestError(BulkImageCreatorError):
    """Raised when reading, parsing, or writing the run manifest fails."""

    pass


class GenerationError(BulkImageCreatorError):
    """Raised when multimodal image generation fails or returns invalid output."""

    pass
