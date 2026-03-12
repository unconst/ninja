"""Build configuration for mylib C extension."""
from setuptools import setup, Extension, find_packages
import numpy

ext_modules = [
    Extension(
        'mylib._fastmath',
        sources=['mylib/_fastmath.c'],
        include_dirs=[
            'include',
            numpy.get_include(),
        ],
        language='c',
    ),
]

setup(
    name='mylib',
    version='0.1.0',
    packages=find_packages(),
    ext_modules=ext_modules,
    python_requires='>=3.8',
)
