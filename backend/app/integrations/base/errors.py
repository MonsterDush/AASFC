from __future__ import annotations


class POSIntegrationError(RuntimeError):
    """Base error for provider-neutral POS integration failures."""


class POSAuthenticationError(POSIntegrationError):
    """Raised when a provider rejects or cannot validate credentials."""


class POSCapabilityUnavailableError(POSIntegrationError):
    """Raised when the active connection cannot supply a requested entity."""


class POSProviderNotRegisteredError(POSIntegrationError):
    """Raised when no adapter factory is registered for a provider code."""


class POSProviderRegistrationError(POSIntegrationError):
    """Raised when a provider factory would overwrite an existing adapter."""
