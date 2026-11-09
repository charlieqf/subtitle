"""Independent Chinese subtitle processing. No network requests on import."""

__version__ = '0.2.0'
__all__ = ['prepare','probe','export_transcript','transcribe','render','run']

def prepare(*args, **kwargs):
    from .media import prepare as implementation
    return implementation(*args, **kwargs)

def probe(*args, **kwargs):
    from .media import probe as implementation
    return implementation(*args, **kwargs)

def export_transcript(*args, **kwargs):
    from .api import export_transcript as implementation
    return implementation(*args, **kwargs)

def transcribe(*args, **kwargs):
    from .api import transcribe as implementation
    return implementation(*args, **kwargs)

def render(*args, **kwargs):
    from .api import render as implementation
    return implementation(*args, **kwargs)

def run(*args, **kwargs):
    from .api import run as implementation
    return implementation(*args, **kwargs)
