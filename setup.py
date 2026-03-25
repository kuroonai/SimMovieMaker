from setuptools import setup, find_packages

setup(
    name="SimMovieMaker",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "opencv-python",
        "numpy",
        "Pillow",
    ],
    entry_points={
        "console_scripts": [
            "simmovimaker = simmovimaker.__main__:main",
        ],
    },
    python_requires=">=3.9",
    data_files=[
        ("assets", ["assets/smm.ico"]),
    ],
)
