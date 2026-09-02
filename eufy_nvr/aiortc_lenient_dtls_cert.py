#!/usr/bin/env python3
"""Patch aiortc so it tolerates the eufy NVR's malformed DTLS certificate.

The eufy S4 / T8N00 NVR presents a self-signed DTLS certificate whose
AlgorithmIdentifier carries trailing bytes. `cryptography` >= 43 rejects it:

    ValueError: error parsing asn1 value: ParseError { kind: ExtraData,
      location: ["Certificate::tbs_cert", "TbsCertificate::signature_alg"] }

aiortc calls ``get_peer_certificate(as_cryptography=True)`` in
``_validate_peer_identity`` only to fingerprint the cert and match it against the
SDP ``a=fingerprint`` line. We just need the DER bytes for that, and OpenSSL's
i2d serialiser is lenient, so wrap the strict parse in a fallback that
fingerprints the raw DER instead. The DTLS handshake and SRTP keying are
untouched.

Idempotent. Asserts the upstream shape so a future aiortc refactor fails the
build loudly instead of silently dropping the fingerprint check.
"""
import pathlib
import sys

import aiortc.rtcdtlstransport as m

path = pathlib.Path(m.__file__)
src = path.read_text()

MARKER = "_eufy_lenient_dtls_cert"
if MARKER in src:
    print(f"[aiortc-patch] already applied to {path}")
    sys.exit(0)

NEEDLE = "        certificate = self._ssl.get_peer_certificate(as_cryptography=True)\n"
if NEEDLE not in src:
    sys.exit(
        "[aiortc-patch] FAILED: _validate_peer_identity no longer matches the "
        "expected shape; review aiortc and update this patch."
    )

REPLACEMENT = (
    f"        # --- {MARKER}: eufy NVR DTLS cert is malformed; cryptography>=43\n"
    "        # refuses to parse it. Fall back to fingerprinting the raw DER. ---\n"
    "        try:\n"
    "            certificate = self._ssl.get_peer_certificate(as_cryptography=True)\n"
    "        except ValueError:\n"
    "            from OpenSSL import crypto as _eufy_crypto\n"
    "\n"
    "            class _EufyLenientCert:\n"
    "                def __init__(self, der: bytes) -> None:\n"
    "                    self._der = der\n"
    "\n"
    "                def fingerprint(self, algorithm):\n"
    "                    h = hashes.Hash(algorithm)\n"
    "                    h.update(self._der)\n"
    "                    return h.finalize()\n"
    "\n"
    "            certificate = _EufyLenientCert(\n"
    "                _eufy_crypto.dump_certificate(\n"
    "                    _eufy_crypto.FILETYPE_ASN1, self._ssl.get_peer_certificate()\n"
    "                )\n"
    "            )\n"
)

path.write_text(src.replace(NEEDLE, REPLACEMENT, 1))
print(f"[aiortc-patch] applied lenient DTLS cert fingerprinting to {path}")
