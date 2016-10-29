# Very simple plugin attachment system

class PluginMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'plugins'):
            cls.plugins = []
            cls.instances = []
        else:
            cls.plugins.append(cls)

    def __call__(cls, *args, **kwargs):
        cls.instances.append(type.__call__(cls, *args, **kwargs))
