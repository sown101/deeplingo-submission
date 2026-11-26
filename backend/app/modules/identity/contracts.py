"""Public surface of the identity module.

API layers of other modules may additionally import
``app.modules.identity.api.dependencies`` for FastAPI authentication dependencies.
"""
from app.modules.identity.domain.errors import AuthenticationError
from app.modules.identity.domain.principal import CurrentUser
