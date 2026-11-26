from uuid import UUID


class SpeakingReviewRepository:
    def __init__(self, client):
        self.client = client.schema('v3')

    def context(self, session_id: UUID, user_id: UUID, concept_id: UUID) -> dict | None:
        data = self.client.rpc('speaking_review_context', self._identity(session_id, user_id, concept_id)).execute().data
        if data is not None and not isinstance(data, dict):
            raise RuntimeError('Invalid speaking review context')
        return data

    def commit(self, session_id: UUID, user_id: UUID, concept_id: UUID, transition: dict | None) -> str:
        return self.client.rpc('commit_speaking_review', {
            **self._identity(session_id, user_id, concept_id), 'p_transition': transition,
        }).execute().data

    @staticmethod
    def _identity(session_id, user_id, concept_id):
        return {'p_session_id': str(session_id), 'p_user_id': str(user_id), 'p_concept_id': str(concept_id)}
