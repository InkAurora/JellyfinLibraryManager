# plugin_loader.py
import importlib.util
import os
from plugin_base import PluginBase

PLUGIN_FOLDER = os.path.join(os.path.dirname(__file__), 'plugins')

def load_plugins(app_context):
    plugins = []
    if not os.path.exists(PLUGIN_FOLDER):
        return plugins
    for filename in os.listdir(PLUGIN_FOLDER):
        if filename.endswith('.py') and not filename.startswith('__'):
            module_name = filename[:-3]
            module_path = os.path.join(PLUGIN_FOLDER, filename)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr in dir(module):
                    obj = getattr(module, attr)
                    if isinstance(obj, type) and issubclass(obj, PluginBase) and obj is not PluginBase:
                        plugin_instance = obj()
                        plugin_instance.activate(app_context)
                        plugins.append(plugin_instance)
    return plugins
