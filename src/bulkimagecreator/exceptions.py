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


class TransientGenerationError(GenerationError):
    """Raised for transient generation errors (HTTP 429, 503, timeouts) that may succeed upon retry."""

    pass


class NonTransientGenerationError(GenerationError):
    """Base exception for permanent generation errors that will not succeed upon retry."""

    pass


class SafetyBlockError(NonTransientGenerationError):
    """Raised when generation is blocked by safety ratings or content policy filters."""

    pass
