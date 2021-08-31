import logging

from utils.path_utils import build_path


def setup_logging():
    logging.getLogger('binance-client').setLevel(logging.WARN)
    logging.getLogger('binance-futures').setLevel(logging.WARN)
    logging.getLogger('apscheduler.executors.default').setLevel(logging.INFO)
    logging.getLogger('apscheduler.executors.default').propagate = False

    formatter = logging.Formatter('%(asctime)s [%(name)-12.12s] %(levelname)s : %(message)s')
    file_handler = logging.FileHandler(build_path(['logs', 'dorabot.log']), encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[stream_handler, file_handler])


def get_controller_logger():
    logger = logging.getLogger('main-controller')
    logger.setLevel(logging.DEBUG)
    return logger


def get_signal_bot_logger():
    return logging.getLogger('signal-bot')


def get_dca_bot_logger():
    return logging.getLogger('dca-bot')


def get_wallet_logger():
    return logging.getLogger('wallet')


def get_telegram_bot_logger():
    logger = logging.getLogger('telegram-bot')
    logger.setLevel(logging.INFO)
    return logger


controller_logger = get_controller_logger()
signal_bot_logger = get_signal_bot_logger()
dca_bot_logger = get_dca_bot_logger()
wallet_logger = get_wallet_logger()
telegram_bot_logger = get_telegram_bot_logger()
