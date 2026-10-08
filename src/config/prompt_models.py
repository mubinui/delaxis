"""Pydantic models for prompt template configuration validation."""

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationInfo, field_validator


def extract_variables(template: str) -> list[str]:
    """
    Extract variable names from a template string.

    Args:
        template: Template string with variables in {variable_name} format

    Returns:
        List of unique variable names found in the template
    """
    # Only valid Python identifiers count as variables ({123} or {-x} are not)
    pattern = r"\{([A-Za-z_][A-Za-z0-9_]*)\}"
    variables = re.findall(pattern, template)
    # Unique, in order of first appearance, so the list reads like the template.
    return list(dict.fromkeys(variables))


class PromptTemplateConfig(BaseModel):
    """Configuration for a prompt template."""

    id: str = Field(pattern=r"^[a-z0-9_]+$", description="Unique prompt template identifier")
    name: str = Field(min_length=1, description="Human-readable name for the prompt template")
    description: str = Field(
        min_length=1, description="Description of what this prompt template is used for"
    )
    template: str = Field(
        description="Prompt template text with variables in {variable_name} format"
    )
    variables: list[str] = Field(
        default_factory=list, description="List of variable names used in the template"
    )
    category: str | None = Field(
        default=None, description="Category for organizing prompt templates"
    )

    # Versioning and metadata fields
    version: int = Field(default=1, ge=1, description="Configuration version number")
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last configuration update",
    )

    @field_validator("template")
    @classmethod
    def validate_template_syntax(cls, v: str) -> str:
        """
        Validate prompt template syntax.

        Checks for:
        - Properly closed variable placeholders
        - No nested placeholders
        - Valid variable names (alphanumeric and underscore only)

        Args:
            v: Template string to validate

        Returns:
            Validated template string

        Raises:
            ValueError: If template syntax is invalid
        """
        if not v or not v.strip():
            raise ValueError("Template cannot be empty")

        # Check for unclosed braces
        open_count = v.count("{")
        close_count = v.count("}")
        if open_count != close_count:
            raise ValueError(
                f"Template has mismatched braces: {open_count} opening, {close_count} closing"
            )

        # Extract all variable placeholders
        pattern = r"\{([^{}]+)\}"
        matches = re.findall(pattern, v)

        for match in matches:
            # Check for nested braces (would indicate malformed template)
            if "{" in match or "}" in match:
                raise ValueError(f"Template contains nested braces in variable: {{{match}}}")

            # Validate variable name format (must be a valid identifier)
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", match):
                raise ValueError(
                    f"Invalid variable name '{match}'. "
                    "Variable names must start with a letter or underscore and "
                    "contain only letters, numbers, and underscores"
                )

        return v

    @field_validator("variables")
    @classmethod
    def validate_variables_match_template(cls, v: list[str], info: ValidationInfo) -> list[str]:
        """
        Validate that variables list matches variables in template.

        Args:
            v: List of variable names
            info: Validation context containing other field values

        Returns:
            Validated variables list

        Raises:
            ValueError: If variables don't match template
        """
        template = info.data.get("template")
        if template:
            # Extract variables from template
            pattern = r"\{([^{}]+)\}"
            template_vars = set(re.findall(pattern, template))
            provided_vars = set(v)

            # Check for missing variables
            missing = template_vars - provided_vars
            if missing:
                raise ValueError(
                    f"Template contains variables not in variables list: {sorted(missing)}"
                )

            # Check for extra variables
            extra = provided_vars - template_vars
            if extra:
                raise ValueError(
                    f"Variables list contains variables not in template: {sorted(extra)}"
                )

        return v

    def extract_variables(self) -> list[str]:
        """
        Extract variable names from the template.

        Returns:
            List of unique variable names found in the template
        """
        pattern = r"\{([^{}]+)\}"
        variables = re.findall(pattern, self.template)
        return sorted(set(variables))

    def validate_config(self) -> None:
        """
        Validate the complete prompt template configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        # Ensure variables list matches template
        extracted_vars = self.extract_variables()
        if set(extracted_vars) != set(self.variables):
            raise ValueError(
                f"Prompt {self.id}: variables list {self.variables} "
                f"does not match template variables {extracted_vars}"
            )


class PromptsConfig(BaseModel):
    """Root configuration for prompt templates."""

    version: str = Field(description="Configuration version")
    prompts: list[PromptTemplateConfig] = Field(
        description="List of prompt template configurations"
    )

    def get_prompt(self, prompt_id: str) -> PromptTemplateConfig | None:
        """
        Get prompt template configuration by ID.

        Args:
            prompt_id: Prompt template identifier

        Returns:
            PromptTemplateConfig or None if not found
        """
        return next((p for p in self.prompts if p.id == prompt_id), None)

    def validate_all(self) -> None:
        """
        Validate all prompt template configurations.

        Raises:
            ValueError: If any prompt configuration is invalid
        """
        # Check for duplicate IDs
        prompt_ids = [p.id for p in self.prompts]
        if len(prompt_ids) != len(set(prompt_ids)):
            duplicates = [pid for pid in prompt_ids if prompt_ids.count(pid) > 1]
            raise ValueError(f"Duplicate prompt IDs found: {set(duplicates)}")

        # Validate each prompt
        for prompt in self.prompts:
            prompt.validate_config()
