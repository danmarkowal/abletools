from setuptools import setup, find_packages


setup(
    name='abletools',
    version='0.1.0',
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    requires=[
        "psutil"
    ],
    entry_points={
        'console_scripts': [
            'abletools=abletools.cli:main',
        ],
    },
)
