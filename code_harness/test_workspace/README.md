# Python Calculator & Hello World Project

A simple Python project demonstrating basic arithmetic operations and a classic "Hello, World!" program, complete with comprehensive pytest test suites.

## Project Description

This project contains beginner-friendly Python programs that showcase:
- Console output with `hello_world.py`
- Basic arithmetic operations (add, subtract, multiply, divide) with `calculator.py`
- Thorough unit tests using `pytest` for both programs

## Files Included

| File | Description |
|------|-------------|
| `hello_world.py` | Prints "Hello, World!" to the console |
| `calculator.py` | Calculator with add, subtract, multiply, and divide operations |
| `test_hello_world.py` | Pytest tests for `hello_world.py` |
| `test_calculator.py` | Pytest tests for `calculator.py` (including edge cases) |

## How to Run the Programs

### Hello World
```bash
python3 hello_world.py
```

### Calculator
```bash
python3 calculator.py
```

The calculator can also be used as a module:
```python
from calculator import add, subtract, multiply, divide

result = add(5, 3)       # 8
result = subtract(10, 4) # 6
result = multiply(3, 7)  # 21
result = divide(15, 3)   # 5.0
```

## How to Run the Tests

### Prerequisites
Make sure you have `pytest` installed:
```bash
pip install pytest
```

### Running All Tests
```bash
pytest -v
```

### Running Individual Test Files
```bash
pytest -v test_hello_world.py
pytest -v test_calculator.py
```

## Dependencies

- **Python 3.6+**
- **pytest** - for running the test suites
  ```bash
  pip install pytest
  ```

No additional third-party libraries are required.

## License

This project is provided as-is for educational purposes.
