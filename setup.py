import versioneer
from setuptools import setup, find_packages


with open("README.md") as f:
    long_description = f.read()

setup(
    name="innerscope",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    description="Expose the inner scope of functions",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Erik Welch",
    url="https://github.com/eriknw/innerscope",
    packages=find_packages(),
    license="BSD",
    python_requires=">=3.6",
    setup_requires=[],
    install_requires=["toolz"],
    tests_require=["pytest"],
    include_package_data=True,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
)
