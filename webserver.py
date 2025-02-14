import os

if __name__ == "__main__":
    from granian import Granian
    from granian.constants import Interfaces

    Granian(
        "paperless.asgi:application",
        interface=Interfaces.ASGI,
        address=os.getenv("PAPERLESS_BIND_ADDR", "::"),
        port=int(os.getenv("PAPERLESS_PORT", 8000)),
        workers=int(os.getenv("PAPERLESS_WEBSERVER_WORKERS", 1)),
        websockets=True,
        # TODO, test this
        url_path_prefix=os.getenv("PAPERLESS_FORCE_SCRIPT_NAME"),
    ).serve()
