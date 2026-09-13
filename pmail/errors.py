"""Exception types shared across the package."""


class PmailError(Exception):
    """Base class for every error this tool raises deliberately."""


class ConfigError(PmailError):
    """Configuration is missing or contradictory."""


class ResolutionError(PmailError):
    """A recipient mentioned in a transcript could not be resolved."""


class SendBlocked(PmailError):
    """A send was refused by a safety guard rather than by the mail server."""


class SendFailed(PmailError):
    """The mail server (or API) rejected the message."""
