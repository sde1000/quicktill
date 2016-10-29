# Very simple plugin attachment system

class ClassPluginMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'plugins'):
            cls.plugins = []
        else:
            cls.plugins.append(cls)

class InstancePluginMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'instances'):
            cls.instances = []

    def __call__(cls, *args, **kwargs):
        cls.instances.append(type.__call__(cls, *args, **kwargs))
