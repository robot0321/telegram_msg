"""구버전 pip의 editable install을 위한 호환용 설정."""

from setuptools import setup


setup(
    name="telegram-msg",
    version="0.1.0",
    description="Local Telegram message and approval daemon",
    packages=["telegram_bot"],
    py_modules=["daemon"],
    python_requires=">=3.8",
    install_requires=["requests>=2.28,<3"],
    entry_points={
        "console_scripts": [
            "telbot=telegram_bot.cli:main",
            "telegram-msg-daemon=daemon:main",
        ],
    },
)
