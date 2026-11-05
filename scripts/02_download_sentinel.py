"""
Script 02: Buat Komposit Sentinel-2 via OpenEO (Server-Side Processing)
=======================================================================
Data mentah Sentinel-2 (~8-17 GB) TIDAK didownload.
Semua pemrosesan berat dilakukan di server CDSE:
  1. Load Sentinel-2 L2A → server
  2. Cloud masking (SCL) → server
  3. Komposit median → server
  4. Clip & resample → server
  5. Download HANYA hasil komposit → ~50-100 MB per tahun

Cara pakai:
    python scripts/02_download_sentinel.py

Prasyarat:
    - Akun CDSE aktif (https://dataspace.copernicus.eu)
    - pip install openeo geopandas rasterio
    - Script 01 sudah dijalankan (boundary tersedia)
"""

import sys
from pathlib import Path

# Pastikan output konsol selalu UTF-8 di Windows
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

import openeo
import geopandas as gpd
import rasterio
import numpy as np


def connect_cdse(max_retries=6, delay=5):
    """Koneksi ke CDSE OpenEO dengan toleransi timeout/network hiccup."""
    print("=" * 60)
    print("Koneksi ke Copernicus Data Space Ecosystem (CDSE)")
    print("=" * 60)

    for attempt in range(max_retries):
        try:
            connection = openeo.connect(config.OPENEO_BACKEND_URL)
            connection.authenticate_oidc()
            print("[OK] Berhasil terautentikasi via token!\n")
            return connection
        except Exception as e:
            err_msg = str(e)
            print(f"  [RETRY {attempt+1}/{max_retries}] Kendala koneksi auth ({err_msg[:60]}...). Mencoba lagi dalam {delay} detik...")
            time.sleep(delay)

    raise ConnectionError("Gagal terhubung ke CDSE setelah beberapa percobaan.")


def get_spatial_extent():
    """Ambil bounding box dari boundary file atau config."""
    if config.BOUNDARY_FILE.exists():
        gdf = gpd.read_file(config.BOUNDARY_FILE)
        bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
        extent = {
            "west": float(bounds[0]) - 0.01,
            "south": float(bounds[1]) - 0.01,
            "east": float(bounds[2]) + 0.01,
            "north": float(bounds[3]) + 0.01,
            "crs": "EPSG:4326",
        }
        print(f"[INFO] Extent dari boundary file (+ buffer 0.01°)")
    else:
        extent = {**config.BADUNG_BBOX, "crs": "EPSG:4326"}
        print(f"[WARNING] Boundary file belum ada, pakai bbox dari config")

    print(f"  W={extent['west']:.4f}  S={extent['south']:.4f}")
    print(f"  E={extent['east']:.4f}  N={extent['north']:.4f}")
    return extent


def build_composite_process(connection, spatial_extent, date_start, date_end, year):
    """
    Bangun process graph OpenEO untuk komposit Sentinel-2.
    Semua tahap berikut dijalankan di SERVER CDSE:
      1. Load band B02, B03, B04, B08, B11, B12, SCL
      2. Mask piksel awan/shadow/cirrus (SCL)
      3. Hitung median temporal per piksel
      4. Drop band SCL dari output
      5. Resample ke resolusi 10m, proyeksi UTM 50S
    """
    print(f"\n{'-' * 60}")
    print(f"  Membangun process graph - Oktober {year}")
    print(f"{'-' * 60}")

    reflectance_bands = config.BANDS_10M + config.BANDS_20M  # B02-B12
    all_bands = reflectance_bands + config.BANDS_SCL           # + SCL

    # --- Step 1: Load koleksi ---
    print(f"  [1/5] Load {config.OPENEO_COLLECTION}")
    print(f"        Periode: {date_start} -> {date_end}")
    print(f"        Bands: {all_bands}")

    s2 = connection.load_collection(
        config.OPENEO_COLLECTION,
        spatial_extent=spatial_extent,
        temporal_extent=[date_start, date_end],
        bands=all_bands,
    )

    # --- Step 2: Cloud masking via SCL ---
    print(f"  [2/5] Cloud masking (SCL in {config.SCL_MASK_VALUES})")

    scl_band = s2.band("SCL")
    cloud_mask = None
    for val in config.SCL_MASK_VALUES:
        cond = (scl_band == val)
        cloud_mask = cond if cloud_mask is None else (cloud_mask | cond)

    s2_reflectance = s2.filter_bands(reflectance_bands)
    s2_masked = s2_reflectance.mask(cloud_mask)

    # --- Step 3: Komposit median ---
    print(f"  [3/5] Komposit median (per piksel, sepanjang waktu)")

    composite = s2_masked.reduce_dimension(dimension="t", reducer="median")

    # --- Step 4: Resample ---
    res = config.TARGET_RESOLUTION
    print(f"  [4/5] Resample ke {res}m - EPSG:32750 (UTM 50S)")

    composite = composite.resample_spatial(
        resolution=res,
        projection=32750,
    )

    # --- Step 5: Siap ---
    print(f"  [5/5] Process graph siap untuk {year}")

    return composite


def submit_and_download(composite, output_path, year):
    """
    Kirim job ke server CDSE, tunggu selesai, download hasilnya.
    Biasanya butuh 5-15 menit per job.
    """
    print(f"\n  +-- SUBMIT JOB: Komposit Oktober {year}")
    print(f"  |  Target File : {output_path}")
    print(f"  |  Pemrosesan di server CDSE (estimasi 5-15 menit)...")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    job = composite.create_job(
        title=f"Badung_S2_Oct{year}_composite",
        out_format="GTiff",
    )

    print(f"  |  Job ID: {job.job_id}")
    print(f"  |  Status: menjalankan job...")

    job.start_and_wait()

    print(f"  |  Job selesai! Mendownload hasil...")

    # Download ke folder sementara untuk tahun ini
    temp_dir = output_path.parent / f"temp_{year}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    downloaded = job.download_results(target=temp_dir)
    print(f"  |  Downloaded: {list(downloaded.keys()) if downloaded else 'ok'}")

    # Cari file .tif dari hasil download dan rename ke output_path yang diinginkan
    tif_candidates = list(temp_dir.glob("*.tif")) + list(temp_dir.glob("*.tiff"))
    if tif_candidates:
        primary_tif = tif_candidates[0]
        if output_path.exists():
            output_path.unlink()
        primary_tif.rename(output_path)
        print(f"  |  Disimpan sebagai: {output_path.name}")
        # Hapus sisa folder temp jika kosong
        for f in temp_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
        try:
            temp_dir.rmdir()
        except Exception:
            pass
    else:
        print(f"  |  [WARNING] Tidak ada file .tif yang ditemukan di {temp_dir}")

    print(f"  +-- DONE: {year}\n")


def verify_composites():
    """Verifikasi semua GeoTIFF yang ada di folder processed."""
    print(f"\n{'=' * 60}")
    print(f"VERIFIKASI HASIL")
    print(f"{'=' * 60}")

    tif_files = sorted(config.PROCESSED_DIR.glob("*.tif"))
    if not tif_files:
        print("[WARNING] Tidak ada GeoTIFF di folder processed/")
        print("          Periksa folder secara manual atau lihat log job.")
        return

    for f in tif_files:
        with rasterio.open(f) as src:
            data = src.read()
            valid = np.count_nonzero(~np.isnan(data[0]) & (data[0] != 0))
            total = data[0].size
            print(f"\n  {f.name}")
            print(f"    Ukuran : {f.stat().st_size / 1e6:.1f} MB")
            print(f"    CRS    : {src.crs}")
            print(f"    Resolusi: {src.res[0]:.1f} × {src.res[1]:.1f} m")
            print(f"    Dimensi: {src.width} × {src.height} px")
            print(f"    Bands  : {src.count} ({src.descriptions or 'B02,B03,B04,B08,B11,B12'})")
            print(f"    Piksel valid: {valid}/{total} ({100*valid/total:.1f}%)")


import time

def safe_api_call(func, *args, max_retries=5, delay=10, **kwargs):
    """Wrapper untuk memanggil API openEO dengan penanganan 429 Too Many Requests."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Too Many Requests" in err_str:
                wait_time = delay * (attempt + 1)
                print(f"  [WAIT] Terkena rate limit server (429). Menunggu {wait_time} detik...")
                time.sleep(wait_time)
            else:
                raise e
    return func(*args, **kwargs)


def wait_for_job(job, poll_interval=15, max_time=1800):
    """Menunggu batch job selesai dengan memantau status secara berkala."""
    start_time = time.time()
    while time.time() - start_time < max_time:
        try:
            status = job.status()
        except Exception as e:
            if "429" in str(e):
                time.sleep(10)
                continue
            raise e

        elapsed = int(time.time() - start_time)
        print(f"        [{elapsed}s] Status job: {status}")

        if status in ["finished", "success"]:
            print(f"  [OK] Job selesai dengan sukses!")
            return True
        elif status in ["error", "canceled"]:
            # Dapatkan log error jika ada
            try:
                logs = job.logs()
                print(f"  [LOGS] Error logs: {logs}")
            except Exception:
                pass
            raise RuntimeError(f"Job berakhir dengan status: {status}")

        time.sleep(poll_interval)
    raise TimeoutError("Waktu tunggu job melebihi batas (30 menit).")


def process_single_year(conn, extent, date_start, date_end, year, output_path, existing_job_id=None):
    """Memproses satu tahun secara sekuensial dengan penanganan rate-limit."""
    print(f"\n{'=' * 60}")
    print(f"PROSES KOMPOSIT OKTOBER {year}")
    print(f"{'=' * 60}")

    if output_path.exists():
        print(f"  [INFO] File {output_path.name} sudah ada di folder processed.")
        print(f"         Melewati proses download.")
        return

    if existing_job_id:
        print(f"  [INFO] Menggunakan job yang sedang berjalan: {existing_job_id}")
        job = conn.job(existing_job_id)
    else:
        # 1. Bangun process graph
        comp = build_composite_process(conn, extent, date_start, date_end, year)

        # 2. Buat job di server
        print(f"\n  [1/3] Membuat job komposit di server CDSE...")
        job = safe_api_call(comp.create_job, title=f"Badung_S2_Oct{year}_composite", out_format="GTiff")
        print(f"        Job ID: {job.job_id}")

        # Delay sejenak agar rate limit aman
        time.sleep(5)

        # 3. Jalankan job
        print(f"  [2/3] Menjalankan job di server...")
        safe_api_call(job.start_job)

    # Tunggu selesai
    print(f"        Sedang diproses oleh cluster CDSE...")
    wait_for_job(job)

    # Delay sejenak sebelum download
    time.sleep(5)

    # 4. Download hasil
    print(f"  [3/3] Mendownload hasil GeoTIFF...")
    temp_dir = output_path.parent / f"temp_{year}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    safe_api_call(job.download_results, target=temp_dir)

    tif_candidates = list(temp_dir.glob("*.tif")) + list(temp_dir.glob("*.tiff"))
    if tif_candidates:
        if output_path.exists():
            output_path.unlink()
        tif_candidates[0].rename(output_path)
        print(f"  [SUKSES] Tersimpan di: {output_path}")

        # Bersihkan temp
        for f in temp_dir.glob("*"):
            try:
                f.unlink()
            except Exception:
                pass
        try:
            temp_dir.rmdir()
        except Exception:
            pass
    else:
        print(f"  [WARNING] File tif tidak ditemukan di {temp_dir}")


def main():
    # 1. Koneksi
    conn = connect_cdse()

    # 2. Spatial extent
    extent = get_spatial_extent()

    # 3. Proses 2018
    process_single_year(
        conn, extent,
        config.DATE_START_2018, config.DATE_END_2018,
        2018, config.COMPOSITE_2018
    )

    # Jeda 10 detik antar tahun untuk kenyamanan rate limit
    print("\n[PAUSE] Jeda 10 detik sebelum memulai tahun berikutnya...")
    time.sleep(10)

    # 4. Proses 2026
    process_single_year(
        conn, extent,
        config.DATE_START_2026, config.DATE_END_2026,
        2026, config.COMPOSITE_2026
    )

    # 5. Verifikasi
    verify_composites()

    print("\n[SELESAI] Script 02 berhasil! Lanjut ke script 03 (hitung indeks).")


if __name__ == "__main__":
    main()
