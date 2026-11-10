"""The one network helper the fotocasa module needs: the Accept-Language
its sessions send. Fotocasa is a Spanish site, so every session announces
the list a desktop Chrome in Spain sends — on your own connection or on
FOTOCASA_PROXY alike."""

SPANISH = "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7"


def site_accept_language(site=None):
    return SPANISH


def accept_language(proxy=None, country=None):
    return SPANISH
