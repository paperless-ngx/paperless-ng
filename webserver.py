if __name__ == "__main__":
    import os

    from granian import Granian
    from granian.constants import Interfaces

    Granian(
        "paperless.asgi:application",
        interface=Interfaces.ASGI,
        address=os.getenv("GRANIAN_HOST") or os.getenv("PAPERLESS_BIND_ADDR", "::"),
        port=int(os.getenv("GRANIAN_PORT") or os.getenv("PAPERLESS_PORT") or 8000),
        workers=int(
            os.getenv("GRANIAN_WORKERS")
            or os.getenv("PAPERLESS_WEBSERVER_WORKERS")
            or 1,
        ),
        websockets=True,
        url_path_prefix=os.getenv("PAPERLESS_FORCE_SCRIPT_NAME"),
    ).serve()
