#include <pybind11/pybind11.h>
#include <filesystem>

namespace py = pybind11;

/**
 * @brief Get the list of python modules.
 *
 */
py::tuple iter_modules() {
    return py::make_tuple();
}

PYBIND11_MODULE(_iter_modules, m) {
    m.doc() = "A fast version of pkgutil.iter_modules().";
    m.def(
        "iter_modules",
        &iter_modules,
        "A fast implementation of pkgutil.iter_modules(path=None, prefix='')",
        py::return_value_policy::take_ownership
    );
}
