"""Test that all of our modules can be imported

Thanks https://stackoverflow.com/a/25562415/10473080
"""
import importlib
import pkgutil

import netcdf_scm


def import_submodules(package_name):
    package = importlib.import_module(package_name)

    for _, name, is_pkg in pkgutil.walk_packages(package.__path__):
        full_name = package.__name__ + "." + name
        importlib.import_module(full_name)
        if is_pkg:
            import_submodules(full_name)


import_submodules("netcdf_scm")
print(netcdf_scm.__version__)
