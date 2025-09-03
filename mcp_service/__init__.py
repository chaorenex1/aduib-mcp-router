import importlib
import pkgutil

def load_mcp_plugins(package_name: str = __name__):
    """
    自动加载指定 package 下所有子模块，触发 @mcp.tool 装饰器。
    """
    package = importlib.import_module(package_name)
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        full_module_name = f"{package_name}.{module_name}"
        importlib.import_module(full_module_name)
