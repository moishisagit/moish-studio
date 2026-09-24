"""The Moish seam — the one place this fork of Unsloth Studio meets Moish (plan.md §4.2).

Studio is the application; Moish is the authority. This package makes that structural:

* ``config``    the gateway URL (loopback only) and where the Studio client credential lives;
* ``providers`` the ONLY provider (``moish``) and the provider store Studio sees;
* ``client``    the request the gateway accepts, and nothing else;
* ``guards``    every local runtime spawn raises; tools and keyless access are off;
* ``seam``      ``register(app)`` wires the above in and adds ``/api/moish/selfcheck``.

Moish never imports this package (the platform talks to Studio only over HTTP). Every
upstream edit that calls into it is recorded in ``UPSTREAM_DELTA.md``.
"""

from moish.seam import register

__all__ = ["register"]
