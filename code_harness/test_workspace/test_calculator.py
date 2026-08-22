#!/usr/bin/env python3
"""Tests for the Calculator program."""

import pytest
from calculator import add, subtract, multiply, divide


class TestAdd:
    """Tests for the add function."""

    def test_add_positive_numbers(self):
        """Test adding two positive numbers."""
        assert add(2, 3) == 5

    def test_add_negative_numbers(self):
        """Test adding two negative numbers."""
        assert add(-2, -3) == -5

    def test_add_positive_and_negative(self):
        """Test adding a positive and a negative number."""
        assert add(5, -3) == 2

    def test_add_zero(self):
        """Test adding zero."""
        assert add(5, 0) == 5
        assert add(0, 5) == 5
        assert add(0, 0) == 0

    def test_add_floats(self):
        """Test adding floating point numbers."""
        assert add(1.5, 2.5) == 4.0

    def test_add_large_numbers(self):
        """Test adding large numbers."""
        assert add(1000000, 2000000) == 3000000


class TestSubtract:
    """Tests for the subtract function."""

    def test_subtract_positive_numbers(self):
        """Test subtracting two positive numbers."""
        assert subtract(5, 3) == 2

    def test_subtract_negative_numbers(self):
        """Test subtracting two negative numbers."""
        assert subtract(-2, -3) == 1

    def test_subtract_result_negative(self):
        """Test subtracting resulting in negative number."""
        assert subtract(3, 5) == -2

    def test_subtract_zero(self):
        """Test subtracting zero."""
        assert subtract(5, 0) == 5
        assert subtract(0, 5) == -5
        assert subtract(0, 0) == 0

    def test_subtract_floats(self):
        """Test subtracting floating point numbers."""
        assert subtract(3.5, 1.5) == 2.0

    def test_subtract_large_numbers(self):
        """Test subtracting large numbers."""
        assert subtract(3000000, 1000000) == 2000000


class TestMultiply:
    """Tests for the multiply function."""

    def test_multiply_positive_numbers(self):
        """Test multiplying two positive numbers."""
        assert multiply(3, 4) == 12

    def test_multiply_negative_numbers(self):
        """Test multiplying two negative numbers."""
        assert multiply(-3, -4) == 12

    def test_multiply_positive_and_negative(self):
        """Test multiplying a positive and a negative number."""
        assert multiply(3, -4) == -12

    def test_multiply_zero(self):
        """Test multiplying by zero."""
        assert multiply(5, 0) == 0
        assert multiply(0, 5) == 0
        assert multiply(0, 0) == 0

    def test_multiply_one(self):
        """Test multiplying by one."""
        assert multiply(5, 1) == 5
        assert multiply(1, 5) == 5

    def test_multiply_floats(self):
        """Test multiplying floating point numbers."""
        assert multiply(2.5, 4.0) == 10.0

    def test_multiply_large_numbers(self):
        """Test multiplying large numbers."""
        assert multiply(1000, 2000) == 2000000


class TestDivide:
    """Tests for the divide function."""

    def test_divide_positive_numbers(self):
        """Test dividing two positive numbers."""
        assert divide(10, 2) == 5.0

    def test_divide_negative_numbers(self):
        """Test dividing two negative numbers."""
        assert divide(-10, -2) == 5.0

    def test_divide_positive_and_negative(self):
        """Test dividing a positive by a negative number."""
        assert divide(10, -2) == -5.0

    def test_divide_zero_numerator(self):
        """Test dividing zero by a number."""
        assert divide(0, 5) == 0.0

    def test_divide_by_zero_raises_error(self):
        """Test that dividing by zero raises ValueError."""
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            divide(10, 0)

    def test_divide_floats(self):
        """Test dividing floating point numbers."""
        assert divide(7.5, 2.5) == 3.0

    def test_divide_result_float(self):
        """Test that division returns float."""
        result = divide(10, 3)
        assert isinstance(result, float)
        assert abs(result - 3.3333333333333335) < 1e-10

    def test_divide_large_numbers(self):
        """Test dividing large numbers."""
        assert divide(1000000, 1000) == 1000.0


class TestCalculatorIntegration:
    """Integration tests for calculator functions."""

    def test_add_then_subtract(self):
        """Test chaining add and subtract operations."""
        result = add(10, 5)
        result = subtract(result, 3)
        assert result == 12

    def test_multiply_then_divide(self):
        """Test chaining multiply and divide operations."""
        result = multiply(4, 5)
        result = divide(result, 2)
        assert result == 10.0

    def test_complex_calculation(self):
        """Test a complex calculation using multiple operations."""
        result = add(10, 5)   # 15
        result = multiply(result, 2)  # 30
        result = subtract(result, 10)  # 20
        result = divide(result, 4)  # 5.0
        assert result == 5.0
