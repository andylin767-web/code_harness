# Python Basics

A small collection of beginner-friendly Python scripts.

## Files

### `hello_world.py`

A classic "Hello, World!" program that prints a greeting to the console.

**Run it:**

```bash
python hello_world.py
```

**Output:**

```
Hello, World!
```

---

### `calculator.py`

A simple interactive calculator supporting four basic arithmetic operations:

| Operation  | Function     | Example          |
|------------|--------------|------------------|
| Addition   | `add(a, b)`  | `add(2, 3) → 5`  |
| Subtraction| `subtract(a, b)` | `subtract(5, 2) → 3` |
| Multiplication | `multiply(a, b)` | `multiply(4, 3) → 12` |
| Division   | `divide(a, b)` | `divide(10, 2) → 5.0` |

**Run the interactive menu:**

```bash
python calculator.py
```

**Use as a module:**

```python
from calculator import add, subtract, multiply, divide

print(add(10, 5))       # 15
print(subtract(10, 5))  # 5
print(multiply(10, 5))  # 50
print(divide(10, 5))    # 2.0
```

> **Note:** Division by zero raises a `ZeroDivisionError`.
