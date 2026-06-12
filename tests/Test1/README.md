# Python Calculator

A simple Python calculator module that provides four basic arithmetic operations: addition, subtraction, multiplication, and division.

## Features

- **add(a, b)** – Returns the sum of `a` and `b`.
- **subtract(a, b)** – Returns the difference of `a` and `b`.
- **multiply(a, b)** – Returns the product of `a` and `b`.
- **divide(a, b)** – Returns the quotient of `a` divided by `b`. Raises a `ValueError` if `b` is zero.

## Requirements

- Python 3.6 or later

No external dependencies are required.

## Usage

```python
from calculator import add, subtract, multiply, divide

# Addition
result = add(10, 5)          # 15

# Subtraction
result = subtract(10, 5)     # 5

# Multiplication
result = multiply(10, 5)     # 50

# Division
result = divide(10, 5)       # 2.0

# Division by zero raises ValueError
try:
    divide(10, 0)
except ValueError as e:
    print(e)                 # "Cannot divide by zero"
```

You can also run the module directly to see a demo:

```bash
python calculator.py
```

## Running Tests

Tests are written using Python's built-in `unittest` framework.

```bash
cd Test1
python -m unittest test_calculator.py
```

To run with verbose output:

```bash
python -m unittest test_calculator.py -v
```

### Test Coverage

- **add** – positive numbers, negative numbers, mixed signs, floats, zeros
- **subtract** – positive numbers, negative numbers, floats, equal numbers
- **multiply** – positive numbers, multiplication by zero, negative numbers, floats
- **divide** – positive numbers, division by zero (raises ValueError), negative numbers, floats, fractional results

## API Reference

### `add(a, b)`
- **Parameters:** `a` (int/float), `b` (int/float)
- **Returns:** `a + b`

### `subtract(a, b)`
- **Parameters:** `a` (int/float), `b` (int/float)
- **Returns:** `a - b`

### `multiply(a, b)`
- **Parameters:** `a` (int/float), `b` (int/float)
- **Returns:** `a * b`

### `divide(a, b)`
- **Parameters:** `a` (int/float), `b` (int/float)
- **Returns:** `a / b`
- **Raises:** `ValueError` if `b` is zero
