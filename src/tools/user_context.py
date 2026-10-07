"""Tool to get current logged-in user information from JWT token."""

from typing import Any

import structlog

from src.tools.context_utils import get_user_context_info

logger = structlog.get_logger(__name__)


def get_current_user_info() -> dict[str, Any]:
    """
    Get the current logged-in user's information from the JWT token.

    Returns the student ID (from preferred_username), name, email, and other user details.
    This tool extracts information from the authenticated user's JWT token,
    so students don't need to provide their information manually.

    Returns:
        Dict containing:
            - student_id: The student ID (from JWT preferred_username)
            - username: The username (same as student_id)
            - name: Full name (from JWT name field, or student_id if null)
            - email: Email address (from JWT email field)
            - roles: List of user roles
            - has_auth: Whether user is authenticated
    """
    # Get basic user info (username, roles)
    user_info = get_user_context_info()

    # The username in the JWT is the preferred_username which contains the student ID
    student_id = user_info.get("username")
    raw_token = user_info.get("raw_token")

    # Initialize with defaults
    name: str | None = None
    email: str | None = None

    # Extract name and email from JWT
    try:
        if raw_token:
            import jwt as pyjwt

            unverified_payload = pyjwt.decode(raw_token, options={"verify_signature": False})

            # Get name and email from JWT payload
            name = unverified_payload.get("name")
            email = unverified_payload.get("email")

            logger.info(
                "jwt_fields_extracted",
                student_id=student_id,
                name_from_jwt=name,
                email_from_jwt=email,
                has_name=bool(name),
                has_email=bool(email),
            )
    except Exception as e:
        logger.error(
            "jwt_extraction_failed",
            error=str(e),
            error_type=type(e).__name__,
            student_id=student_id,
        )

    # Fallback: Use student_id as name if JWT name field is null/empty
    if not name:
        name = student_id
        logger.info("using_student_id_as_name_fallback", student_id=student_id)

    result = {
        "student_id": student_id,
        "username": student_id,  # Same as student_id
        "name": name,
        "email": email,
        "roles": user_info.get("roles", []),
        "has_auth": bool(student_id),
    }

    logger.info(
        "get_current_user_info_result",
        student_id=student_id,
        name=result["name"],
        email=result["email"],
        has_auth=result["has_auth"],
        roles_count=len(result["roles"]),
    )

    return result
