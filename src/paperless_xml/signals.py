def get_parser(*args, **kwargs):
    from paperless_xml.parsers import XMLDocumentParser

    return XMLDocumentParser(*args, **kwargs)


def xml_consumer_declaration(sender, **kwargs):
    return {
        "parser": get_parser,
        "weight": 11,
        "mime_types": {
            "text/plain": ".txt",
            "text/xml": ".xml",
            "application/xml": ".xml",
        },
    }
