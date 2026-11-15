"""Give local CSS and JavaScript content-addressed URLs on every build.

The CDN may keep the previous bytes at an unchanged URL after deployment.
Keep source filenames convenient for editing and generate versioned siblings
only in the site output. Original URLs remain available for older pages.
"""

from copy import deepcopy
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from mkdocs.exceptions import PluginError
from mkdocs.plugins import event_priority
from mkdocs.structure.files import File


_css_sources = []
_script_sources = []


def on_config(config):
    global _css_sources, _script_sources
    # MkDocs serve can rebuild with the same config after an asset is edited.
    # Always start from source URLs, never from the previous build's hashes.
    _css_sources = deepcopy(config.extra_css)
    _script_sources = deepcopy(config.extra_javascript)
    return config


@event_priority(-100)
def on_files(files, config):
    def fingerprint(url):
        parts = urlsplit(url)
        if parts.scheme or parts.netloc or parts.path.startswith("/"):
            return url
        source = files.get_file_from_path(parts.path)
        if source is None:
            raise PluginError(f"Cannot version missing local asset: {parts.path}")
        content = source.content_bytes
        path = PurePosixPath(parts.path)
        version = sha256(content).hexdigest()[:12]
        generated = str(path.with_name(f"{path.stem}.{version}{path.suffix}"))
        if files.get_file_from_path(generated) is None:
            files.append(File.generated(config, generated, content=content))
        return urlunsplit(parts._replace(path=generated))

    config.extra_css = [fingerprint(url) for url in _css_sources]
    scripts = []
    for source in _script_sources:
        if isinstance(source, str):
            scripts.append(fingerprint(source))
        else:
            script = deepcopy(source)
            script.path = fingerprint(script.path)
            scripts.append(script)
    config.extra_javascript = scripts
    return files
