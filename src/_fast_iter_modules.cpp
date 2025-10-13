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

  // Check if the directory is readable by examining its permissions.
  // We use the overload of fs::status that takes an error_code to avoid throwing exceptions
  // if the status itself cannot be retrieved (e.g., due to permissions).
  std::error_code ec;
  fs::file_status s = fs::status(path, ec);

  if (ec) {
    // If we couldn't get the status (e.g., due to permissions or other system errors),
    // we treat the path as unreadable/inaccessible and skip it.
    return ret;
  }

  // Check if any read permission bit is set for the owner, group, or others.
  // This is a common heuristic to determine if a directory is "readable" for iteration.
  fs::perms p = s.permissions();
  if (!((p & fs::perms::owner_read) != fs::perms::none ||
        (p & fs::perms::group_read) != fs::perms::none ||
        (p & fs::perms::others_read) != fs::perms::none)) {
    // The directory exists but no read permission is explicitly set, so we skip it.
    return ret;
  }

  // If the directory is deemed readable based on permissions, proceed with iteration.
  // Note: While we've checked permissions, fs::directory_iterator might still throw
  // in rare cases (e.g., if the directory is removed concurrently or other non-permission
  // related OS errors occur). However, this addresses the specific "permissions 000" case
  // without using a try/catch block around the iterator itself.
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

  return ret;
}

PYBIND11_MODULE(_fast_iter_modules, m) {
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
