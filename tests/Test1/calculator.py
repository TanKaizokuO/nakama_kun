"""Simple calculator module with four basic operations."""

def add(a, b):
    """Return the sum of a and b."""
    return a + b


def subtract(a, b):
    """Return the difference of a and b."""
    return a - b


def multiply(a, b):
    """Return the product of a and b."""
    return a * b


def divide(a, b):
    """Return the quotient of a divided by b.
    
    Raises:
        ValueError: If b is zero.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


if __name__ == "__main__":
    print("Calculator Demo")
    print(f"add(10, 5) = {add(10, 5)}")
    print(f"subtract(10, 5) = {subtract(10, 5)}")
    print(f"multiply(10, 5) = {multiply(10, 5)}")
    print(f"divide(10, 5) = {divide(10, 5)}")
    try:
        divide(10, 0)
    except ValueError as e:
        print(f"divide(10, 0) -> ValueError: {e}")
