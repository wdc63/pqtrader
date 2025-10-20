from setuptools import setup, find_packages

# 定义核心依赖
install_requires = [
    "PyYAML>=6.0",
    "pandas>=1.5.0",
    "numpy>=1.23.0",
    "empyrical-reloaded>=0.5.8",
    "Flask>=2.2.0",
    "watchdog==6.0.0",
    "Flask-SocketIO>=5.3.0",
    "Jinja2>=3.1.0",
    "pyecharts>=2.0.0",
    "pydantic>=2.0",
]

# 定义可选的测试依赖
extras_require = {
    "test": ["pytest>=7.0"],
}

setup(
    name="qtrader",
    version="0.1.0",
    description="A flexible, event-driven backtesting framework for quantitative trading.",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=install_requires,
    extras_require=extras_require,
    python_requires=">=3.9",
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Office/Business :: Financial :: Investment",
    ],
)
