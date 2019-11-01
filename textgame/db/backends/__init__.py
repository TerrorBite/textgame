
# Import each backend module.


__all__ = []

#print(repr(__path__), repr(__file__), repr(__name__))

def _load_backends():
    import importlib
    import logging
    import pathlib

    logger = logging.getLogger(__name__)

    global __all__

    selfpath = pathlib.Path(__file__)
    for filepath in pathlib.Path(__path__[0]).iterdir():
        if not filepath.name.startswith('_'):
            name = filepath.stem
            module = importlib.import_module('.'+name, __name__)
            logger.log(5, f"Imported {module.__name__} from {module.__file__}")
            globals()[name] = module
            __all__.append(name)


_load_backends()
del _load_backends
