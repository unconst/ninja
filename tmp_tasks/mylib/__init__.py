"""mylib - A small library with fast math operations."""

try:
    from ._fastmath import fast_sum
except ImportError as e:
    raise ImportError(
        f"Failed to import C extension '_fastmath'. "
        f"Make sure you ran 'make build' first. Error: {e}"
    )

__version__ = '0.1.0'
__all__ = ['fast_sum']
