"""Domain errors raised by the summarizer pipeline."""


class SummarizerError(Exception):
    """Base class for all summarizer-pipeline errors."""


class InvalidDocumentError(SummarizerError):
    """The uploaded bytes are not valid UTF-8 text, or are empty."""


class ModelInvocationError(SummarizerError):
    """Bedrock InvokeModel failed after retries."""
