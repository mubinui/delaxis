"""Agent behavior configuration and output validation."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class OutputFormatType(StrEnum):
    """Type of output format."""

    JSON = "json"
    TEXT = "text"
    CODE = "code"
    MARKDOWN = "markdown"


class OutputFormatConfig(BaseModel):
    """Configuration for agent output format."""

    type: OutputFormatType = Field(description="Type of output format expected from the agent")
    language: str | None = Field(
        default=None,
        description="Programming language for code output (e.g., 'python', 'javascript')",
    )
    include_explanation: bool = Field(
        default=False, description="Whether to include explanation with the output"
    )
    format_template: str | None = Field(
        default=None,
        description="Template for formatting output (supports {language}, {code}, {explanation} placeholders)",
    )
    json_schema: dict[str, Any] | None = Field(
        default=None, description="JSON schema for validating JSON output"
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str | None, info) -> str | None:
        """Validate language is provided for code output."""
        output_type = info.data.get("type")
        if output_type == OutputFormatType.CODE and v is None:
            # Allow auto_detect as a special value
            return "auto_detect"
        return v


class ConstraintsConfig(BaseModel):
    """Configuration for agent output constraints."""

    max_output_length: int | None = Field(
        default=None, ge=1, description="Maximum length of output in characters"
    )
    min_output_length: int | None = Field(
        default=None, ge=0, description="Minimum length of output in characters"
    )
    require_language_specification: bool = Field(
        default=False, description="Whether to require language specification in code blocks"
    )
    forbidden_patterns: list[str] = Field(
        default_factory=list, description="List of regex patterns that are forbidden in output"
    )
    required_patterns: list[str] = Field(
        default_factory=list, description="List of regex patterns that must be present in output"
    )
    allowed_languages: list[str] | None = Field(
        default=None, description="List of allowed programming languages for code output"
    )


class SecurityConfig(BaseModel):
    """Configuration for security checks on agent output."""

    syntax_check: bool = Field(
        default=False, description="Whether to perform syntax checking on code output"
    )
    security_scan: bool = Field(
        default=False, description="Whether to scan for security vulnerabilities in code"
    )
    dangerous_functions: list[str] = Field(
        default_factory=lambda: ["eval", "exec", "compile", "__import__"],
        description="List of dangerous function names to check for",
    )
    allow_file_operations: bool = Field(
        default=False, description="Whether to allow file operations in code"
    )
    allow_network_operations: bool = Field(
        default=False, description="Whether to allow network operations in code"
    )


class AgentBehaviorConfig(BaseModel):
    """Complete behavior configuration for an agent."""

    output_format: OutputFormatConfig | None = Field(
        default=None, description="Output format configuration"
    )
    constraints: ConstraintsConfig | None = Field(
        default=None, description="Output constraints configuration"
    )
    validation: SecurityConfig | None = Field(
        default=None, description="Security and validation configuration"
    )

    # ==========================================================================
    # RELIABILITY SETTINGS (CrewAI 0.4 best practices)
    # ==========================================================================

    reflect_on_tool_use: bool = Field(
        default=True,
        description="Whether agent should synthesize tool results into natural language. "
        "When True, the agent will transform raw tool output into user-friendly responses.",
    )
    max_validation_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum number of retries when response validation fails. "
        "Agent will receive feedback and retry on validation failure.",
    )
    validate_response_quality: bool = Field(
        default=True,
        description="Whether to validate response quality (detect raw JSON, errors, etc.)",
    )
    min_response_length: int = Field(
        default=10, ge=0, description="Minimum acceptable response length in characters"
    )

    # Raw output detection patterns (configurable)
    raw_output_patterns: list[str] = Field(
        default_factory=lambda: [
            r'["\']?status_code["\']?\s*:',
            r'["\']?success["\']?\s*:\s*(true|false|True|False)',
            r'^{[^}]*["\']data["\']:\s*[\[\{]',
        ],
        description="Regex patterns to detect raw tool output that should be transformed",
    )

    # Error patterns that indicate response failure
    error_patterns: list[str] = Field(
        default_factory=lambda: [
            r"I don'?t have access",
            r"I cannot (access|retrieve|find)",
            r"^Error:",
            r"Exception:",
            r"(Key|Type|Attribute|Value|Runtime)Error:",
        ],
        description="Regex patterns to detect error responses that may need retry",
    )

    def has_validation(self) -> bool:
        """Check if any validation is configured."""
        return (
            self.output_format is not None
            or self.constraints is not None
            or self.validation is not None
            or self.validate_response_quality
        )
