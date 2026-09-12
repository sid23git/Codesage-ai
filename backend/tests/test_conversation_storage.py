"""Tests for Conversation/Message models and ConversationService (M6 Phase 3)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.providers.base import LLMMessage
from app.models.conversation import Conversation, Message
from app.models.repository import Repository
from app.models.user import User
from app.schemas.rag import ChunkSearchResult
from app.services.conversation_service import ConversationService
from app.services.orchestration_service import AssistantAnswer
from app.services.repository_service import RepositoryService


async def _make_repo(db_session: AsyncSession, owner: User, name: str) -> Repository:
    repo = Repository(
        owner_id=owner.id,
        name=name,
        full_name=f"testuser/{name}",
        github_url=f"https://github.com/testuser/{name}",
        status="ready",
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    return repo


def _chunk(chunk_id: int, score: float = 0.8) -> ChunkSearchResult:
    return ChunkSearchResult(
        chunk_id=chunk_id,
        file_path="app/main.py",
        start_line=1,
        end_line=10,
        language="Python",
        chunk_type="function",
        name="main",
        chunk_text="def main():\n    pass",
        score=score,
        retrieval_sources=["semantic"],
    )


class TestConversationCreation:
    """Creating conversations and messages."""

    @pytest.mark.asyncio
    async def test_create_conversation_persists_row(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-a")

        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )

        assert conversation.id is not None
        assert conversation.user_id == test_user.id
        assert conversation.repository_id == repo.id
        assert conversation.messages == []
        assert conversation.created_at is not None
        assert conversation.updated_at is not None

    @pytest.mark.asyncio
    async def test_record_turn_persists_user_and_assistant_messages(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-b")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        answer = AssistantAnswer(
            status="answered",
            answer="It initializes the app.",
            evidence=[_chunk(1)],
            model="mock-llm",
            ingestion_id=42,
            input_tokens=10,
            output_tokens=5,
        )

        user_msg, assistant_msg = await ConversationService.record_turn(
            db_session,
            conversation,
            user_content="What does main() do?",
            answer=answer,
        )

        assert user_msg.role == "user"
        assert user_msg.content == "What does main() do?"
        assert assistant_msg.role == "assistant"
        assert assistant_msg.content == "It initializes the app."
        assert assistant_msg.model == "mock-llm"
        assert assistant_msg.input_tokens == 10
        assert assistant_msg.output_tokens == 5
        assert assistant_msg.evidence is not None
        assert len(assistant_msg.evidence) == 1
        assert assistant_msg.evidence[0]["chunk_id"] == 1
        assert assistant_msg.evidence[0]["file_path"] == "app/main.py"
        assert assistant_msg.evidence[0]["snippet"] == "def main():\n    pass"

    @pytest.mark.asyncio
    async def test_record_turn_with_no_evidence_stores_empty_list(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-c")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        answer = AssistantAnswer(
            status="insufficient_evidence",
            answer="Not enough evidence.",
            ingestion_id=1,
        )

        _, assistant_msg = await ConversationService.record_turn(
            db_session,
            conversation,
            user_content="something obscure",
            answer=answer,
        )

        assert assistant_msg.evidence == []

    @pytest.mark.asyncio
    async def test_evidence_snippet_is_bounded(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-snip")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        long_chunk = ChunkSearchResult(
            chunk_id=99,
            file_path="big.py",
            start_line=1,
            end_line=999,
            language="Python",
            chunk_type="function",
            name="huge",
            chunk_text="x" * 5000,
            score=0.9,
            retrieval_sources=["semantic"],
        )
        answer = AssistantAnswer(
            status="answered", answer="ok", evidence=[long_chunk], ingestion_id=1
        )

        _, assistant_msg = await ConversationService.record_turn(
            db_session, conversation, user_content="q", answer=answer
        )

        assert assistant_msg.evidence is not None
        assert len(assistant_msg.evidence[0]["snippet"]) <= 500


class TestConversationHistory:
    """Multi-turn history loading and chronological ordering."""

    @pytest.mark.asyncio
    async def test_build_history_returns_chronological_llm_messages(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-hist")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )

        for i in range(3):
            await ConversationService.record_turn(
                db_session,
                conversation,
                user_content=f"question {i}",
                answer=AssistantAnswer(
                    status="answered", answer=f"answer {i}", ingestion_id=1
                ),
            )
        await db_session.refresh(conversation)

        history = ConversationService.build_history(
            conversation, max_history_messages=8
        )

        assert [m.content for m in history] == [
            "question 0",
            "answer 0",
            "question 1",
            "answer 1",
            "question 2",
            "answer 2",
        ]
        assert all(isinstance(m, LLMMessage) for m in history)

    @pytest.mark.asyncio
    async def test_build_history_truncates_to_max_history_messages(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-trunc")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )

        for i in range(5):  # 5 turns = 10 messages
            await ConversationService.record_turn(
                db_session,
                conversation,
                user_content=f"q{i}",
                answer=AssistantAnswer(
                    status="answered", answer=f"a{i}", ingestion_id=1
                ),
            )
        await db_session.refresh(conversation)

        history = ConversationService.build_history(
            conversation, max_history_messages=4
        )

        assert len(history) == 4
        assert [m.content for m in history] == ["q3", "a3", "q4", "a4"]

    @pytest.mark.asyncio
    async def test_messages_returned_in_chronological_order(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-chrono")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        for i in range(3):
            await ConversationService.record_turn(
                db_session,
                conversation,
                user_content=f"q{i}",
                answer=AssistantAnswer(
                    status="answered", answer=f"a{i}", ingestion_id=1
                ),
            )
        await db_session.refresh(conversation)

        contents = [m.content for m in conversation.messages]
        assert contents == ["q0", "a0", "q1", "a1", "q2", "a2"]


class TestConversationOwnershipAndIsolation:
    """Ownership, repository scoping, and cross-user/repo isolation."""

    @pytest.mark.asyncio
    async def test_get_owned_conversation_returns_none_for_wrong_user(
        self, db_session: AsyncSession, test_user: User, other_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-own1")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )

        result = await ConversationService.get_owned_conversation(
            db_session, other_user.id, repo.id, conversation.id
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_owned_conversation_returns_none_for_wrong_repository(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo_a = await _make_repo(db_session, test_user, "repo-own-a")
        repo_b = await _make_repo(db_session, test_user, "repo-own-b")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo_a.id
        )

        result = await ConversationService.get_owned_conversation(
            db_session, test_user.id, repo_b.id, conversation.id
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_owned_conversation_returns_conversation_when_valid(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-own-valid")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )

        result = await ConversationService.get_owned_conversation(
            db_session, test_user.id, repo.id, conversation.id
        )
        assert result is not None
        assert result.id == conversation.id

    @pytest.mark.asyncio
    async def test_list_conversations_isolated_by_user(
        self, db_session: AsyncSession, test_user: User, other_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-list-iso")
        await ConversationService.create_conversation(db_session, test_user.id, repo.id)

        other_conversations = await ConversationService.list_conversations(
            db_session, other_user.id, repo.id
        )
        assert other_conversations == []

    @pytest.mark.asyncio
    async def test_list_conversations_ordered_most_recently_active_first(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-list-order")
        conv1 = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        conv2 = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        # Touch conv1 last, so it should now be most-recently-active.
        await ConversationService.record_turn(
            db_session,
            conv1,
            user_content="q",
            answer=AssistantAnswer(status="answered", answer="a", ingestion_id=1),
        )

        conversations = await ConversationService.list_conversations(
            db_session, test_user.id, repo.id
        )
        assert conversations[0].id == conv1.id
        assert conversations[1].id == conv2.id


class TestConversationDeletionCascade:
    """Deleting a repository or user must not orphan conversations/messages."""

    @pytest.mark.asyncio
    async def test_deleting_repository_cascades_to_conversations_and_messages(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        repo = await _make_repo(db_session, test_user, "repo-cascade")
        conversation = await ConversationService.create_conversation(
            db_session, test_user.id, repo.id
        )
        await ConversationService.record_turn(
            db_session,
            conversation,
            user_content="q",
            answer=AssistantAnswer(status="answered", answer="a", ingestion_id=1),
        )
        conversation_id = conversation.id
        repo_id = repo.id
        owner_id = test_user.id

        # Expire `repo` AND `conversation` so both levels of the nested
        # cascade path (repo -> conversation -> message) are re-queried
        # fresh -- SQLAlchemy does not repopulate an unloaded relationship
        # on an already identity-mapped object just because a later query
        # matches its primary key. Messages were added directly (not via
        # conversation.messages.append(...)), so conversation.messages is
        # still unloaded at this point too, and needs the same treatment
        # repo.conversations does. (expire_all() would also expire
        # unrelated fixture objects like test_user, so only these two
        # specific objects are targeted -- see test_rag_storage.py for
        # the single-level version of this same pattern.)
        db_session.expire(repo)
        db_session.expire(conversation)

        deleted = await RepositoryService.delete_repository(
            db_session, owner_id, repo_id
        )
        assert deleted is True
        await db_session.commit()

        result = await db_session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        assert result.scalars().first() is None

        result = await db_session.execute(
            select(Message).where(Message.conversation_id == conversation_id)
        )
        assert result.scalars().all() == []
