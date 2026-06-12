"""Tests for the calculator module."""

import pytest
from calculator import add, subtract, multiply, divide


class TestAdd:
    def test_add_positive_numbers(self):
        assert add(2, 3) == 5
        assert add(10, 20) == 30

    def test_add_negative_numbers(self):
        assert add(-1, -1) == -2
        assert add(-5, 3) == -2

    def test_add_with_zero(self):
        assert add(0, 5) == 5
        assert add(7, 0) == 7
        assert add(0, 0) == 0

    def test_add_floats(self):
        assert add(1.5, 2.5) == 4.0
        assert add(0.1, 0.2) == pytest.approx(0.3, rel=1e-9)


class TestSubtract:
    def test_subtract_positive_numbers(self):
        assert subtract(5, 3) == 2
        assert subtract(10, 20) == -10

    def test_subtract_negative_numbers(self):
        assert subtract(-1, -1) == 0
        assert subtract(-5, -3) == -2

    def test_subtract_with_zero(self):
        assert subtract(0, 5) == -5
        assert subtract(7, 0) == 7
        assert subtract(0, 0) == 0

    def test_subtract_floats(self):
        assert subtract(5.5, 2.0) == 3.5
        assert subtract(0.3, 0.1) == pytest.approx(0.2, rel=1e-9)


class TestMultiply:
    def test_multiply_positive_numbers(self):
        assert multiply(2, 3) == 6
        assert multiply(10, 0) == 0

    def test_multiply_negative_numbers(self):
        assert multiply(-2, 3) == -6
        assert multiply(-2, -3) == 6

    def test_multiply_with_zero(self):
        assert multiply(0, 5) == 0
        assert multiply(0, 0) == 0

    def test_multiply_floats(self):
        assert multiply(2.5, 4.0) == 10.0
        assert multiply(1.5, 0.5) == 0.75


class TestDivide:
    def test_divide_positive_numbers(self):
        assert divide(6, 3) == 2.0
        assert divide(10, 4) == 2.5

    def test_divide_negative_numbers(self):
        assert divide(-6, 3) == -2.0
        assert divide(-6, -3) == 2.0

    def test_divide_with_zero_numerator(self):
        assert divide(0, 5) == 0.0

    def test_divide_by_zero_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(5, 0)
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(0, 0)

    def test_divide_floats(self):
        assert divide(7.0, 2.0) == 3.5
        assert divide(1.0, 3.0) == pytest.approx(0.3333333333, rel=1e-9)