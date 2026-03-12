#ifndef FASTMATH_H
#define FASTMATH_H

#include <Python.h>

/* Compute the sum of a list of numbers. Returns a Python float. */
static PyObject* fastmath_fast_sum(PyObject* self, PyObject* args);

#endif /* FASTMATH_H */
