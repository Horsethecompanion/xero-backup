"""
Step 1: Generate a self-signed TLS certificate for localhost.

Xero requires HTTPS redirect URIs, so our local callback server needs
a cert. This is self-signed and only used on your own machine -
your browser will show a "not secure" warning, which is expected
and safe to click through (it's only talking to localhost).

Run this once: python3 1_generate_cert.py
Produces: cert.pem and key.pem in this folder.
"""

import datetime
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
])

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
    .add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        ]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

with open("key.pem", "wb") as f:
    f.write(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

with open("cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("Created cert.pem and key.pem")
print("Next: edit 2_login.py with your Client ID/Secret, then run it")
