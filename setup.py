"""Distribution package setup script."""
from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.rst')) as readme_file:
    readme = readme_file.read()
try:
    with open('CHANGELOG.rst') as changelog_file:
        changelog = changelog_file.read()
    long_description = '\n\n'.join((readme, changelog))
except FileNotFoundError:
    long_description = readme

setup(
    name='keysightosc',

    description='Interface for Keysight Oscilloscopes.',
    long_description=long_description,
    author='Leander Claes',
    author_email='claes@emt.uni-paderborn.de',
    url='https://emt.uni-paderborn.de/',
    license='Proprietary',

    # Automatically generate version number from git tags
    use_scm_version=True,

    # Automatically detect the packages and sub-packages
    packages=find_packages(),

    # Runtime dependencies
    install_requires=[
        'pyvisa'
    ],

    # Python version requirement
    python_requires='>=3',

    # Dependencies of this setup script
    setup_requires=[
        'setuptools_scm',  # For automatic git-based versioning
    ],

    # For a full list of valid classifiers, see:
    # https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Science/Research',
        'License :: Other/Proprietary License',
        'Programming Language :: Python :: 3',
        'Topic :: Scientific/Engineering',
    ],
)
