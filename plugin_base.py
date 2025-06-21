# plugin_base.py

class PluginBase:
    """
    Base class for all plugins. Plugins should inherit from this class and implement the `activate` method.
    """
    name = "BasePlugin"

    def activate(self, app_context):
        """
        Called when the plugin is loaded. Use app_context to interact with the main app.
        """
        raise NotImplementedError("Plugin must implement the activate method.")
