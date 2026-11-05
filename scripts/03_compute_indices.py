"""
Script 03: Hitung Indeks Spektral + Clip ke Boundary
=====================================================
Membaca komposit GeoTIFF (dari script 02) dan menghitung:
  - NDVI: vegetasi
  - NDBI: kawasan terbangun
  - NDWI: air
  - BSI:  tanah terbuka

Semua operasi menggunakan numpy (cepat, lokal).

Band order dalam komposit dari OpenEO:
  Band 1 = B02 (Blue,  10m)
  Band 2 = B03 (Green, 10m)
  Band 3 = B04 (Red,   10m)
  Band 4 = B08 (NIR,   10m)
  Band 5 = B11 (SWIR1, 20m → resampled 10m)
  Band 6 = B12 (SWIR2, 20m → resampled 10m)

Cara pakai:
    python scripts/03_compute_indices.py
"""

import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from scipy.ndimage import uniform_filter


# ========================================================================
# BAND INDEX MAPPING (sesuai urutan output OpenEO)
# ========================================================================
# OpenEO mengeluarkan band sesuai urutan yang kita minta:
# B02, B03, B04, B08, B11, B12
BAND = {
    "B02": 0,  # Blue
    "B03": 1,  # Green
    "B04": 2,  # Red
    "B08": 3,  # NIR
    "B11": 4,  # SWIR-1
    "B12": 5,  # SWIR-2
}


def load_composite(filepath):
    """
    Baca komposit GeoTIFF dan kembalikan sebagai float32 array + metadata + band mapping.
    Sentinel-2 L2A menyimpan reflektansi sebagai integer (×10000).
    """
    print(f"\n  Loading: {filepath.name}")

    with rasterio.open(filepath) as src:
        data = src.read().astype(np.float32)
        meta = src.meta.copy()
        profile = src.profile.copy()
        descriptions = [d.upper() for d in src.descriptions if d] if src.descriptions else []

    # Dynamic band mapping jika deskripsi tersedia
    band_map = BAND.copy()
    if descriptions and any(b in descriptions for b in ["B02", "B04", "B08", "B11"]):
        print(f"    Mendeteksi urutan band dari metadata: {descriptions}")
        for b_name in ["B02", "B03", "B04", "B08", "B11", "B12"]:
            if b_name in descriptions:
                band_map[b_name] = descriptions.index(b_name)

    # Cek apakah nilai perlu di-scale (S2 L2A: reflektansi × 10000)
    max_val = np.nanmax(data)
    if max_val > 100:
        print(f"    Scaling: reflektansi ÷ 10000 (max raw = {max_val:.0f})")
        data = data / 10000.0

    # Mask NoData / invalid
    data[data <= 0] = np.nan
    data[data > 1.5] = np.nan  # reflektansi > 1.5 tidak valid

    print(f"    Shape: {data.shape} (bands, rows, cols)")
    print(f"    Range: [{np.nanmin(data):.4f}, {np.nanmax(data):.4f}]")
    print(f"    Valid: {np.count_nonzero(~np.isnan(data[0]))}/{data[0].size} px")

    return data, meta, profile, band_map


def clip_to_boundary(filepath, boundary_path, output_path):
    """
    Clip raster ke batas administratif Kabupaten Badung.
    Menghapus piksel di luar boundary.
    """
    if not boundary_path.exists():
        print(f"  [SKIP] Boundary tidak ditemukan, tidak di-clip.")
        return filepath

    gdf = gpd.read_file(boundary_path)

    with rasterio.open(filepath) as src:
        # Reproject boundary ke CRS raster jika berbeda
        if gdf.crs != src.crs:
            gdf = gdf.to_crs(src.crs)

        geometries = gdf.geometry.values
        nodata_val = src.nodata if src.nodata is not None else 0
        clipped, clipped_transform = rio_mask(
            src, geometries, crop=True, nodata=nodata_val, filled=True
        )
        clipped_float = clipped.astype(np.float32)
        clipped_float[clipped == nodata_val] = np.nan

        clipped_meta = src.meta.copy()
        clipped_meta.update({
            "height": clipped.shape[1],
            "width": clipped.shape[2],
            "transform": clipped_transform,
            "dtype": "float32",
            "nodata": np.nan,
        })

    # Simpan hasil clip
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **clipped_meta) as dst:
        dst.write(clipped_float)

    print(f"  [OK] Clipped → {output_path.name}")
    return output_path


def compute_local_std(array_2d, window_size=5):
    """
    Menghitung Local Standard Deviation (sigma) menggunakan sliding window WxW.
    Rumus: sigma = sqrt( E[X^2] - (E[X])^2 )
    Digunakan untuk membedakan hamparan sawah (tekstur halus, sigma kecil)
    dengan kanopi pepohonan/hutan (tekstur kasar, sigma besar).
    """
    valid_mask = ~np.isnan(array_2d)
    filled = np.where(valid_mask, array_2d, 0.0)

    mean = uniform_filter(filled, size=window_size, mode="reflect")
    mean_sq = uniform_filter(filled**2, size=window_size, mode="reflect")

    # Normalisasi bobot untuk piksel tepi/NaN
    weight = uniform_filter(valid_mask.astype(np.float32), size=window_size, mode="reflect")
    weight = np.where(weight > 0, weight, np.nan)

    mean = mean / weight
    mean_sq = mean_sq / weight

    variance = mean_sq - mean**2
    variance = np.where(variance > 0, variance, 0.0)
    local_std = np.sqrt(variance)
    local_std[~valid_mask] = np.nan
    return local_std


def plot_texture_comparison(nir_data, texture_data, output_dir):
    """Buat grafik analisis tekstur spasial NIR 2018."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # 1. Band NIR
    im1 = axes[0].imshow(nir_data, cmap="viridis", vmin=0.05, vmax=0.6)
    axes[0].set_title("Sentinel-2 Band NIR (B08) - 2018", fontsize=12)
    axes[0].axis("off")
    plt.colorbar(im1, ax=axes[0], shrink=0.7, label="Reflektansi NIR")

    # 2. Local Standard Deviation
    vmax_t = np.nanpercentile(texture_data, 98)
    im2 = axes[1].imshow(texture_data, cmap="magma", vmin=0, vmax=vmax_t)
    axes[1].set_title(f"Tekstur Lokal (Local Std Dev 5x5)\nHomogen (Sawah) vs Kasar (Pohon)", fontsize=12)
    axes[1].axis("off")
    plt.colorbar(im2, ax=axes[1], shrink=0.7, label="σ NIR")

    # 3. Mask Homogen (Calon Sawah) vs Kasar (Pohon)
    sawah_texture_mask = texture_data < config.TH_SIGMA_NIR
    sawah_vis = np.zeros((*texture_data.shape, 3), dtype=np.uint8)
    # Area sawah halus = hijau
    sawah_vis[sawah_texture_mask & ~np.isnan(texture_data)] = [46, 204, 113]
    # Area kasar pohon = cokelat gelap
    sawah_vis[~sawah_texture_mask & ~np.isnan(texture_data)] = [160, 64, 0]

    axes[2].imshow(sawah_vis)
    axes[2].set_title(f"Klasifikasi Tekstur (Ambang σ < {config.TH_SIGMA_NIR})\nHijau: Sawah Rata | Cokelat: Kanopi Kasar", fontsize=12)
    axes[2].axis("off")

    plt.suptitle("Analisis Tekstur Spasial NIR (Pemisahan Sawah vs Kanopi Pohon) - Kabupaten Badung", fontsize=14, y=1.02)
    plt.tight_layout()

    out_file = output_dir / "comparison_texture.png"
    fig.savefig(out_file, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot tekstur disimpan: {out_file.name}")


def normalized_difference(a, b):
    """Hitung (a - b) / (a + b) dengan handling division by zero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = (a - b) / (a + b)
    result[~np.isfinite(result)] = np.nan
    return result


def compute_indices(data, band_map=None):
    """
    Hitung semua indeks spektral dari array komposit multi-band.

    Returns dict of {nama_indeks: array_2d}
    """
    bm = band_map or BAND
    blue = data[bm["B02"]]
    green = data[bm["B03"]]
    red = data[bm["B04"]]
    nir = data[bm["B08"]]
    swir1 = data[bm["B11"]]

    indices = {}

    # NDVI = (NIR - Red) / (NIR + Red)
    indices["ndvi"] = normalized_difference(nir, red)

    # NDBI = (SWIR1 - NIR) / (SWIR1 + NIR)
    indices["ndbi"] = normalized_difference(swir1, nir)

    # NDWI = (Green - NIR) / (Green + NIR)
    indices["ndwi"] = normalized_difference(green, nir)

    # BSI = ((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))
    indices["bsi"] = normalized_difference(swir1 + red, nir + blue)

    for name, arr in indices.items():
        valid = np.count_nonzero(~np.isnan(arr))
        print(f"    {name.upper():5s}: mean={np.nanmean(arr):+.4f}  "
              f"std={np.nanstd(arr):.4f}  "
              f"range=[{np.nanmin(arr):.4f}, {np.nanmax(arr):.4f}]  "
              f"valid={valid}")

    return indices


def save_index(index_array, reference_filepath, output_path, name):
    """Simpan satu indeks sebagai GeoTIFF 1-band."""
    with rasterio.open(reference_filepath) as src:
        meta = src.meta.copy()

    meta.update({
        "count": 1,
        "dtype": "float32",
        "nodata": np.nan,
    })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **meta) as dst:
        dst.write(index_array.astype(np.float32), 1)
        dst.set_band_description(1, name.upper())

    size_mb = output_path.stat().st_size / 1e6
    print(f"    Saved: {output_path.name} ({size_mb:.1f} MB)")


def plot_indices(indices_2018, indices_2026, output_dir):
    """Buat plot perbandingan indeks 2018 vs 2026."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in ["ndvi", "ndbi", "ndwi", "bsi"]:
        fig, axes = plt.subplots(1, 3, figsize=(18, 6))

        # Tentukan range warna
        vmin = min(np.nanpercentile(indices_2018[name], 2),
                   np.nanpercentile(indices_2026[name], 2))
        vmax = max(np.nanpercentile(indices_2018[name], 98),
                   np.nanpercentile(indices_2026[name], 98))

        # Plot 2018
        im1 = axes[0].imshow(indices_2018[name], vmin=vmin, vmax=vmax, cmap="RdYlGn")
        axes[0].set_title(f"{name.upper()} — Oktober 2018")
        axes[0].axis("off")
        plt.colorbar(im1, ax=axes[0], shrink=0.7)

        # Plot 2026
        im2 = axes[1].imshow(indices_2026[name], vmin=vmin, vmax=vmax, cmap="RdYlGn")
        axes[1].set_title(f"{name.upper()} — Oktober 2026")
        axes[1].axis("off")
        plt.colorbar(im2, ax=axes[1], shrink=0.7)

        # Plot selisih (2026 - 2018)
        diff = indices_2026[name] - indices_2018[name]
        d_abs = max(abs(np.nanpercentile(diff, 2)), abs(np.nanpercentile(diff, 98)))
        im3 = axes[2].imshow(diff, vmin=-d_abs, vmax=d_abs, cmap="RdBu_r")
        axes[2].set_title(f"Δ{name.upper()} (2026 − 2018)")
        axes[2].axis("off")
        plt.colorbar(im3, ax=axes[2], shrink=0.7)

        plt.suptitle(f"Perbandingan {name.upper()} — Kabupaten Badung", fontsize=14, y=1.02)
        plt.tight_layout()

        path = output_dir / f"comparison_{name}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  Plot: {path.name}")


def print_statistics_table(indices_2018, indices_2026):
    """Cetak tabel statistik perbandingan kedua tahun."""
    print(f"\n{'=' * 75}")
    print(f"{'STATISTIK PERBANDINGAN INDEKS SPEKTRAL':^75}")
    print(f"{'=' * 75}")
    print(f"{'Indeks':<8} {'Stat':<8} {'2018':>10} {'2026':>10} {'Δ':>10}")
    print(f"{'─' * 75}")

    for name in ["ndvi", "ndbi", "ndwi", "bsi"]:
        a = indices_2018[name]
        b = indices_2026[name]
        for stat_name, func in [
            ("Mean", np.nanmean), ("Median", np.nanmedian),
            ("Std", np.nanstd), ("P25", lambda x: np.nanpercentile(x, 25)),
            ("P75", lambda x: np.nanpercentile(x, 75)),
        ]:
            va, vb = func(a), func(b)
            print(f"{name.upper() if stat_name == 'Mean' else '':<8} "
                  f"{stat_name:<8} {va:>+10.4f} {vb:>+10.4f} {vb - va:>+10.4f}")
        print(f"{'─' * 75}")


def process_year(composite_path, boundary_path, year):
    """Pipeline lengkap untuk satu tahun: load → clip → indices."""
    print(f"\n{'=' * 60}")
    print(f"  PROSES INDEKS SPEKTRAL — OKTOBER {year}")
    print(f"{'=' * 60}")

    # 1. Load komposit
    data, meta, profile, band_map = load_composite(composite_path)

    # 2. Clip ke boundary (opsional, sudah di-clip oleh bbox di OpenEO)
    clipped_path = config.PROCESSED_DIR / f"composite_{year}_oct_clipped.tif"
    if boundary_path.exists():
        print(f"\n  Clipping ke batas Kabupaten Badung...")
        clip_to_boundary(composite_path, boundary_path, clipped_path)
        # Reload clipped data
        data, meta, profile, band_map = load_composite(clipped_path)
        ref_path = clipped_path
    else:
        ref_path = composite_path

    # 3. Hitung indeks
    print(f"\n  Menghitung indeks spektral...")
    indices = compute_indices(data, band_map)

    # 4. Simpan setiap indeks sebagai GeoTIFF
    print(f"\n  Menyimpan GeoTIFF indeks...")
    index_paths = {
        "ndvi": getattr(config, f"NDVI_{year}"),
        "ndbi": getattr(config, f"NDBI_{year}"),
        "ndwi": getattr(config, f"NDWI_{year}"),
        "bsi": getattr(config, f"BSI_{year}"),
    }
    for name, path in index_paths.items():
        save_index(indices[name], ref_path, path, name)

    # 5. Fitur Tekstur Spasial NIR (Khusus Tahun 2018 untuk pemurnian sawah)
    if year == 2018:
        print(f"\n  Menghitung Tekstur Spasial NIR (Local Std Dev {config.TEXTURE_WINDOW_SIZE}x{config.TEXTURE_WINDOW_SIZE})...")
        nir_band = data[band_map["B08"]]
        texture_nir = compute_local_std(nir_band, window_size=config.TEXTURE_WINDOW_SIZE)
        save_index(texture_nir, ref_path, config.TEXTURE_NIR_2018, "TEXTURE_NIR")
        plot_texture_comparison(nir_band, texture_nir, config.OUTPUT_MAPS)

    return indices


def main():
    print("=" * 60)
    print("Script 03: Hitung Indeks Spektral")
    print("=" * 60)

    # Cek ketersediaan komposit
    for label, path in [("2018", config.COMPOSITE_2018), ("2026", config.COMPOSITE_2026)]:
        if not path.exists():
            # Cari file tif apapun di folder processed
            tifs = sorted(config.PROCESSED_DIR.glob("*.tif"))
            if tifs:
                print(f"[INFO] {path.name} tidak ditemukan, tapi ada: {[t.name for t in tifs]}")
                print(f"       Silakan rename file sesuai atau update config.py")
            else:
                print(f"[ERROR] Komposit {label} tidak ditemukan: {path}")
                print(f"        Jalankan script 02 terlebih dahulu.")
            sys.exit(1)

    # Proses kedua tahun
    indices_2018 = process_year(config.COMPOSITE_2018, config.BOUNDARY_FILE, 2018)
    indices_2026 = process_year(config.COMPOSITE_2026, config.BOUNDARY_FILE, 2026)

    # Statistik perbandingan
    print_statistics_table(indices_2018, indices_2026)

    # Plot perbandingan
    print(f"\n  Membuat plot perbandingan...")
    plot_indices(indices_2018, indices_2026, config.OUTPUT_MAPS)

    print(f"\n[SELESAI] Semua indeks tersimpan di: {config.INDICES_DIR}")
    print(f"          Plot tersimpan di: {config.OUTPUT_MAPS}")
    print(f"          Lanjut ke script 04 (thresholding & morfologi).")


if __name__ == "__main__":
    main()
