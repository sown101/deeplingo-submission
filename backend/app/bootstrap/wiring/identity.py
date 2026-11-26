from app.modules.identity.application.ports import TokenVerifier
from app.modules.identity.infrastructure.jwt_verifier import SupabaseJWTVerifier

jwt_verifier = SupabaseJWTVerifier()


def get_jwt_verifier() -> TokenVerifier:
    return jwt_verifier
