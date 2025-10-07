import os
from flask import current_app
from pyodk.client import Client


def va_odk_clientsetup():
    try:
        client = Client(
            config_path=os.path.join(
                current_app.config.get("APP_RESOURCE"), "pyodk", "odk_config.toml"
            ),
            cache_path=os.path.join(
                current_app.config.get("APP_RESOURCE"), "pyodk", "odk_cache.toml"
            ),
        )
        return client
    except Exception as e:
        raise Exception(f"pyODK Client initialization failed: {str(e)}")
