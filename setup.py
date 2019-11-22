"""
A setuptools script for yet another scheduler
"""

import atexit
import os
import sys
import shutil
from setuptools import setup, find_packages
from setuptools.command.install import install
from yascheduler import __version__, CONFIG_FILE

package_name = "yascheduler"
package_version = __version__


class CustomInstall(install):
    def run(self):
        def _post_install():
            def find_module_path():
                for p in sys.path:
                    if os.path.isdir(p) and package_name in os.listdir(p):
                        return os.path.join(p, package_name)
            install_path = find_module_path()
            src_config = os.path.join(install_path, 'data/yascheduler.conf')
            if not os.path.isfile(CONFIG_FILE):
                config_dir = os.path.dirname(CONFIG_FILE)
                os.makedirs(config_dir)
                shutil.copy(src_config, CONFIG_FILE)

        atexit.register(_post_install)
        install.run(self)


if __name__ == '__main__':
    setup(
        name=package_name,
        version=package_version,
        author="Eugeny Blokhin",
        author_email="eb@tilde.pro",
        description="Yet another scheduler",
        long_description=open('README.rst').read(),
        license="MIT",
        packages=find_packages(),
        package_data={'yascheduler': ['data/*']},
        install_requires=[
            "pg8000",
            "fabric",
            "python-daemon"
        ],
        entry_points={
          "console_scripts": ["yasubmit = yascheduler.utils:submit",
                              "yastatus = yascheduler.utils:check_status",
                              "yainitdb = yascheduler.utils:init_db"]
        },
        cmdclass={'install': CustomInstall},
    )
