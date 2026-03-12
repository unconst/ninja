#include "fastmath.h"

static PyObject* fastmath_fast_sum(PyObject* self, PyObject* args) {
    PyObject* input_list;
    if (!PyArg_ParseTuple(args, "O", &input_list)) {
        return NULL;
    }

    if (!PyList_Check(input_list)) {
        PyErr_SetString(PyExc_TypeError, "Argument must be a list");
        return NULL;
    }

    Py_ssize_t size = PyList_Size(input_list);
    double total = 0.0;

    for (Py_ssize_t i = 0; i < size; i++) {
        PyObject* item = PyList_GetItem(input_list, i);
        if (PyLong_Check(item)) {
            total += (double)PyLong_AsLong(item);
        } else if (PyFloat_Check(item)) {
            total += PyFloat_AsDouble(item);
        } else {
            PyErr_SetString(PyExc_TypeError,
                "List items must be int or float");
            return NULL;
        }
    }

    return PyFloat_FromDouble(total);
}

static PyMethodDef FastmathMethods[] = {
    {"fast_sum", fastmath_fast_sum, METH_VARARGS,
     "Compute the sum of a list of numbers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef fastmathmodule = {
    PyModuleDef_HEAD_INIT,
    "_fastmath",
    "Fast math operations C extension module.",
    -1,
    FastmathMethods
};

PyMODINIT_FUNC PyInit__fastmath(void) {
    return PyModule_Create(&fastmathmodule);
}
