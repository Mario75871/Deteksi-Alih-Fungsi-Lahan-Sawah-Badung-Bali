"""
Script 00: Uji Autentikasi Copernicus Data Space Ecosystem (CDSE)
=================================================================
Menghubungkan ke CDSE via openEO dan menyimpan refresh token di komputer lokal.
Setelah berhasil login sekali, script lainnya tidak perlu login ulang.

Cara pakai:
    python scripts/00_test_auth.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

import openeo


def test_login():
    print("=" * 60)
    print("UJI LOGIN COPERNICUS DATA SPACE (CDSE)")
    print("=" * 60)
    print(f"Backend URL: {config.OPENEO_BACKEND_URL}")
    print("Menghubungkan...")

    conn = openeo.connect(config.OPENEO_BACKEND_URL)

    print("\n[INFO] Membuka sesi autentikasi OpenID Connect (OIDC)...")
    print("Petunjuk:")
    print("1. Jika browser terbuka otomatis, silakan login dengan akun CDSE Anda.")
    print("2. Jika muncul tautan (URL) dan kode di terminal, buka tautan tersebut di browser dan masukkan kodenya.")
    print("3. Setelah berhasil, token akan disimpan otomatis di komputer Anda.\n")

    try:
        conn.authenticate_oidc()
        print("\n" + "=" * 60)
        print("[SUKSES] Autentikasi Berhasil!")
        print("Akun CDSE Anda sudah terhubung ke pipeline openEO di Python.")
        print("Refresh token sudah tersimpan untuk penggunaan berikutnya.")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"\n[GAGAL] Terjadi kesalahan saat autentikasi: {e}")
        return False


if __name__ == "__main__":
    test_login()
