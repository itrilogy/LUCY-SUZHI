import re

from setuptools import setup, find_packages

# Read the content of the README file
with open("README.md", encoding="utf-8") as f:
    long_description = f.read()
    # Remove p tags.
    pattern = re.compile(r"<p.*?>.*?</p>", re.DOTALL)
    long_description = re.sub(pattern, "", long_description)

# Read the content of the requirements.txt file
with open("requirements.txt", encoding="utf-8") as f:
    requirements = f.read().splitlines()


setup(
    name="suzhi-storm",
    version="1.0.0",
    author="鹿溪联合创新实验室",
    author_email="",
    description="溯知 · SuZhi：深度知识策展与学术长文生成（引擎代号 STORM）。含受 Stanford STORM（MIT）启发的独立异步重写。",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    license="MIT License",
    packages=find_packages(exclude=["tests", "tests.*", "path", "path.*", "examples", "examples.*", "frontend", "frontend.*"]),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.10",
    install_requires=requirements,
)
