#include "pybind11/cast.h"
#include <optional>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <filesystem>
#include <string>
#include <vector>

namespace py = pybind11;
namespace fs = std::filesystem;

/**
 * @brief Get the list of python modules.
 *
 */
std::optional<std::vector<std::string>> _iter_file_finder_modules(py::object importer, std::string prefix) {

    std::vector<std::string> ret;

    py::object path_obj = importer.attr("path");
    if (path_obj.is_none()) {
        return ret;
    }

    auto path = fs::path(py::str(path_obj).cast<std::string>());
    if (!fs::is_directory(path)) {
        return ret;
    }

    // bool filesystem

    py::object importer_path = importer.attr("path");
    return py::make_tuple();
}

PYBIND11_MODULE(_fast_iter_modules, m) {
    m.doc() = "A fast version of pkgutil._iter_file_finder_modules.";
    m.def(
        "_iter_file_finder_modules",
        &_iter_file_finder_modules,
        "A fast implementation of pkgutil._iter_file_finder_modules(importer, prefix='')",
        py::arg("importer"),
        py::arg("prefix") = py::str(""),
        py::return_value_policy::take_ownership
    );
}
