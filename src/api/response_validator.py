"""Response validation utilities for graceful error handling.

This module provides utilities to validate AI agent responses and return
user-friendly fallback messages when the agent fails to generate a proper response.
"""

from src.audit_logging import get_logger

logger = get_logger(__name__)


class ResponseValidator:
    """Validates and sanitizes AI agent responses.

    Detects empty, null, or context-only responses and provides
    user-friendly fallback messages.
    """

    DEFAULT_FALLBACK = (
        "I apologize, but I was unable to process your request. "
        "Please try again or rephrase your question."
    )

    # Patterns that indicate raw context/history instead of actual response
    INVALID_PATTERNS = [
        "Previous conversation context",
        "[Current message]",
        "User:",
        "Assistant:",
        "System:",
        "[Context]",
        "[History]",
        "Chat history:",
        "Conversation history:",
    ]

    @classmethod
    def is_valid_response(cls, response: str | None) -> bool:
        """Check if response is a valid user-facing answer.

        Args:
            response: The AI agent response to validate

        Returns:
            True if the response is valid, False otherwise
        """
        # Check for empty or null response
        if not response or not response.strip():
            return False

        stripped_response = response.strip()

        # Check if response starts with invalid patterns (raw context/history)
        for pattern in cls.INVALID_PATTERNS:
            if stripped_response.startswith(pattern):
                return False

        return True

    @classmethod
    def get_fallback_response(
        cls,
        original_response: str | None,
        custom_message: str | None = None,
        reason: str = "invalid_response",
    ) -> str:
        """Return fallback message, logging original for debugging.

        Args:
            original_response: The original failed response
            custom_message: Optional custom fallback message
            reason: The reason for using fallback (for logging)

        Returns:
            The fallback message to return to the user
        """
        # Log the original response for debugging
        logger.warning(
            "Using fallback response",
            reason=reason,
            original_response_length=len(original_response) if original_response else 0,
            original_preview=original_response[:100] if original_response else None,
        )

        return custom_message or cls.DEFAULT_FALLBACK

    @classmethod
    def validate_and_get_response(
        cls,
        response: str | None,
        custom_fallback: str | None = None,
    ) -> tuple[str, bool, str | None]:
        """Validate response and return either the original or fallback.

        Args:
            response: The AI agent response to validate
            custom_fallback: Optional custom fallback message

        Returns:
            Tuple of (response_text, is_fallback, fallback_reason)
            - response_text: The validated response or fallback message
            - is_fallback: True if fallback was used
            - fallback_reason: The reason for fallback, or None if not a fallback
        """
        if response is not None and cls.is_valid_response(response):
            return response, False, None

        # Determine the reason for fallback
        if not response:
            reason = "empty_response"
        elif not response.strip():
            reason = "whitespace_only"
        else:
            reason = "invalid_format"

        fallback = cls.get_fallback_response(
            original_response=response,
            custom_message=custom_fallback,
            reason=reason,
        )

        return fallback, True, reason
