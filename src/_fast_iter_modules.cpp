#include "pybind11/cast.h"
#include "pybind11/pytypes.h"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <filesystem>
#include <string>
#include <tuple>
#include <vector>

namespace py = pybind11;
namespace fs = std::filesystem;
using namespace pybind11::literals;

/**
 * @brief Fast equivalent of `inspect.getmodulename`.
 *
 * @param path Path to a file
 * @param suffixes Suffixes of valid python modules. Typically this is
 *      `importlib.machinery.all_suffixes()`
 * @return The stem of the file, if this is a module; empty string otherwise
 */
std::string getmodulename(fs::path path, std::vector<std::string> suffixes) {
    fs::path ext = path.extension();
    for (auto const& suffix : suffixes) {
        std::string path_str = path.string();
        std::string::size_type pos = path_str.rfind(suffix);
        if (pos != std::string::npos) {
            return path_str.substr(0, pos);
        }
    }
    return "";
}

/**
 * @brief Get a list of importable python modules.
 *
 *      See `pkgutil._iter_file_finder_modules` for the original python version.
 *
 * @param importer Importer instance containing an import path. Typically this is an object of type
 *      `importlib.machinery.FileFinder`
 * @param suffixes Suffixes of valid python modules. Typically this is
 *      `importlib.machinery.all_suffixes()`
 * @return A vector of tuples containing modules names, and a boolean indicating whether the module
 *      is a package or not
 */
std::vector<std::tuple<std::string, bool>>
_iter_file_finder_modules(
    py::object importer,
    std::vector<std::string> suffixes
) {
  std::vector<std::tuple<std::string, bool>> ret;

  // The importer doesn't have a path
  py::object path_obj = importer.attr("path");
  if (path_obj.is_none()) {
    return ret;
  }

  // The importer's path isn't an existing directory
  fs::path path = fs::path(py::str(path_obj).cast<std::string>());
  if (!fs::is_directory(path) || !fs::exists(path)) {
    return ret;
  }

  // Attempt to iterate the directory. If the directory is unreadable for any reason
  // (e.g., permissions, non-existent, or other system errors), fs::directory_iterator
  // will throw a filesystem_error. We catch this and return an empty list for this path.
  try {
    for (auto const &entry : fs::directory_iterator(path)) {
      fs::path entry_path = entry.path();
      fs::path filename = entry_path.filename();
      std::string modname = getmodulename(filename, suffixes);


      if (modname == "" && fs::is_directory(entry_path) &&
          filename.string().find(".") == std::string::npos &&
          fs::is_regular_file(entry_path / "__init__.py") // Is this a package?
      ) {
        ret.push_back(std::make_tuple(filename.string(), true));
      } else if (modname == "__init__") {
        continue;
      } else if (modname != "" && modname.find(".") == std::string::npos) {
        ret.push_back(std::make_tuple(modname,
                                      false // This is definitely not a package
                                      ));
      }
    }
  } catch (const fs::filesystem_error& e) {
    // If an error occurs during directory iteration (e.g., permissions denied,
    // directory removed concurrently), we treat it as unreadable/inaccessible
    // and return the current (potentially empty) list, effectively skipping this path.
    // We could log the error 'e.what()' here if desired for debugging.
    return ret;
  }

  return ret;
}

PYBIND11_MODULE(_fast_iter_modules, m, py::mod_gil_not_used()) {
    m.doc() = "A fast version of pkgutil._iter_file_finder_modules.";
    m.def(
        "_iter_file_finder_modules",
        &_iter_file_finder_modules,
        "A fast implementation of pkgutil._iter_file_finder_modules(importer, prefix='')",
        py::arg("importer"),
        py::arg("suffixes") = std::make_tuple(".py", ".pyc"),
        py::return_value_policy::take_ownership
    );
}
