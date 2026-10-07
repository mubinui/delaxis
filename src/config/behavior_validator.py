"""Output validation for agent responses."""

import ast
import json
import re
from typing import Any

from src.audit_logging import get_logger
from src.config.behavior_models import (
    AgentBehaviorConfig,
    ConstraintsConfig,
    OutputFormatConfig,
    OutputFormatType,
    SecurityConfig,
)

logger = get_logger(__name__)


class ValidationError(Exception):
    """Exception raised when validation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class ValidationResult:
    """Result of validation."""

    def __init__(
        self, valid: bool, errors: list[str] | None = None, warnings: list[str] | None = None
    ):
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []

    def add_error(self, error: str) -> None:
        """Add an error to the result."""
        self.errors.append(error)
        self.valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        self.warnings.append(warning)

    def __bool__(self) -> bool:
        """Return True if validation passed."""
        return self.valid

    def __str__(self) -> str:
        """String representation of validation result."""
        if self.valid:
            msg = "Validation passed"
            if self.warnings:
                msg += f" with {len(self.warnings)} warning(s)"
            return msg
        return f"Validation failed with {len(self.errors)} error(s)"


class AgentBehaviorValidator:
    """
    Validator for agent output based on behavior configuration.

    This validator can be used to validate agent outputs against configured
    behavior constraints including output format, length constraints, forbidden
    patterns, and security checks.
    """

    def __init__(self, behavior_config: AgentBehaviorConfig):
        """
        Initialize the validator with behavior configuration.

        Args:
            behavior_config: Agent behavior configuration
        """
        self.behavior_config = behavior_config

    def validate(self, output: str) -> ValidationResult:
        """
        Validate agent output against all configured rules.

        Args:
            output: Agent output to validate

        Returns:
            ValidationResult with validation status and any errors/warnings
        """
        result = ValidationResult(valid=True)

        # Validate output format
        if self.behavior_config.output_format:
            format_result = self.validate_output_format(output, self.behavior_config.output_format)
            if not format_result:
                result.valid = False
                result.errors.extend(format_result.errors)
            result.warnings.extend(format_result.warnings)

        # Validate constraints
        if self.behavior_config.constraints:
            constraints_result = self.validate_constraints(output, self.behavior_config.constraints)
            if not constraints_result:
                result.valid = False
                result.errors.extend(constraints_result.errors)
            result.warnings.extend(constraints_result.warnings)

        # Validate security
        if self.behavior_config.validation:
            security_result = self.apply_security_checks(output, self.behavior_config.validation)
            if not security_result:
                result.valid = False
                result.errors.extend(security_result.errors)
            result.warnings.extend(security_result.warnings)

        return result

    def validate_output_format(
        self, output: str, format_config: OutputFormatConfig
    ) -> ValidationResult:
        """
        Validate output format.

        Args:
            output: Agent output to validate
            format_config: Output format configuration

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)

        if format_config.type == OutputFormatType.JSON:
            # Validate JSON format
            try:
                parsed = json.loads(output)

                # Validate against schema if provided
                if format_config.json_schema:
                    schema_result = self._validate_json_schema(parsed, format_config.json_schema)
                    if not schema_result:
                        result.valid = False
                        result.errors.extend(schema_result.errors)
            except json.JSONDecodeError as e:
                result.add_error(f"Invalid JSON format: {str(e)}")

        elif format_config.type == OutputFormatType.CODE:
            # Validate code format
            code_blocks = self._extract_code_blocks(output)

            if not code_blocks:
                result.add_error("No code blocks found in output")
            else:
                # Check language specification if required
                if format_config.language and format_config.language != "auto_detect":
                    for block in code_blocks:
                        if block.get("language") != format_config.language:
                            result.add_warning(
                                f"Code block language '{block.get('language')}' "
                                f"does not match expected '{format_config.language}'"
                            )

        elif format_config.type == OutputFormatType.MARKDOWN:
            # Basic markdown validation
            if not output.strip():
                result.add_error("Empty markdown output")

        return result

    def validate_constraints(self, output: str, constraints: ConstraintsConfig) -> ValidationResult:
        """
        Validate output constraints.

        Args:
            output: Agent output to validate
            constraints: Constraints configuration

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)

        # Check length constraints
        output_length = len(output)

        if constraints.max_output_length and output_length > constraints.max_output_length:
            result.add_error(
                f"Output length {output_length} exceeds maximum {constraints.max_output_length}"
            )

        if constraints.min_output_length and output_length < constraints.min_output_length:
            result.add_error(
                f"Output length {output_length} is below minimum {constraints.min_output_length}"
            )

        # Check forbidden patterns
        for pattern in constraints.forbidden_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                result.add_error(f"Output contains forbidden pattern: {pattern}")

        # Check required patterns
        for pattern in constraints.required_patterns:
            if not re.search(pattern, output, re.IGNORECASE):
                result.add_error(f"Output missing required pattern: {pattern}")

        # Check language specification for code
        if constraints.require_language_specification:
            code_blocks = self._extract_code_blocks(output)
            for i, block in enumerate(code_blocks):
                if not block.get("language"):
                    result.add_error(f"Code block {i + 1} missing language specification")

        # Check allowed languages
        if constraints.allowed_languages:
            code_blocks = self._extract_code_blocks(output)
            for i, block in enumerate(code_blocks):
                lang = block.get("language", "").lower()
                if lang and lang not in [
                    allowed.lower() for allowed in constraints.allowed_languages
                ]:
                    result.add_error(f"Code block {i + 1} uses disallowed language: {lang}")

        return result

    def apply_security_checks(
        self, output: str, security_config: SecurityConfig
    ) -> ValidationResult:
        """
        Apply security checks to output.

        Args:
            output: Agent output to validate
            security_config: Security configuration

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)

        # Extract code blocks for security scanning
        code_blocks = self._extract_code_blocks(output)

        for i, block in enumerate(code_blocks):
            code = block.get("code", "")
            language = block.get("language", "").lower()

            # Syntax check for Python code
            if security_config.syntax_check and language == "python":
                syntax_result = self._check_python_syntax(code)
                if not syntax_result:
                    result.add_error(
                        f"Code block {i + 1} has syntax errors: {'; '.join(syntax_result.errors)}"
                    )

            # Check for dangerous functions
            if security_config.security_scan:
                for func in security_config.dangerous_functions:
                    # Check for function calls
                    pattern = rf"\b{re.escape(func)}\s*\("
                    if re.search(pattern, code):
                        result.add_error(f"Code block {i + 1} contains dangerous function: {func}")

            # Check file operations
            if not security_config.allow_file_operations:
                file_ops = ["open(", "file(", "os.remove", "os.unlink", "shutil."]
                for op in file_ops:
                    if op in code:
                        result.add_error(
                            f"Code block {i + 1} contains disallowed file operation: {op}"
                        )

            # Check network operations
            if not security_config.allow_network_operations:
                network_ops = ["requests.", "urllib.", "socket.", "http."]
                for op in network_ops:
                    if op in code:
                        result.add_error(
                            f"Code block {i + 1} contains disallowed network operation: {op}"
                        )

        return result

    def _extract_code_blocks(self, text: str) -> list[dict[str, str]]:
        """
        Extract code blocks from markdown-formatted text.

        Args:
            text: Text containing code blocks

        Returns:
            List of dicts with 'language' and 'code' keys
        """
        code_blocks = []

        # Match markdown code blocks with optional language
        pattern = r"```(\w+)?\n(.*?)```"
        matches = re.finditer(pattern, text, re.DOTALL)

        for match in matches:
            language = match.group(1) or ""
            code = match.group(2).strip()
            code_blocks.append({"language": language, "code": code})

        return code_blocks

    def _check_python_syntax(self, code: str) -> ValidationResult:
        """
        Check Python code syntax.

        Args:
            code: Python code to check

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)

        try:
            ast.parse(code)
        except SyntaxError as e:
            result.add_error(f"Syntax error at line {e.lineno}: {e.msg}")
        except Exception as e:
            result.add_error(f"Parse error: {str(e)}")

        return result

    def _validate_json_schema(self, data: Any, schema: dict[str, Any]) -> ValidationResult:
        """
        Validate JSON data against a schema.

        Args:
            data: Parsed JSON data
            schema: JSON schema

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)

        try:
            # Try to use jsonschema if available
            import jsonschema

            jsonschema.validate(instance=data, schema=schema)
        except ImportError:
            # Fallback to basic validation if jsonschema not available
            result.add_warning("jsonschema not installed, skipping schema validation")
        except Exception as e:
            result.add_error(f"Schema validation failed: {str(e)}")

        return result
