# Python Calculator

A simple Python calculator module providing basic arithmetic operations.

## Functions

| Function     | Description                                   | Example                  |
|--------------|-----------------------------------------------|--------------------------|
| `add(a, b)`  | Returns the sum of `a` and `b`.               | `add(2, 3) → 5`         |
| `subtract(a, b)` | Returns the result of subtracting `b` from `a`. | `subtract(5, 3) → 2` |
| `multiply(a, b)` | Returns the product of `a` and `b`.           | `multiply(2, 3) → 6`    |
| `divide(a, b)`   | Returns the quotient of `a` divided by `b`.   | `divide(6, 3) → 2.0`    |

> **Note:** `divide(a, b)` raises a `ValueError` if `b` is zero (division by zero is undefined).

## Usage

```python
from calculator import add, subtract, multiply, divide

print(add(10, 5))        # 15
print(subtract(10, 5))   # 5
print(multiply(10, 5))   # 50
print(divide(10, 5))     # 2.0

# Division by zero raises an error
try:
    divide(10, 0)
except ValueError as e:
    print(e)  # "Cannot divide by zero"
```

## Running Tests

Tests are written using **pytest**. To run them:

```bash
# From the project root directory
pytest tests/Test2/ -v
```

All tests should pass successfully (17 tests covering normal cases, negative numbers, floats, zero operands, and division by zero).

## Requirements

- Python 3.8+
- pytest (for running tests)

## License

This project is for educational purposes.