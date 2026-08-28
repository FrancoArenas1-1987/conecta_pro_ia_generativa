class ConectaVideoError(Exception):
    """Base class for project-specific exceptions."""


class ConfigurationError(ConectaVideoError):
    """Raised when configuration is invalid or incomplete."""


class PreflightError(ConectaVideoError):
    """Raised when the runtime environment is not ready."""


class GenerationError(ConectaVideoError):
    """Raised when script generation fails."""


class RenderError(ConectaVideoError):
    """Raised when rendering fails."""
