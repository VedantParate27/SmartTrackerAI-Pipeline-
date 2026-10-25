import os
import datetime
import socket
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import ipaddress

def get_lan_ips():
    ips = {"127.0.0.1", "10.108.147.119"}
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ":" not in ip:  # IPv4
                ips.add(ip)
    except Exception:
        pass
    return list(ips)

def generate_self_signed_cert(cert_dir="certs"):
    cert_path = Path(cert_dir)
    cert_path.mkdir(parents=True, exist_ok=True)
    
    key_file = cert_path / "key.pem"
    cert_file = cert_path / "cert.pem"

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Maharashtra"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Mumbai"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SmartTracker AI"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    lan_ips = get_lan_ips()
    san_list = [
        x509.DNSName("localhost"),
    ]
    for ip_str in lan_ips:
        san_list.append(x509.DNSName(ip_str))
        try:
            san_list.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        except ValueError:
            pass

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"SSL certificate generated successfully at:\n  - {cert_file.resolve()}\n  - {key_file.resolve()}")
    print(f"Included SANs: {[str(n) for n in san_list]}")

if __name__ == "__main__":
    generate_self_signed_cert()
