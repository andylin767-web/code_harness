#!/usr/bin/env python3
"""Tests for the Hello World program."""

import pytest
from hello_world import main


def test_main_output(capsys):
    """Test that main() prints Hello, World! to stdout."""
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello, World!
"


def test_main_returns_none():
    """Test that main() returns None."""
    result = main()
    assert result is None
