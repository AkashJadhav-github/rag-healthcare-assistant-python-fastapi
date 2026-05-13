"""Generate RSA-2048 key pair for RS256 JWT signing and print .env lines."""
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

priv = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode().strip().replace("\n", "\\n")

pub = key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode().strip().replace("\n", "\\n")

print("# Add these lines to your .env file:")
print(f"JWT_PRIVATE_KEY={priv}")
print(f"JWT_PUBLIC_KEY={pub}")
