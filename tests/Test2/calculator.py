"""A simple Python calculator with basic arithmetic operations."""


def add(a, b):
    """Return the sum of a and b."""
    return a + b


def subtract(a, b):
    """Return the result of subtracting b from a."""
    return a - b


def multiply(a, b):
    """Return the product of a and b."""
    return a * b


def divide(a, b):
    """Return the quotient of a divided by b.

    Raises:
        ValueError: If b is zero (division by zero is undefined).
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
