"""
Run once to generate RS256 key pair for JWT signing.
Usage: python scripts/generate_keys.py
Saves private.pem and public.pem in the project root.
Never commit these files to git.
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from pathlib import Path

private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)
public_key = private_key.public_key()

private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
)
public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)

Path("private.pem").write_bytes(private_pem)
Path("public.pem").write_bytes(public_pem)
print("✅ private.pem and public.pem generated successfully.")
print("⚠️  Never commit these files to git!")
