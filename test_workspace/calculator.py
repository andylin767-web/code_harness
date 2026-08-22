#!/usr/bin/env python3
"""A simple calculator program supporting basic arithmetic operations."""


def add(a: float, b: float) -> float:
    """Return the sum of two numbers."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference of two numbers."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of two numbers."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return the quotient of two numbers."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def main():
    """Interactive calculator loop."""
    print("Simple Calculator")
    print("Operations: +, -, *, /")
    print("Type 'quit' to exit\n")

    while True:
        user_input = input("Enter expression (e.g., 5 + 3): ").strip()
        if user_input.lower() == "quit":
            print("Goodbye!")
            break

        try:
            parts = user_input.split()
            if len(parts) != 3:
                print("Invalid input. Use format: number operator number")
                continue

            a = float(parts[0])
            op = parts[1]
            b = float(parts[2])

            if op == "+":
                result = add(a, b)
            elif op == "-":
                result = subtract(a, b)
            elif op == "*":
                result = multiply(a, b)
            elif op == "/":
                result = divide(a, b)
            else:
                print(f"Unknown operator: {op}")
                continue

            print(f"Result: {result}")
        except ValueError as e:
            print(f"Error: {e}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
