#!/usr/bin/env python3
"""Simple Calculator Program with basic arithmetic operations."""


def add(a, b):
    """Add two numbers."""
    return a + b


def subtract(a, b):
    """Subtract second number from first number."""
    return a - b


def multiply(a, b):
    """Multiply two numbers."""
    return a * b


def divide(a, b):
    """
    Divide first number by second number.
    
    Args:
        a: Dividend
        b: Divisor
        
    Returns:
        float: Result of division
        
    Raises:
        ValueError: When trying to divide by zero
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def main():
    """Demonstrate calculator operations."""
    print("Simple Calculator")
    print("=" * 30)
    
    # Example operations
    x, y = 10, 5
    
    print(f"{x} + {y} = {add(x, y)}")
    print(f"{x} - {y} = {subtract(x, y)}")
    print(f"{x} * {y} = {multiply(x, y)}")
    print(f"{x} / {y} = {divide(x, y)}")
    
    # Demonstrate division by zero handling
    print("
Testing division by zero:")
    try:
        result = divide(10, 0)
        print(f"10 / 0 = {result}")
    except ValueError as e:
        print(f"10 / 0 = Error: {e}")


if __name__ == "__main__":
    main()
