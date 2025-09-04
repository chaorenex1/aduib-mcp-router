import logging
import os
import time

from aduib_app import AduibAIApp
from component.log.app_logging import init_logging
from configs import config

log=logging.getLogger(__name__)

def create_app_with_configs()->AduibAIApp:
    """ Create the FastAPI app with necessary configurations and middlewares.
    :return: AduibAIApp instance
    """

    app = AduibAIApp()
    app.config=config
    if config.APP_HOME:
        app.app_home = config.APP_HOME
    else:
        app.app_home = os.getcwd()
    return app


def create_app()->AduibAIApp:
    start_time = time.perf_counter()
    app = create_app_with_configs()
    init_logging(app)
    end_time = time.perf_counter()
    log.info(f"App home directory: {app.app_home}")
    log.info(f"Finished create_app ({round((end_time - start_time) * 1000, 2)} ms)")
    return app
