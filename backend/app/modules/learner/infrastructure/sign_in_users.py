"""The sign-in provider's user admin, used only to delete the learner's own account."""
from __future__ import annotations

from uuid import UUID


class SupabaseSignInUsers:
    def __init__(self, client):
        self.client = client

    def delete_user(self, user_id: UUID) -> None:
        self.client.auth.admin.delete_user(str(user_id))
