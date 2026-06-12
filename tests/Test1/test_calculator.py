"""Unit tests for the calculator module."""

import unittest
from calculator import add, subtract, multiply, divide


class TestCalculator(unittest.TestCase):
    """Test cases for all calculator operations."""

    # ---------- add ----------
    def test_add_positive(self):
        self.assertEqual(add(3, 5), 8)

    def test_add_negative(self):
        self.assertEqual(add(-2, -3), -5)

    def test_add_mixed(self):
        self.assertEqual(add(-2, 7), 5)

    def test_add_float(self):
        self.assertAlmostEqual(add(0.1, 0.2), 0.3)

    def test_add_zero(self):
        self.assertEqual(add(0, 0), 0)

    # ---------- subtract ----------
    def test_subtract_positive(self):
        self.assertEqual(subtract(10, 3), 7)

    def test_subtract_negative(self):
        self.assertEqual(subtract(-5, -2), -3)

    def test_subtract_float(self):
        self.assertAlmostEqual(subtract(1.5, 0.5), 1.0)

    def test_subtract_to_zero(self):
        self.assertEqual(subtract(5, 5), 0)

    # ---------- multiply ----------
    def test_multiply_positive(self):
        self.assertEqual(multiply(4, 3), 12)

    def test_multiply_by_zero(self):
        self.assertEqual(multiply(5, 0), 0)

    def test_multiply_negative(self):
        self.assertEqual(multiply(-3, 4), -12)

    def test_multiply_float(self):
        self.assertAlmostEqual(multiply(2.5, 2), 5.0)

    # ---------- divide ----------
    def test_divide_positive(self):
        self.assertEqual(divide(10, 2), 5)

    def test_divide_by_zero(self):
        with self.assertRaises(ValueError):
            divide(10, 0)

    def test_divide_negative(self):
        self.assertEqual(divide(-12, 3), -4)

    def test_divide_float(self):
        self.assertAlmostEqual(divide(1, 3), 0.3333333333, places=7)

    def test_divide_result_float(self):
        self.assertEqual(divide(5, 2), 2.5)


if __name__ == "__main__":
    unittest.main()
