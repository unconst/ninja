"""Tests for the mylib C extension."""
import pytest


def test_import_mylib():
    """Test that mylib can be imported."""
    import mylib
    assert hasattr(mylib, 'fast_sum')
    assert hasattr(mylib, '__version__')


def test_fast_sum_integers():
    """Test fast_sum with a list of integers."""
    from mylib import fast_sum
    result = fast_sum([1, 2, 3, 4, 5])
    assert result == 15.0


def test_fast_sum_floats():
    """Test fast_sum with a list of floats."""
    from mylib import fast_sum
    result = fast_sum([1.5, 2.5, 3.0])
    assert abs(result - 7.0) < 1e-9


def test_fast_sum_mixed():
    """Test fast_sum with mixed int and float."""
    from mylib import fast_sum
    result = fast_sum([1, 2.5, 3, 4.5])
    assert abs(result - 11.0) < 1e-9


def test_fast_sum_empty():
    """Test fast_sum with an empty list."""
    from mylib import fast_sum
    result = fast_sum([])
    assert result == 0.0


def test_fast_sum_single():
    """Test fast_sum with a single element."""
    from mylib import fast_sum
    assert fast_sum([42]) == 42.0


def test_fast_sum_negative():
    """Test fast_sum with negative numbers."""
    from mylib import fast_sum
    result = fast_sum([-1, -2, 3])
    assert result == 0.0


def test_fast_sum_type_error():
    """Test that fast_sum raises TypeError for non-list input."""
    from mylib import fast_sum
    with pytest.raises(TypeError):
        fast_sum("not a list")


def test_fast_sum_bad_items():
    """Test that fast_sum raises TypeError for non-numeric items."""
    from mylib import fast_sum
    with pytest.raises(TypeError):
        fast_sum([1, "two", 3])
