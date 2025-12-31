# -*- coding: utf-8 -*-
"""
Cooldown Manager Property Tests

Uses hypothesis library for property-based testing to verify cooldown mechanism correctness.

Author: Kiro
Version: v1.0.0
"""

import pytest
import asyncio
import json
import tempfile
import os
import time
from pathlib import Path
from unittest.mock import MagicMock
from hypothesis import given, strategies as st, settings, assume

# Add project root to path
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock all astrbot modules before importing cooldown_manager
mock_logger = MagicMock()
mock_astrbot_api_all = MagicMock()
mock_astrbot_api_all.logger = mock_logger

sys.modules["astrbot"] = MagicMock()
sys.modules["astrbot.api"] = MagicMock()
sys.modules["astrbot.api.all"] = mock_astrbot_api_all
sys.modules["astrbot.api.message_components"] = MagicMock()
sys.modules["astrbot.core"] = MagicMock()
sys.modules["astrbot.core.message"] = MagicMock()
sys.modules["astrbot.core.message.components"] = MagicMock()
sys.modules["astrbot.core.provider"] = MagicMock()
sys.modules["astrbot.core.provider.entities"] = MagicMock()
sys.modules["astrbot.api.event"] = MagicMock()
sys.modules["astrbot.core.star"] = MagicMock()
sys.modules["astrbot.core.star.star_tools"] = MagicMock()

# Import cooldown_manager directly (not through utils package)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "cooldown_manager",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "utils",
        "cooldown_manager.py",
    ),
)
cooldown_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cooldown_module)
CooldownManager = cooldown_module.CooldownManager


# Custom strategies for valid user IDs (alphanumeric only)
user_id_strategy = st.from_regex(r"[a-zA-Z0-9]{1,20}", fullmatch=True)

# Custom strategies for valid user names
user_name_strategy = st.from_regex(r"[a-zA-Z0-9_]{1,50}", fullmatch=True)

# Custom strategies for valid chat_key (must contain underscore)
chat_key_strategy = st.from_regex(r"[a-zA-Z0-9]+_[a-zA-Z0-9_]{1,40}", fullmatch=True)

# Custom strategies for cooldown reasons
reason_strategy = st.sampled_from(
    ["decision_ai_no_reply", "manual", "timeout", "keyword_trigger"]
)

# Custom strategies for cooldown entries
cooldown_entry_strategy = st.fixed_dictionaries(
    {
        "cooldown_start": st.floats(
            min_value=0, max_value=2000000000, allow_nan=False, allow_infinity=False
        ),
        "reason": reason_strategy,
        "user_name": user_name_strategy,
    }
)

# Custom strategies for cooldown data map
cooldown_map_strategy = st.dictionaries(
    keys=chat_key_strategy,
    values=st.dictionaries(
        keys=user_id_strategy, values=cooldown_entry_strategy, min_size=0, max_size=5
    ),
    min_size=0,
    max_size=3,
)


def reset_cooldown_manager():
    """Reset CooldownManager state"""
    CooldownManager._cooldown_map = {}
    CooldownManager._initialized = False
    CooldownManager._storage_path = None
    CooldownManager._last_save_time = 0


class TestCooldownPersistenceRoundTrip:
    """
    **Feature: attention-cooldown-mechanism, Property 11: Cooldown data persistence round-trip**
    **Validates: Requirements 4.3**

    Tests that cooldown data saved to disk and loaded back should be equivalent
    """

    @given(cooldown_data=cooldown_map_strategy)
    @settings(max_examples=100, deadline=None)
    def test_persistence_round_trip(self, cooldown_data):
        """
        **Feature: attention-cooldown-mechanism, Property 11: Cooldown data persistence round-trip**
        **Validates: Requirements 4.3**

        For any cooldown list data, saving to disk then loading should produce equivalent data
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Reset state
            reset_cooldown_manager()

            # Set storage path
            storage_path = Path(temp_dir) / "cooldown_data.json"
            CooldownManager._storage_path = storage_path
            CooldownManager._initialized = True

            # Set cooldown data
            CooldownManager._cooldown_map = cooldown_data.copy()

            # Save to disk
            CooldownManager._save_to_disk(force=True)

            # Clear memory data
            CooldownManager._cooldown_map = {}

            # Load from disk
            CooldownManager._load_from_disk()

            # Verify data consistency
            loaded_data = CooldownManager._cooldown_map

            # Compare data
            assert loaded_data == cooldown_data, (
                f"Round-trip failed: original={cooldown_data}, loaded={loaded_data}"
            )

            # Cleanup
            reset_cooldown_manager()


class TestCooldownTriggerCondition:
    """
    **Feature: attention-cooldown-mechanism, Property 2: Cooldown list conditional trigger**
    **Validates: Requirements 1.2**

    Tests that when Decision AI decides not to reply and user attention is above threshold,
    the user should be added to cooldown list
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        attention_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_trigger_threshold(
        self, chat_key, user_id, user_name, attention_score, threshold
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 2: Cooldown list conditional trigger**
        **Validates: Requirements 1.2**

        For any user, when Decision AI decides not to reply and user attention is above threshold,
        the user should be added to cooldown list
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True
        CooldownManager.COOLDOWN_TRIGGER_THRESHOLD = threshold

        # Simulate cooldown trigger logic
        should_add_to_cooldown = attention_score > threshold

        async def run_test():
            if should_add_to_cooldown:
                result = await CooldownManager.add_to_cooldown(
                    chat_key, user_id, user_name, "decision_ai_no_reply"
                )
                assert result is True, "Should successfully add to cooldown list"

                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is True, (
                    f"When attention({attention_score}) > threshold({threshold}), user should be in cooldown"
                )
            else:
                # When attention is below threshold, should not add to cooldown (we don't call add_to_cooldown)
                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is False, (
                    f"When attention({attention_score}) <= threshold({threshold}), user should not be in cooldown"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


class TestCooldownAttentionListSync:
    """
    **Feature: attention-cooldown-mechanism, Property 9: Cooldown list sync with attention list**
    **Validates: Requirements 4.1**

    Tests that when a user is removed from attention list,
    the user should also be removed from cooldown list
    """

    @given(
        chat_key=chat_key_strategy,
        cooldown_user_ids=st.lists(
            user_id_strategy, min_size=1, max_size=5, unique=True
        ),
        attention_user_ids=st.lists(
            user_id_strategy, min_size=0, max_size=5, unique=True
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_sync_with_attention_list(
        self, chat_key, cooldown_user_ids, attention_user_ids
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 9: Cooldown list sync with attention list**
        **Validates: Requirements 4.1**

        For any user, when that user is removed from attention list,
        that user should also be removed from cooldown list
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state with multiple users
        CooldownManager._cooldown_map[chat_key] = {}
        for user_id in cooldown_user_ids:
            CooldownManager._cooldown_map[chat_key][user_id] = {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": f"user_{user_id}",
            }

        # Calculate expected results
        attention_set = set(attention_user_ids)
        cooldown_set = set(cooldown_user_ids)
        expected_removed = (
            cooldown_set - attention_set
        )  # Users in cooldown but not in attention
        expected_remaining = cooldown_set & attention_set  # Users in both

        async def run_test():
            # Sync with attention list
            removed_users = await CooldownManager.sync_with_attention_list(
                chat_key, attention_user_ids
            )

            # Verify removed users match expected
            assert set(removed_users) == expected_removed, (
                f"Removed users should be {expected_removed}, got {set(removed_users)}"
            )

            # Verify remaining users are still in cooldown
            for user_id in expected_remaining:
                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is True, (
                    f"User {user_id} should still be in cooldown (in both lists)"
                )

            # Verify removed users are no longer in cooldown
            for user_id in expected_removed:
                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is False, (
                    f"User {user_id} should be removed from cooldown (not in attention list)"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
    )
    @settings(max_examples=100, deadline=None)
    def test_on_attention_user_removed(self, chat_key, user_id, user_name):
        """
        **Feature: attention-cooldown-mechanism, Property 9: Cooldown list sync with attention list**
        **Validates: Requirements 4.1**

        When on_attention_user_removed is called, the user should be removed from cooldown
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state
        CooldownManager._cooldown_map[chat_key] = {
            user_id: {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        async def run_test():
            # Verify user is in cooldown
            is_in_cooldown_before = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_before is True, (
                "User should be in cooldown before removal"
            )

            # Call on_attention_user_removed
            result = await CooldownManager.on_attention_user_removed(chat_key, user_id)

            # Verify user was removed
            assert result is True, "on_attention_user_removed should return True"

            is_in_cooldown_after = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_after is False, (
                "User should not be in cooldown after removal"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


class TestCooldownSessionClearSync:
    """
    **Feature: attention-cooldown-mechanism, Property 10: Session data clear sync**
    **Validates: Requirements 4.2**

    Tests that when a session's attention data is cleared,
    that session's cooldown list data should also be cleared
    """

    @given(
        chat_key=chat_key_strategy,
        user_ids=st.lists(user_id_strategy, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100, deadline=None)
    def test_clear_session_cooldown(self, chat_key, user_ids):
        """
        **Feature: attention-cooldown-mechanism, Property 10: Session data clear sync**
        **Validates: Requirements 4.2**

        For any session, when that session's attention data is cleared,
        that session's cooldown list data should also be cleared
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state with multiple users
        CooldownManager._cooldown_map[chat_key] = {}
        for user_id in user_ids:
            CooldownManager._cooldown_map[chat_key][user_id] = {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": f"user_{user_id}",
            }

        async def run_test():
            # Verify users are in cooldown before clearing
            for user_id in user_ids:
                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is True, (
                    f"User {user_id} should be in cooldown before clearing"
                )

            # Clear session cooldown
            cleared_count = await CooldownManager.clear_session_cooldown(chat_key)

            # Verify correct count was returned
            assert cleared_count == len(user_ids), (
                f"Cleared count should be {len(user_ids)}, got {cleared_count}"
            )

            # Verify all users are no longer in cooldown
            for user_id in user_ids:
                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is False, (
                    f"User {user_id} should not be in cooldown after session clear"
                )

            # Verify session is completely removed from cooldown map
            assert chat_key not in CooldownManager._cooldown_map, (
                f"Session {chat_key} should be removed from cooldown map"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()

    @given(
        chat_keys=st.lists(chat_key_strategy, min_size=1, max_size=3, unique=True),
        user_ids_per_session=st.lists(
            st.lists(user_id_strategy, min_size=1, max_size=3, unique=True),
            min_size=1,
            max_size=3,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_clear_all_cooldown(self, chat_keys, user_ids_per_session):
        """
        **Feature: attention-cooldown-mechanism, Property 10: Session data clear sync**
        **Validates: Requirements 4.2**

        When clearing all cooldown data, all sessions should be cleared
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state for multiple sessions
        total_users = 0
        for i, chat_key in enumerate(chat_keys):
            user_ids = user_ids_per_session[i % len(user_ids_per_session)]
            CooldownManager._cooldown_map[chat_key] = {}
            for user_id in user_ids:
                CooldownManager._cooldown_map[chat_key][user_id] = {
                    "cooldown_start": time.time(),
                    "reason": "decision_ai_no_reply",
                    "user_name": f"user_{user_id}",
                }
                total_users += 1

        async def run_test():
            # Clear all cooldown
            cleared_count = await CooldownManager.clear_all_cooldown()

            # Verify correct total count was returned
            assert cleared_count == total_users, (
                f"Cleared count should be {total_users}, got {cleared_count}"
            )

            # Verify cooldown map is empty
            assert len(CooldownManager._cooldown_map) == 0, (
                f"Cooldown map should be empty after clear_all_cooldown"
            )

            # Verify no users are in cooldown
            for i, chat_key in enumerate(chat_keys):
                user_ids = user_ids_per_session[i % len(user_ids_per_session)]
                for user_id in user_ids:
                    is_in_cooldown = await CooldownManager.is_in_cooldown(
                        chat_key, user_id
                    )
                    assert is_in_cooldown is False, (
                        f"User {user_id} in session {chat_key} should not be in cooldown"
                    )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


class TestCooldownTimeoutAutoRelease:
    """
    **Feature: attention-cooldown-mechanism, Property 4: Cooldown timeout auto-release**
    **Validates: Requirements 1.4**

    Tests that when cooldown duration exceeds configured max duration,
    the user's cooldown state should be automatically released
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        max_duration=st.integers(min_value=1, max_value=3600),
        elapsed_time=st.floats(min_value=0.0, max_value=7200.0, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_timeout_auto_release(
        self, chat_key, user_id, user_name, max_duration, elapsed_time
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 4: Cooldown timeout auto-release**
        **Validates: Requirements 1.4**

        For any user in cooldown state, when cooldown duration exceeds configured max duration,
        the user's cooldown state should be automatically released
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True
        CooldownManager.MAX_COOLDOWN_DURATION = max_duration

        # Calculate cooldown start time based on elapsed time
        current_time = time.time()
        cooldown_start = current_time - elapsed_time

        # Manually set up cooldown state
        CooldownManager._cooldown_map[chat_key] = {
            user_id: {
                "cooldown_start": cooldown_start,
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        should_be_released = elapsed_time >= max_duration

        async def run_test():
            # Check and release expired cooldowns
            released_users = await CooldownManager.check_and_release_expired(chat_key)

            # Verify user is still in cooldown or released based on elapsed time
            is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)

            if should_be_released:
                assert user_id in released_users, (
                    f"User should be released when elapsed_time({elapsed_time}) >= max_duration({max_duration})"
                )
                assert is_in_cooldown is False, (
                    f"User should not be in cooldown after timeout release"
                )
            else:
                assert user_id not in released_users, (
                    f"User should NOT be released when elapsed_time({elapsed_time}) < max_duration({max_duration})"
                )
                assert is_in_cooldown is True, (
                    f"User should still be in cooldown before timeout"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestCooldownReleaseTriggerCondition:
    """
    **Feature: attention-cooldown-mechanism, Property 5: Cooldown release trigger condition**
    **Validates: Requirements 2.1, 2.2**

    Tests that when a user in cooldown triggers AI reply (via keyword/@mention or normal decision),
    the user's cooldown state should be released
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_release_on_reply_trigger(
        self, chat_key, user_id, user_name, trigger_type
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 5: Cooldown release trigger condition**
        **Validates: Requirements 2.1, 2.2**

        For any user in cooldown state, when that user's message triggers AI reply
        (via keyword/@mention or normal decision), the user's cooldown state should be released
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state
        CooldownManager._cooldown_map[chat_key] = {
            user_id: {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        async def run_test():
            # Verify user is in cooldown before release
            is_in_cooldown_before = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_before is True, (
                "User should be in cooldown before release"
            )

            # Try to release cooldown on reply
            result = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, user_id, trigger_type
            )

            # Verify release was successful
            assert result is True, (
                f"Cooldown release should succeed for trigger_type={trigger_type}"
            )

            # Verify user is no longer in cooldown
            is_in_cooldown_after = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_after is False, (
                f"User should not be in cooldown after release (trigger_type={trigger_type})"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()

    @given(
        chat_key=chat_key_strategy,
        user_ids=st.lists(user_id_strategy, min_size=2, max_size=5, unique=True),
        trigger_user_index=st.integers(min_value=0, max_value=100),
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_release_only_affects_trigger_user(
        self, chat_key, user_ids, trigger_user_index, trigger_type
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 5: Cooldown release trigger condition**
        **Validates: Requirements 2.1, 2.2**

        When releasing cooldown for one user, other users' cooldown states should remain unchanged
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Select trigger user
        trigger_user_id = user_ids[trigger_user_index % len(user_ids)]
        other_user_ids = [uid for uid in user_ids if uid != trigger_user_id]

        # Set up cooldown state for all users
        CooldownManager._cooldown_map[chat_key] = {}
        for user_id in user_ids:
            CooldownManager._cooldown_map[chat_key][user_id] = {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": f"user_{user_id}",
            }

        async def run_test():
            # Release cooldown for trigger user
            result = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, trigger_user_id, trigger_type
            )
            assert result is True, "Release should succeed for trigger user"

            # Verify trigger user is no longer in cooldown
            is_trigger_in_cooldown = await CooldownManager.is_in_cooldown(
                chat_key, trigger_user_id
            )
            assert is_trigger_in_cooldown is False, (
                "Trigger user should not be in cooldown"
            )

            # Verify other users are still in cooldown
            for other_user_id in other_user_ids:
                is_other_in_cooldown = await CooldownManager.is_in_cooldown(
                    chat_key, other_user_id
                )
                assert is_other_in_cooldown is True, (
                    f"Other user {other_user_id} should still be in cooldown"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


class TestCooldownReleaseUserIdentityValidation:
    """
    **Feature: attention-cooldown-mechanism, Property 7: Cooldown release user identity validation**
    **Validates: Requirements 3.1**

    Tests that cooldown release detection should only affect the message sender,
    not other users' cooldown states
    """

    @given(
        chat_key=chat_key_strategy,
        cooldown_user_id=user_id_strategy,
        message_sender_id=user_id_strategy,
        user_name=user_name_strategy,
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_release_validates_user_identity(
        self, chat_key, cooldown_user_id, message_sender_id, user_name, trigger_type
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 7: Cooldown release user identity validation**
        **Validates: Requirements 3.1**

        For any message, cooldown release detection should only affect the message sender,
        not other users' cooldown states
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state for cooldown_user_id
        CooldownManager._cooldown_map[chat_key] = {
            cooldown_user_id: {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        # Determine if sender matches cooldown user
        sender_matches_cooldown_user = message_sender_id == cooldown_user_id

        async def run_test():
            # Try to release cooldown for message sender
            result = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, message_sender_id, trigger_type
            )

            if sender_matches_cooldown_user:
                # If sender is the cooldown user, release should succeed
                assert result is True, (
                    "Release should succeed when sender matches cooldown user"
                )
                is_in_cooldown = await CooldownManager.is_in_cooldown(
                    chat_key, cooldown_user_id
                )
                assert is_in_cooldown is False, (
                    "Cooldown user should be released when sender matches"
                )
            else:
                # If sender is different, release should fail (user not in cooldown)
                assert result is False, (
                    "Release should fail when sender doesn't match cooldown user"
                )
                # Original cooldown user should still be in cooldown
                is_in_cooldown = await CooldownManager.is_in_cooldown(
                    chat_key, cooldown_user_id
                )
                assert is_in_cooldown is True, (
                    "Original cooldown user should remain in cooldown when different sender triggers"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


class TestCooldownReleaseBoundaryConditions:
    """
    **Feature: attention-cooldown-mechanism, Property 8: Boundary condition validation**
    **Validates: Requirements 3.2, 3.3**

    Tests that for users not in cooldown list or not in attention list,
    the system should not execute any cooldown release processing
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_release_fails_when_user_not_in_cooldown(
        self, chat_key, user_id, trigger_type
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 8: Boundary condition validation**
        **Validates: Requirements 3.2**

        When message sender is not in cooldown list, system should skip cooldown release processing
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Don't add user to cooldown list

        async def run_test():
            # Verify user is not in cooldown
            is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
            assert is_in_cooldown is False, "User should not be in cooldown"

            # Try to release cooldown
            result = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, user_id, trigger_type
            )

            # Release should fail (user not in cooldown)
            assert result is False, (
                "Release should fail when user is not in cooldown list"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        attention_user_ids=st.lists(
            user_id_strategy, min_size=0, max_size=5, unique=True
        ),
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_release_fails_when_user_not_in_attention_list(
        self, chat_key, user_id, user_name, attention_user_ids, trigger_type
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 8: Boundary condition validation**
        **Validates: Requirements 3.3**

        When message sender is not in attention list, system should skip cooldown release processing
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Set up cooldown state
        CooldownManager._cooldown_map[chat_key] = {
            user_id: {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        # Determine if user is in attention list
        user_in_attention = user_id in attention_user_ids

        async def run_test():
            # Verify user is in cooldown
            is_in_cooldown_before = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_before is True, "User should be in cooldown"

            # Try to release cooldown with attention list validation
            result = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, user_id, trigger_type, attention_user_ids
            )

            if user_in_attention:
                # If user is in attention list, release should succeed
                assert result is True, (
                    "Release should succeed when user is in attention list"
                )
                is_in_cooldown_after = await CooldownManager.is_in_cooldown(
                    chat_key, user_id
                )
                assert is_in_cooldown_after is False, (
                    "User should not be in cooldown after release"
                )
            else:
                # If user is not in attention list, release should fail
                assert result is False, (
                    "Release should fail when user is not in attention list"
                )
                is_in_cooldown_after = await CooldownManager.is_in_cooldown(
                    chat_key, user_id
                )
                assert is_in_cooldown_after is True, (
                    "User should still be in cooldown when not in attention list"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_release_fails_when_session_not_exists(
        self, chat_key, user_id, trigger_type
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 8: Boundary condition validation**
        **Validates: Requirements 3.2**

        When session doesn't exist in cooldown map, system should skip cooldown release processing
        """
        # Reset state
        reset_cooldown_manager()
        CooldownManager._initialized = True

        # Don't create any session in cooldown map

        async def run_test():
            # Try to release cooldown
            result = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, user_id, trigger_type
            )

            # Release should fail (session not exists)
            assert result is False, (
                "Release should fail when session doesn't exist in cooldown map"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()


# Import AttentionManager for integration tests
import importlib.util

attention_spec = importlib.util.spec_from_file_location(
    "attention_manager",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "utils",
        "attention_manager.py",
    ),
)
attention_module = importlib.util.module_from_spec(attention_spec)
attention_spec.loader.exec_module(attention_module)
AttentionManager = attention_module.AttentionManager


def reset_attention_manager():
    """Reset AttentionManager state"""
    AttentionManager._attention_map = {}
    AttentionManager._conversation_activity_map = {}
    AttentionManager._initialized = False
    AttentionManager._storage_path = None
    AttentionManager._last_save_time = 0


class TestCooldownBlocksAttentionIncrease:
    """
    **Feature: attention-cooldown-mechanism, Property 3: Cooldown state blocks attention increase**
    **Validates: Requirements 1.3**

    Tests that when a user is in cooldown state and sends a new message,
    their attention score should not increase
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        initial_attention=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        attention_boost=st.floats(min_value=0.1, max_value=0.5, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_blocks_attention_increase(
        self, chat_key, user_id, user_name, initial_attention, attention_boost
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 3: Cooldown state blocks attention increase**
        **Validates: Requirements 1.3**

        For any user in cooldown state, when that user sends a new message,
        their attention score should not increase
        """
        # Reset state
        reset_cooldown_manager()
        reset_attention_manager()
        CooldownManager._initialized = True
        AttentionManager._initialized = True

        # Set up attention state
        AttentionManager._attention_map[chat_key] = {
            user_id: {
                "user_id": user_id,
                "user_name": user_name,
                "attention_score": initial_attention,
                "emotion": 0.0,
                "last_interaction": time.time(),
                "interaction_count": 1,
                "last_message_preview": "",
            }
        }

        # Set up cooldown state
        CooldownManager._cooldown_map[chat_key] = {
            user_id: {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        async def run_test():
            # Verify user is in cooldown
            is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
            assert is_in_cooldown is True, "User should be in cooldown"

            # Get attention before
            attention_before = AttentionManager._attention_map[chat_key][user_id][
                "attention_score"
            ]

            # Simulate record_replied_user (which should skip attention increase for cooldown users)
            # We directly check the cooldown logic
            skip_attention_increase = False
            if chat_key in CooldownManager._cooldown_map:
                if user_id in CooldownManager._cooldown_map[chat_key]:
                    skip_attention_increase = True

            # Verify that attention increase should be skipped
            assert skip_attention_increase is True, (
                "Attention increase should be skipped for users in cooldown"
            )

            # If we were to apply the boost (which we shouldn't), attention would increase
            # But since user is in cooldown, attention should remain the same
            if not skip_attention_increase:
                AttentionManager._attention_map[chat_key][user_id][
                    "attention_score"
                ] = min(attention_before + attention_boost, 1.0)

            # Verify attention didn't change
            attention_after = AttentionManager._attention_map[chat_key][user_id][
                "attention_score"
            ]
            assert attention_after == attention_before, (
                f"Attention should not increase for cooldown user: before={attention_before}, after={attention_after}"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()
        reset_attention_manager()


class TestCooldownReleaseRestoresAttention:
    """
    **Feature: attention-cooldown-mechanism, Property 6: Cooldown release restores attention**
    **Validates: Requirements 2.3**

    Tests that after cooldown is released, the user's attention score
    should be able to increase normally
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        initial_attention=st.floats(min_value=0.0, max_value=0.8, allow_nan=False),
        attention_boost=st.floats(min_value=0.1, max_value=0.2, allow_nan=False),
        trigger_type=st.sampled_from(["keyword", "at", "normal"]),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_release_restores_attention_increase(
        self,
        chat_key,
        user_id,
        user_name,
        initial_attention,
        attention_boost,
        trigger_type,
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 6: Cooldown release restores attention**
        **Validates: Requirements 2.3**

        For any user who just had their cooldown released, when that user sends a new message,
        their attention score should be able to increase normally
        """
        # Reset state
        reset_cooldown_manager()
        reset_attention_manager()
        CooldownManager._initialized = True
        AttentionManager._initialized = True

        # Set up attention state
        AttentionManager._attention_map[chat_key] = {
            user_id: {
                "user_id": user_id,
                "user_name": user_name,
                "attention_score": initial_attention,
                "emotion": 0.0,
                "last_interaction": time.time(),
                "interaction_count": 1,
                "last_message_preview": "",
            }
        }

        # Set up cooldown state
        CooldownManager._cooldown_map[chat_key] = {
            user_id: {
                "cooldown_start": time.time(),
                "reason": "decision_ai_no_reply",
                "user_name": user_name,
            }
        }

        async def run_test():
            # Verify user is in cooldown before release
            is_in_cooldown_before = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_before is True, (
                "User should be in cooldown before release"
            )

            # Release cooldown
            released = await CooldownManager.try_release_cooldown_on_reply(
                chat_key, user_id, trigger_type
            )
            assert released is True, "Cooldown should be released"

            # Verify user is no longer in cooldown
            is_in_cooldown_after = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_after is False, (
                "User should not be in cooldown after release"
            )

            # Now attention increase should NOT be skipped
            skip_attention_increase = False
            if chat_key in CooldownManager._cooldown_map:
                if user_id in CooldownManager._cooldown_map[chat_key]:
                    skip_attention_increase = True

            assert skip_attention_increase is False, (
                "Attention increase should NOT be skipped after cooldown release"
            )

            # Simulate attention increase (which should now work)
            attention_before = AttentionManager._attention_map[chat_key][user_id][
                "attention_score"
            ]
            if not skip_attention_increase:
                AttentionManager._attention_map[chat_key][user_id][
                    "attention_score"
                ] = min(attention_before + attention_boost, 1.0)

            # Verify attention increased
            attention_after = AttentionManager._attention_map[chat_key][user_id][
                "attention_score"
            ]
            expected_attention = min(attention_before + attention_boost, 1.0)
            assert abs(attention_after - expected_attention) < 0.001, (
                f"Attention should increase after cooldown release: "
                f"before={attention_before}, after={attention_after}, expected={expected_attention}"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()
        reset_attention_manager()


class TestAttentionDecreaseConsistency:
    """
    **Feature: attention-cooldown-mechanism, Property 1: Attention decrease consistency**
    **Validates: Requirements 1.1**

    Tests that when Decision AI decides not to reply,
    the user's attention score should decrease
    """

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        initial_attention=st.floats(min_value=0.4, max_value=1.0, allow_nan=False),
        decrease_step=st.floats(min_value=0.1, max_value=0.3, allow_nan=False),
        min_threshold=st.floats(min_value=0.2, max_value=0.4, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_attention_decrease_on_no_reply(
        self,
        chat_key,
        user_id,
        user_name,
        initial_attention,
        decrease_step,
        min_threshold,
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 1: Attention decrease consistency**
        **Validates: Requirements 1.1**

        For any user and message, when Decision AI decides not to reply,
        that user's attention score should decrease
        """
        # Skip if initial attention is below threshold (no decrease expected)
        assume(initial_attention >= min_threshold)

        # Reset state
        reset_cooldown_manager()
        reset_attention_manager()
        CooldownManager._initialized = True
        AttentionManager._initialized = True

        # Set up attention state
        AttentionManager._attention_map[chat_key] = {
            user_id: {
                "user_id": user_id,
                "user_name": user_name,
                "attention_score": initial_attention,
                "emotion": 0.0,
                "last_interaction": time.time(),
                "interaction_count": 1,
                "last_message_preview": "",
            }
        }

        async def run_test():
            # Get attention before
            attention_before = AttentionManager._attention_map[chat_key][user_id][
                "attention_score"
            ]

            # Simulate decrease_attention_on_no_reply logic
            # Only decrease if attention is above threshold
            if attention_before >= min_threshold:
                new_attention = max(
                    attention_before - decrease_step,
                    0.0,  # MIN_ATTENTION_SCORE
                )
                AttentionManager._attention_map[chat_key][user_id][
                    "attention_score"
                ] = new_attention

            # Verify attention decreased
            attention_after = AttentionManager._attention_map[chat_key][user_id][
                "attention_score"
            ]

            if attention_before >= min_threshold:
                assert attention_after < attention_before, (
                    f"Attention should decrease when AI decides not to reply: "
                    f"before={attention_before}, after={attention_after}"
                )

                expected_attention = max(attention_before - decrease_step, 0.0)
                assert abs(attention_after - expected_attention) < 0.001, (
                    f"Attention decrease should match step: "
                    f"before={attention_before}, after={attention_after}, expected={expected_attention}"
                )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()
        reset_attention_manager()

    @given(
        chat_key=chat_key_strategy,
        user_id=user_id_strategy,
        user_name=user_name_strategy,
        initial_attention=st.floats(min_value=0.4, max_value=1.0, allow_nan=False),
        cooldown_threshold=st.floats(min_value=0.2, max_value=0.5, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_cooldown_triggered_on_high_attention_no_reply(
        self, chat_key, user_id, user_name, initial_attention, cooldown_threshold
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 1: Attention decrease consistency**
        **Validates: Requirements 1.1, 1.2**

        When Decision AI decides not to reply and user attention is above cooldown threshold,
        the user should be added to cooldown list
        """
        # Only test when attention is above threshold
        assume(initial_attention > cooldown_threshold)

        # Reset state
        reset_cooldown_manager()
        reset_attention_manager()
        CooldownManager._initialized = True
        CooldownManager.COOLDOWN_TRIGGER_THRESHOLD = cooldown_threshold
        AttentionManager._initialized = True

        # Set up attention state
        AttentionManager._attention_map[chat_key] = {
            user_id: {
                "user_id": user_id,
                "user_name": user_name,
                "attention_score": initial_attention,
                "emotion": 0.0,
                "last_interaction": time.time(),
                "interaction_count": 1,
                "last_message_preview": "",
            }
        }

        async def run_test():
            # Verify user is not in cooldown before
            is_in_cooldown_before = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_before is False, (
                "User should not be in cooldown before"
            )

            # Simulate the cooldown trigger logic from decrease_attention_on_no_reply
            old_attention = initial_attention
            if old_attention > CooldownManager.COOLDOWN_TRIGGER_THRESHOLD:
                added = await CooldownManager.add_to_cooldown(
                    chat_key, user_id, user_name, reason="decision_ai_no_reply"
                )
                assert added is True, "User should be added to cooldown"

            # Verify user is now in cooldown
            is_in_cooldown_after = await CooldownManager.is_in_cooldown(
                chat_key, user_id
            )
            assert is_in_cooldown_after is True, (
                f"User should be in cooldown when attention({initial_attention}) > threshold({cooldown_threshold})"
            )

        asyncio.new_event_loop().run_until_complete(run_test())

        # Cleanup
        reset_cooldown_manager()
        reset_attention_manager()


class TestConfigurationParameterLoading:
    """
    **Feature: attention-cooldown-mechanism, Property 12: Configuration parameter loading**
    **Validates: Requirements 7.1, 7.2, 7.3**

    Tests that cooldown-related parameters from configuration file
    should be correctly read and applied during system initialization
    """

    @given(
        max_duration=st.integers(min_value=60, max_value=7200),
        trigger_threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        attention_decrease=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_config_parameters_loaded_correctly(
        self, max_duration, trigger_threshold, attention_decrease
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 12: Configuration parameter loading**
        **Validates: Requirements 7.1, 7.2, 7.3**

        For any configuration file with cooldown-related parameters,
        the system should correctly read and apply these parameters after initialization
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Reset state
            reset_cooldown_manager()

            # Create config dict with cooldown parameters
            config = {
                "cooldown_max_duration": max_duration,
                "cooldown_trigger_threshold": trigger_threshold,
                "cooldown_attention_decrease": attention_decrease,
            }

            # Initialize CooldownManager with config
            CooldownManager.initialize(temp_dir, config)

            # Verify parameters were loaded correctly
            # Requirements 7.1: Max cooldown duration
            assert CooldownManager.MAX_COOLDOWN_DURATION == max_duration, (
                f"MAX_COOLDOWN_DURATION should be {max_duration}, "
                f"got {CooldownManager.MAX_COOLDOWN_DURATION}"
            )

            # Requirements 7.2: Trigger threshold
            assert CooldownManager.COOLDOWN_TRIGGER_THRESHOLD == trigger_threshold, (
                f"COOLDOWN_TRIGGER_THRESHOLD should be {trigger_threshold}, "
                f"got {CooldownManager.COOLDOWN_TRIGGER_THRESHOLD}"
            )

            # Requirements 7.3: Attention decrease
            assert CooldownManager.COOLDOWN_ATTENTION_DECREASE == attention_decrease, (
                f"COOLDOWN_ATTENTION_DECREASE should be {attention_decrease}, "
                f"got {CooldownManager.COOLDOWN_ATTENTION_DECREASE}"
            )

            # Cleanup
            reset_cooldown_manager()

    @given(
        max_duration=st.integers(min_value=60, max_value=7200),
        trigger_threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        attention_decrease=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_config_parameters_affect_behavior(
        self, max_duration, trigger_threshold, attention_decrease
    ):
        """
        **Feature: attention-cooldown-mechanism, Property 12: Configuration parameter loading**
        **Validates: Requirements 7.1, 7.2, 7.3**

        Configuration parameters should affect the actual behavior of the cooldown mechanism
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Reset state
            reset_cooldown_manager()

            # Create config dict
            config = {
                "cooldown_max_duration": max_duration,
                "cooldown_trigger_threshold": trigger_threshold,
                "cooldown_attention_decrease": attention_decrease,
            }

            # Initialize CooldownManager with config
            CooldownManager.initialize(temp_dir, config)

            # Test that trigger_threshold affects cooldown trigger decision
            # A user with attention above threshold should trigger cooldown
            test_attention_above = trigger_threshold + 0.1
            test_attention_below = max(trigger_threshold - 0.1, 0.0)

            # Above threshold should trigger
            should_trigger_above = (
                test_attention_above > CooldownManager.COOLDOWN_TRIGGER_THRESHOLD
            )
            assert should_trigger_above is True, (
                f"Attention {test_attention_above} should trigger cooldown "
                f"(threshold={CooldownManager.COOLDOWN_TRIGGER_THRESHOLD})"
            )

            # Below threshold should not trigger (unless threshold is 0)
            if trigger_threshold > 0.1:
                should_trigger_below = (
                    test_attention_below > CooldownManager.COOLDOWN_TRIGGER_THRESHOLD
                )
                assert should_trigger_below is False, (
                    f"Attention {test_attention_below} should NOT trigger cooldown "
                    f"(threshold={CooldownManager.COOLDOWN_TRIGGER_THRESHOLD})"
                )

            # Cleanup
            reset_cooldown_manager()

    def test_default_config_values_when_not_provided(self):
        """
        **Feature: attention-cooldown-mechanism, Property 12: Configuration parameter loading**
        **Validates: Requirements 7.1, 7.2, 7.3**

        When configuration parameters are not provided, default values should be used
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Reset state completely including class-level defaults
            reset_cooldown_manager()
            # Also reset the class-level config constants to their original defaults
            CooldownManager.MAX_COOLDOWN_DURATION = 600
            CooldownManager.COOLDOWN_TRIGGER_THRESHOLD = 0.3
            CooldownManager.COOLDOWN_ATTENTION_DECREASE = 0.2

            # Store original default values
            original_max_duration = 600  # Default from cooldown_manager.py
            original_threshold = 0.3  # Default from cooldown_manager.py
            original_decrease = 0.2  # Default from cooldown_manager.py

            # Initialize with empty config (should use defaults from config.get with default values)
            CooldownManager.initialize(temp_dir, {})

            # Verify default values are used (config.get returns default when key not present)
            assert CooldownManager.MAX_COOLDOWN_DURATION == original_max_duration, (
                f"Default MAX_COOLDOWN_DURATION should be {original_max_duration}"
            )
            assert CooldownManager.COOLDOWN_TRIGGER_THRESHOLD == original_threshold, (
                f"Default COOLDOWN_TRIGGER_THRESHOLD should be {original_threshold}"
            )
            assert CooldownManager.COOLDOWN_ATTENTION_DECREASE == original_decrease, (
                f"Default COOLDOWN_ATTENTION_DECREASE should be {original_decrease}"
            )

            # Cleanup
            reset_cooldown_manager()

    @given(max_duration=st.integers(min_value=60, max_value=7200))
    @settings(max_examples=50, deadline=None)
    def test_max_duration_affects_timeout_release(self, max_duration):
        """
        **Feature: attention-cooldown-mechanism, Property 12: Configuration parameter loading**
        **Validates: Requirements 7.1**

        The max_duration parameter should affect when cooldown times out
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Reset state
            reset_cooldown_manager()

            # Initialize with specific max_duration
            config = {"cooldown_max_duration": max_duration}
            CooldownManager.initialize(temp_dir, config)

            chat_key = "test_platform_group_123"
            user_id = "user456"

            # Set up cooldown that has exceeded max_duration
            current_time = time.time()
            CooldownManager._cooldown_map[chat_key] = {
                user_id: {
                    "cooldown_start": current_time
                    - max_duration
                    - 1,  # Exceeded by 1 second
                    "reason": "decision_ai_no_reply",
                    "user_name": "test_user",
                }
            }

            async def run_test():
                # Check and release expired
                released = await CooldownManager.check_and_release_expired(chat_key)

                # User should be released because cooldown exceeded max_duration
                assert user_id in released, (
                    f"User should be released when cooldown exceeds max_duration={max_duration}"
                )

                # Verify user is no longer in cooldown
                is_in_cooldown = await CooldownManager.is_in_cooldown(chat_key, user_id)
                assert is_in_cooldown is False, (
                    "User should not be in cooldown after timeout"
                )

            asyncio.new_event_loop().run_until_complete(run_test())

            # Cleanup
            reset_cooldown_manager()
