"""Calculator tool for performing arithmetic operations."""


def calculate(expression: str) -> float | str:
    """
    Perform arithmetic calculations on a mathematical expression.

    This tool evaluates mathematical expressions safely using Python's eval
    with restricted globals to prevent code execution.

    Args:
        expression: Mathematical expression to evaluate (e.g., "2 + 2", "10 * 5 / 2")

    Returns:
        Result of the calculation as a float, or error message as string

    Examples:
        >>> calculate("2 + 2")
        4.0
        >>> calculate("10 * 5")
        50.0
        >>> calculate("100 / 4")
        25.0
    """
    try:
        # Restricted namespace for safe evaluation
        # Only allow basic math operations and built-in math functions
        safe_dict = {
            "__builtins__": {},
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
        }

        # Evaluate the expression
        result = eval(expression, safe_dict, {})

        # Convert to float for consistency
        return float(result)

    except ZeroDivisionError:
        return "Error: Division by zero"
    except SyntaxError:
        return f"Error: Invalid expression syntax: {expression}"
    except NameError as e:
        return f"Error: Invalid operation or function: {e}"
    except Exception as e:
        return f"Error: Could not evaluate expression: {e}"
