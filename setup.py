from setuptools import setup, find_packages

with open("README.md") as f:
    long_description = f.read()

# Maybe we should use versioneer.py instead
with open("innerscope/__init__.py") as f:
    lines = f.readlines()
for line in lines:
    if line.startswith("__version__"):
        _, version, _ = line.split('"')
        break
else:
    raise ValueError("__version__ not found.  Aborting!")

setup(
    name="innerscope",
    version=version,
    description="Expose the inner scope of functions",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Erik Welch",
    url="https://github.com/eriknw/innerscope",
    packages=find_packages(),
    license="BSD",
    python_requires=">=3.8",
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
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3 :: Only",
    ],
)
