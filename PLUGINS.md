# How to Create a Plugin for Jellyfin Library Manager

This application supports plugins to extend its functionality. Follow these steps to create your own plugin:

## 1. Inherit from PluginBase

Create a new Python file in the `plugins/` directory. Your plugin should define a class that inherits from `PluginBase` (see `plugin_base.py`).

```
from plugin_base import PluginBase

class MyPlugin(PluginBase):
    name = "My Custom Plugin"

    def activate(self, app_context):
        # Your plugin logic here
        print(f"{self.name} activated!")
```

## 2. Implement the `activate` Method

The `activate(self, app_context)` method is called when your plugin is loaded. Use the `app_context` parameter to interact with the main application.

## 3. Place Your Plugin in the Plugins Folder

Save your plugin file in the `plugins/` directory. For example: `plugins/my_plugin.py`.

## 4. Restart the Application

When you start the application, your plugin will be automatically discovered and activated.

## 5. Accessing the App Context

The `app_context` parameter gives you access to the main application instance. You can use it to:

- Access or modify application state
- Register new menu items (with further development)
- Interact with other plugins

## Example Plugin

```
from plugin_base import PluginBase

class ExamplePlugin(PluginBase):
    name = "ExamplePlugin"

    def activate(self, app_context):
        print(f"{self.name} activated! App context: {app_context}")
```

## Notes

- Each plugin must have a unique class name and `name` attribute.
- Only `.py` files in the `plugins/` folder are loaded as plugins.
- Plugins are loaded at application startup.

For advanced integration (e.g., adding menu items), further development of the plugin API may be required.
