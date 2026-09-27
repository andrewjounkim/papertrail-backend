"""Typed exceptions that map cleanly onto HTTP status codes + JSON error bodies."""


class AppError(Exception):
    """Base class for errors that should become a clean JSON response."""

    status_code = 500

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class BadRequestError(AppError):
    """400 - the request itself was invalid (empty/unrecognized input, bad level, etc.)."""

    status_code = 400


class NotFoundError(AppError):
    """404 - well-formed request, but the paper/paper data doesn't exist."""

    status_code = 404


class UpstreamError(AppError):
    """502 - PubMed, iCite, or the LLM failed, timed out, or returned something we can't use."""

    status_code = 502
