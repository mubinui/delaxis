"""
Property-based tests for agent output format validation.

**Feature: industry-grade-orchestration, Property 10: Output format validation**
**Validates: Requirements 4.4**
"""

import json
import pytest
from hypothesis import given, strategies as st, settings, assume

from src.config.behavior_models import (
    AgentBehaviorConfig,
    ConstraintsConfig,
    OutputFormatConfig,
    OutputFormatType,
    SecurityConfig,
)
from src.config.behavior_validator import AgentBehaviorValidator, ValidationResult


# Strategies for generating test data
@st.composite
def valid_json_output(draw):
    """Generate valid JSON output."""
    data = {
        "result": draw(st.text(min_size=1, max_size=100)),
        "status": draw(st.sampled_from(["success", "error", "pending"])),
        "count": draw(st.integers(min_value=0, max_value=1000))
    }
    return json.dumps(data)


@st.composite
def invalid_json_output(draw):
    """Generate invalid JSON output."""
    # Generate text that looks like JSON but is malformed
    options = [
        '{"key": "value"',  # Missing closing brace
        '{"key": value}',  # Unquoted value
        "{'key': 'value'}",  # Single quotes
        '{key: "value"}',  # Unquoted key
        '{"key": "value",}',  # Trailing comma
    ]
    return draw(st.sampled_from(options))


@st.composite
def valid_code_output(draw):
    """Generate valid code output with markdown code blocks."""
    language = draw(st.sampled_from(["python", "javascript", "java", "go"]))
    code = draw(st.text(min_size=10, max_size=200, alphabet=st.characters(
        whitelist_categories=('Lu', 'Ll', 'Nd', 'P'),
        whitelist_characters=' \n\t'
    )))
    return f"```{language}\n{code}\n```"


@st.composite
def code_output_without_language(draw):
    """Generate code output without language specification."""
    code = draw(st.text(min_size=10, max_size=200))
    return f"```\n{code}\n```"


@st.composite
def text_with_forbidden_pattern(draw):
    """Generate text containing forbidden patterns."""
    forbidden = draw(st.sampled_from(["eval(", "exec(", "compile(", "__import__("]))
    prefix = draw(st.text(max_size=50))
    suffix = draw(st.text(max_size=50))
    return f"{prefix}{forbidden}{suffix}"


@st.composite
def python_code_with_syntax_error(draw):
    """Generate Python code with syntax errors."""
    errors = [
        "def foo(\n    pass",  # Missing closing paren
        "if True\n    pass",  # Missing colon
        "for i in range(10)\n    print(i)",  # Missing colon
        "def foo():\nreturn 1",  # Incorrect indentation
    ]
    return f"```python\n{draw(st.sampled_from(errors))}\n```"


@st.composite
def valid_python_code(draw):
    """Generate valid Python code."""
    codes = [
        "def hello():\n    return 'world'",
        "x = 10\ny = 20\nprint(x + y)",
        "for i in range(5):\n    print(i)",
        "class MyClass:\n    def __init__(self):\n        self.value = 42",
    ]
    return f"```python\n{draw(st.sampled_from(codes))}\n```"


class TestOutputFormatValidation:
    """
    Property 10: Output format validation
    
    For any agent with configured output format constraints, generated output
    should be validated against those constraints and rejected if non-compliant.
    
    Validates: Requirements 4.4
    """
    
    @settings(max_examples=100)
    @given(json_output=valid_json_output())
    def test_valid_json_format_passes(self, json_output):
        """
        Property: Valid JSON output should pass JSON format validation.
        
        For any valid JSON string, validation with JSON format type
        should succeed.
        """
        # Create behavior config with JSON format
        behavior = AgentBehaviorConfig(
            output_format=OutputFormatConfig(type=OutputFormatType.JSON)
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(json_output)
        
        # Should pass
        assert result.valid, f"Valid JSON failed validation: {result.errors}"
        assert len(result.errors) == 0
    
    @settings(max_examples=100)
    @given(invalid_json=invalid_json_output())
    def test_invalid_json_format_fails(self, invalid_json):
        """
        Property: Invalid JSON output should fail JSON format validation.
        
        For any malformed JSON string, validation with JSON format type
        should fail with appropriate error.
        """
        # Create behavior config with JSON format
        behavior = AgentBehaviorConfig(
            output_format=OutputFormatConfig(type=OutputFormatType.JSON)
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(invalid_json)
        
        # Should fail
        assert not result.valid, "Invalid JSON passed validation"
        assert len(result.errors) > 0
        assert any("json" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(code_output=valid_code_output())
    def test_valid_code_format_passes(self, code_output):
        """
        Property: Valid code output with language specification should pass validation.
        
        For any code block with proper markdown formatting and language,
        validation should succeed.
        """
        # Create behavior config with code format
        behavior = AgentBehaviorConfig(
            output_format=OutputFormatConfig(
                type=OutputFormatType.CODE,
                language="auto_detect"
            )
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(code_output)
        
        # Should pass (may have warnings about language mismatch)
        assert result.valid or len(result.warnings) > 0
    
    @settings(max_examples=100)
    @given(code_output=code_output_without_language())
    def test_code_without_language_fails_when_required(self, code_output):
        """
        Property: Code output without language specification should fail when required.
        
        For any code block without language specification, validation with
        require_language_specification should fail.
        """
        # Create behavior config requiring language specification
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(
                require_language_specification=True
            )
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(code_output)
        
        # Should fail
        assert not result.valid, "Code without language passed validation"
        assert len(result.errors) > 0
        assert any("language" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(
        output=st.text(min_size=1, max_size=50),
        max_length=st.integers(min_value=51, max_value=1000)
    )
    def test_output_exceeding_max_length_fails(self, output, max_length):
        """
        Property: Output exceeding max length should fail validation.
        
        For any output longer than configured max_output_length,
        validation should fail.
        """
        # Ensure output is shorter than max_length for this test
        assume(len(output) < max_length)
        
        # Create output that exceeds max_length
        long_output = output * (max_length // len(output) + 2)
        
        # Create behavior config with max length
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(max_output_length=max_length)
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(long_output)
        
        # Should fail
        assert not result.valid, "Long output passed validation"
        assert len(result.errors) > 0
        assert any("length" in err.lower() or "exceeds" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(
        output=st.text(min_size=100, max_size=200),
        min_length=st.integers(min_value=1, max_value=50)
    )
    def test_output_below_min_length_fails(self, output, min_length):
        """
        Property: Output below min length should fail validation.
        
        For any output shorter than configured min_output_length,
        validation should fail.
        """
        # Ensure output is longer than min_length for this test
        assume(len(output) > min_length)
        
        # Create output that is below min_length
        short_output = output[:min_length - 1]
        
        # Create behavior config with min length
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(min_output_length=min_length)
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(short_output)
        
        # Should fail
        assert not result.valid, "Short output passed validation"
        assert len(result.errors) > 0
        assert any("length" in err.lower() or "below" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(output=text_with_forbidden_pattern())
    def test_forbidden_patterns_fail_validation(self, output):
        """
        Property: Output containing forbidden patterns should fail validation.
        
        For any output containing a forbidden pattern,
        validation should fail with appropriate error.
        """
        # Create behavior config with forbidden patterns
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(
                forbidden_patterns=[r"eval\(", r"exec\(", r"compile\(", r"__import__\("]
            )
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(output)
        
        # Should fail
        assert not result.valid, "Output with forbidden pattern passed validation"
        assert len(result.errors) > 0
        assert any("forbidden" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(
        prefix=st.text(max_size=50),
        suffix=st.text(max_size=50),
        required=st.sampled_from(["REQUIRED", "MUST_HAVE", "ESSENTIAL"])
    )
    def test_missing_required_patterns_fail_validation(self, prefix, suffix, required):
        """
        Property: Output missing required patterns should fail validation.
        
        For any output that doesn't contain a required pattern,
        validation should fail.
        """
        # Create output without the required pattern. The validator matches
        # patterns case-insensitively, so a case-sensitive assumption lets
        # through inputs like output="required" / pattern="REQUIRED", where
        # the pattern really is present as far as validation is concerned.
        output = f"{prefix}{suffix}"
        assume(required.lower() not in output.lower())
        
        # Create behavior config with required pattern
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(
                required_patterns=[required]
            )
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(output)
        
        # Should fail
        assert not result.valid, "Output without required pattern passed validation"
        assert len(result.errors) > 0
        assert any("required" in err.lower() or "missing" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(code=python_code_with_syntax_error())
    def test_python_syntax_errors_detected(self, code):
        """
        Property: Python code with syntax errors should fail validation.
        
        For any Python code with syntax errors, validation with
        syntax_check enabled should fail.
        """
        # Create behavior config with syntax checking
        behavior = AgentBehaviorConfig(
            validation=SecurityConfig(syntax_check=True)
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(code)
        
        # Should fail
        assert not result.valid, "Code with syntax error passed validation"
        assert len(result.errors) > 0
        assert any("syntax" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(code=valid_python_code())
    def test_valid_python_syntax_passes(self, code):
        """
        Property: Valid Python code should pass syntax validation.
        
        For any syntactically correct Python code, validation with
        syntax_check enabled should succeed.
        """
        # Create behavior config with syntax checking
        behavior = AgentBehaviorConfig(
            validation=SecurityConfig(syntax_check=True)
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(code)
        
        # Should pass
        assert result.valid, f"Valid Python code failed validation: {result.errors}"
    
    @settings(max_examples=100)
    @given(
        prefix=st.text(max_size=50),
        suffix=st.text(max_size=50),
        dangerous_func=st.sampled_from(["eval", "exec", "compile", "__import__"])
    )
    def test_dangerous_functions_detected(self, prefix, suffix, dangerous_func):
        """
        Property: Code containing dangerous functions should fail security scan.
        
        For any code containing dangerous functions like eval, exec,
        validation with security_scan enabled should fail.
        """
        # Create code with dangerous function
        code = f"```python\n{prefix}\n{dangerous_func}('malicious code')\n{suffix}\n```"
        
        # Create behavior config with security scanning
        behavior = AgentBehaviorConfig(
            validation=SecurityConfig(
                security_scan=True,
                dangerous_functions=["eval", "exec", "compile", "__import__"]
            )
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(code)
        
        # Should fail
        assert not result.valid, f"Code with {dangerous_func} passed security scan"
        assert len(result.errors) > 0
        assert any("dangerous" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(
        language=st.sampled_from(["python", "javascript", "java"]),
        disallowed_lang=st.sampled_from(["ruby", "php", "perl"])
    )
    def test_disallowed_languages_fail_validation(self, language, disallowed_lang):
        """
        Property: Code in disallowed languages should fail validation.
        
        For any code in a language not in allowed_languages list,
        validation should fail.
        """
        assume(disallowed_lang not in [language])
        
        # Create code in disallowed language
        code = f"```{disallowed_lang}\nsome code here\n```"
        
        # Create behavior config with allowed languages
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(
                allowed_languages=[language]
            )
        )
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(code)
        
        # Should fail
        assert not result.valid, f"Code in disallowed language {disallowed_lang} passed validation"
        assert len(result.errors) > 0
        assert any("disallowed" in err.lower() or "language" in err.lower() for err in result.errors)
    
    @settings(max_examples=100)
    @given(
        output=st.text(min_size=10, max_size=100)
    )
    def test_no_validation_always_passes(self, output):
        """
        Property: Output should always pass when no validation is configured.
        
        For any output, validation with no constraints should always succeed.
        """
        # Create behavior config with no validation
        behavior = AgentBehaviorConfig()
        validator = AgentBehaviorValidator(behavior)
        
        # Validate
        result = validator.validate(output)
        
        # Should always pass
        assert result.valid, "Output failed validation with no constraints"
        assert len(result.errors) == 0
