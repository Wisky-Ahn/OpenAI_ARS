"""애플리케이션 전역 로깅 설정과 로거 헬퍼를 제공합니다."""

import logging
import os
from logging import Logger


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(level: int = logging.DEBUG) -> None:
    """환경 변수 기반으로 로깅 레벨을 설정하고 포맷을 초기화합니다."""

    log_level_name = os.getenv("LOG_LEVEL")
    if log_level_name:
        numeric_level = logging.getLevelName(log_level_name.upper())
        if isinstance(numeric_level, int):
            level = numeric_level

    logging.basicConfig(level=level, format=LOG_FORMAT)


def get_logger(name: str) -> Logger:
    """모듈별 로거를 반환합니다."""

    return logging.getLogger(name)


