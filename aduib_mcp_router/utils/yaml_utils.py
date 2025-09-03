import logging
import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore
from yaml import YAMLError

logger = logging.getLogger(__name__)


def load_yaml_file(file_path: str, ignore_error: bool = True, default_value: Any = {}) -> Any:
    """
    Safe loading a YAML file
    :param file_path: the path of the YAML file
    :param ignore_error:
        if True, return default_value if error occurs and the error will be logged in debug level
        if False, raise error if error occurs
    :param default_value: the value returned when errors ignored
    :return: an object of the YAML content
    """
    if not file_path or not Path(file_path).exists():
        if ignore_error:
            return default_value
        else:
            raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, encoding="utf-8") as yaml_file:
        try:
            yaml_content = yaml.safe_load(yaml_file)
            return yaml_content or default_value
        except Exception as e:
            if ignore_error:
                return default_value
            else:
                raise YAMLError(f"Failed to load YAML file {file_path}: {e}") from e


def load_yaml_files(file_path: str, ignore_error: bool = True, default_value: Any = []) -> list[Any]:
    """
    Safe loading multiple YAML files from a directory
    :param file_path: the path of the directory containing YAML files
    :param ignore_error:
        if True, return default_value if error occurs and the error will be logged in debug level
        if False, raise error if error occurs
    :param default_value: the value returned when errors ignored
    :return: a list of objects of the YAML content
    """
    if not file_path or not Path(file_path).is_dir():
        if ignore_error:
            return []
        else:
            raise FileNotFoundError(f"Directory not found: {file_path}")

    yaml_contents = []
    for root, _, files in os.walk(file_path):
        for yaml_file in files:
            if yaml_file.endswith('.yaml') and not yaml_file.startswith('__'):
                try:
                    yaml_content = load_yaml_file(os.path.join(root, yaml_file),
                                                  ignore_error=ignore_error, default_value=default_value)
                    yaml_contents.append(yaml_content)
                except Exception as e:
                    if not ignore_error:
                        raise e

    return yaml_contents