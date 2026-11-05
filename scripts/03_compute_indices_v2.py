"""
Script 03_v2: Hitung Indeks Spektral + LSWI + Bilateral Filter + Tekstur NIR
=============================================================================
PCD Murni (Non-Machine Learning) Versi 2.0:
  - Bilateral Edge-Preserving Filter pada kanal reflektansi
  - NDVI (Biomassa Vegetasi)
  - LSWI (Land Surface Water Index / Kelembapan & Genangan Subak)
  - NDBI (Kawasan Terbangun / Material Kedap Air)
  - NDWI (Kelembapan Kanopi & Badan Air)
  - BSI  (Tanah Terbuka / Urukan Proyek)
  - Tekstur Simpangan Baku Lokal NIR (5x5 StdDev)
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

import cv2
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from scipy.ndimage import uniform_filter


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
    """
    print(f"\n  Loading: {filepath.name}")

    with rasterio.open(filepath) as src:
        data = src.read().astype(np.float32)
        meta = src.meta.copy()
        profile = src.profile.copy()
        descriptions = [d.upper() for d in src.descriptions if d] if src.descriptions else []

    band_map = BAND.copy()
    if descriptions and any(b in descriptions for b in ["B02", "B04", "B08", "B11"]):
        print(f"    Mendeteksi urutan band dari metadata: {descriptions}")
        for b_name in ["B02", "B03", "B04", "B08", "B11", "B12"]:
            if b_name in descriptions:
                band_map[b_name] = descriptions.index(b_name)

    max_val = np.nanmax(data)
    if max_val > 100:
        print(f"    Scaling: reflektansi ÷ 10000 (max raw = {max_val:.0f})")
        data = data / 10000.0

    data[data <= 0] = np.nan
    data[data > 1.5] = np.nan

    print(f"    Shape: {data.shape} (bands, rows, cols)")
    print(f"    Range: [{np.nanmin(data):.4f}, {np.nanmax(data):.4f}]")
    print(f"    Valid: {np.count_nonzero(~np.isnan(data[0]))}/{data[0].size} px")

    return data, meta, profile, band_map


def clip_to_boundary(filepath, boundary_path, output_path):
    """
    Clip raster ke batas administratif Kabupaten Badung.
    """
    if not boundary_path.exists():
        print("  [SKIP] Boundary tidak ditemukan, tidak di-clip.")
        return filepath

    gdf = gpd.read_file(boundary_path)

    with rasterio.open(filepath) as src:
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **clipped_meta) as dst:
        dst.write(clipped_float)

    print(f"  [OK] Clipped → {output_path.name}")
    return output_path


def apply_bilateral_filter(array_2d, d=5, sigma_color=0.05, sigma_space=5.0):
    """
    Menerapkan Bilateral Edge-Preserving Filter untuk meredam noise sensor
    tanpa mengaburkan tepi batas sawah / batas petak kavling vila.
    """
    mask = ~np.isnan(array_2d)
    if not np.any(mask):
        return array_2d.copy()
    
    # Isi NaN sementara dengan mean valid
    mean_val = float(np.nanmean(array_2d))
    filled = np.where(mask, array_2d, mean_val).astype(np.float32)
    
    # Bilateral filter OpenCV pada citra float32
    filtered = cv2.bilateralFilter(filled, d=d, sigmaColor=sigma_color, sigmaSpace=sigma_space)
    filtered[~mask] = np.nan
    return filtered


def compute_local_std(array_2d, window_size=5):
    """
    Menghitung Local Standard Deviation (sigma) menggunakan sliding window WxW.
    Rumus: sigma = sqrt( E[X^2] - (E[X])^2 )
    """
    valid_mask = ~np.isnan(array_2d)
    filled = np.where(valid_mask, array_2d, 0.0)

    mean = uniform_filter(filled, size=window_size, mode="reflect")
    mean_sq = uniform_filter(filled**2, size=window_size, mode="reflect")

    weight = uniform_filter(valid_mask.astype(np.float32), size=window_size, mode="reflect")
    weight = np.where(weight > 0, weight, np.nan)

    mean = mean / weight
    mean_sq = mean_sq / weight

    variance = mean_sq - mean**2
    variance = np.where(variance > 0, variance, 0.0)
    local_std = np.sqrt(variance)
    local_std[~valid_mask] = np.nan
    return local_std


def normalized_difference(a, b):
    """Hitung (a - b) / (a + b) dengan safe division."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = (a - b) / (a + b)
    result[~np.isfinite(result)] = np.nan
    return result


def compute_indices_v2(data, band_map=None, use_bilateral=True):
    """
    Hitung semua indeks spektral v2 dari array komposit multi-band:
    NDVI, LSWI, NDBI, NDWI, BSI.
    """
    bm = band_map or BAND
    blue = data[bm["B02"]]
    green = data[bm["B03"]]
    red = data[bm["B04"]]
    nir = data[bm["B08"]]
    swir1 = data[bm["B11"]]

    if use_bilateral:
        print("    Menerapkan Bilateral Filter (d=5, sigmaColor=0.05, sigmaSpace=5.0)...")
        blue = apply_bilateral_filter(blue, config.BILATERAL_D, config.BILATERAL_SIGMA_COLOR, config.BILATERAL_SIGMA_SPACE)
        green = apply_bilateral_filter(green, config.BILATERAL_D, config.BILATERAL_SIGMA_COLOR, config.BILATERAL_SIGMA_SPACE)
        red = apply_bilateral_filter(red, config.BILATERAL_D, config.BILATERAL_SIGMA_COLOR, config.BILATERAL_SIGMA_SPACE)
        nir = apply_bilateral_filter(nir, config.BILATERAL_D, config.BILATERAL_SIGMA_COLOR, config.BILATERAL_SIGMA_SPACE)
        swir1 = apply_bilateral_filter(swir1, config.BILATERAL_D, config.BILATERAL_SIGMA_COLOR, config.BILATERAL_SIGMA_SPACE)

    indices = {}
    # NDVI = (NIR - Red) / (NIR + Red)
    indices["ndvi"] = normalized_difference(nir, red)

    # LSWI = (NIR - SWIR1) / (NIR + SWIR1)
    indices["lswi"] = normalized_difference(nir, swir1)

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

    return indices, nir


def save_single_band(array_2d, meta, filepath, name=""):
    """Simpan 2D array sebagai single-band GeoTIFF."""
    out_meta = meta.copy()
    out_meta.update({
        "count": 1,
        "dtype": "float32",
        "nodata": np.nan,
    })

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(filepath, "w", **out_meta) as dst:
        dst.write(array_2d.astype(np.float32), 1)

    print(f"    Saved: {filepath.name} ({name})")


def plot_comparison(arr_2018, arr_2026, name, title, cmap, norm_center=None, vmin=None, vmax=None):
    """Plot perbandingan 2018 vs 2026 + delta."""
    delta = arr_2026 - arr_2018

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    if vmin is None:
        vmin = max(np.nanpercentile(arr_2018, 2), np.nanpercentile(arr_2026, 2))
    if vmax is None:
        vmax = min(np.nanpercentile(arr_2018, 98), np.nanpercentile(arr_2026, 98))

    norm = None
    if norm_center is not None and vmin < norm_center < vmax:
        norm = TwoSlopeNorm(vmin=vmin, vcenter=norm_center, vmax=vmax)

    im0 = axes[0].imshow(arr_2018, cmap=cmap, vmin=vmin if not norm else None,
                         vmax=vmax if not norm else None, norm=norm)
    axes[0].set_title(f"{title} - Okt 2018\n(mean = {np.nanmean(arr_2018):+.3f})", fontsize=11)
    axes[0].axis("off")
    plt.colorbar(im0, ax=axes[0], shrink=0.7)

    im1 = axes[1].imshow(arr_2026, cmap=cmap, vmin=vmin if not norm else None,
                         vmax=vmax if not norm else None, norm=norm)
    axes[1].set_title(f"{title} - Okt 2026\n(mean = {np.nanmean(arr_2026):+.3f})", fontsize=11)
    axes[1].axis("off")
    plt.colorbar(im1, ax=axes[1], shrink=0.7)

    d_max = max(abs(np.nanpercentile(delta, 2)), abs(np.nanpercentile(delta, 98)))
    im2 = axes[2].imshow(delta, cmap="RdBu_r", vmin=-d_max, vmax=d_max)
    axes[2].set_title(f"Delta (2026 - 2018)\n(mean = {np.nanmean(delta):+.3f})", fontsize=11)
    axes[2].axis("off")
    plt.colorbar(im2, ax=axes[2], shrink=0.7)

    plt.suptitle(f"Perbandingan Multitemporal {title} - Kabupaten Badung", fontsize=14, y=1.02)
    plt.tight_layout()

    out_file = config.OUTPUT_MAPS / f"comparison_{name}.png"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_file, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot disimpan: {out_file.name}")


def main():
    print("=" * 70)
    print("Script 03_v2: Hitung Indeks Spektral (Bilateral, LSWI, Tekstur NIR)")
    print("=" * 70)

    # 1. Pastikan boundary ada
    if not config.BOUNDARY_FILE.exists():
        print(f"\n[ERROR] File boundary tidak ditemukan: {config.BOUNDARY_FILE}")
        sys.exit(1)

    # 2. Clip komposit 2018 & 2026 ke boundary Badung
    print("\n--- TAHAP 1: Clip Komposit ke Boundary Badung ---")
    clipped_2018 = config.PROCESSED_DIR / "composite_2018_oct_clipped.tif"
    clipped_2026 = config.PROCESSED_DIR / "composite_2026_oct_clipped.tif"

    clip_to_boundary(config.COMPOSITE_2018, config.BOUNDARY_FILE, clipped_2018)
    clip_to_boundary(config.COMPOSITE_2026, config.BOUNDARY_FILE, clipped_2026)

    # 3. Load clipped composites
    print("\n--- TAHAP 2: Load Komposit & Terapkan Bilateral Filter ---")
    data_2018, meta_2018, _, band_map_2018 = load_composite(clipped_2018)
    data_2026, meta_2026, _, band_map_2026 = load_composite(clipped_2026)

    # 4. Hitung indeks spektral v2
    print("\n--- TAHAP 3: Hitung Indeks Spektral (NDVI, LSWI, NDBI, NDWI, BSI) ---")
    print("\n[2018]")
    indices_2018, nir_2018 = compute_indices_v2(data_2018, band_map_2018, use_bilateral=True)
    print("\n[2026]")
    indices_2026, nir_2026 = compute_indices_v2(data_2026, band_map_2026, use_bilateral=True)

    # 5. Hitung filter tekstur simpangan baku lokal NIR (5x5)
    print("\n--- TAHAP 4: Hitung Tekstur Spasial NIR (5x5 Local StdDev) ---")
    texture_nir_2018 = compute_local_std(nir_2018, window_size=config.TEXTURE_WINDOW_SIZE)
    texture_nir_2026 = compute_local_std(nir_2026, window_size=config.TEXTURE_WINDOW_SIZE)
    print(f"  Tekstur NIR 2018: mean={np.nanmean(texture_nir_2018):.4f}, "
          f"p10={np.nanpercentile(texture_nir_2018, 10):.4f}, "
          f"p90={np.nanpercentile(texture_nir_2018, 90):.4f}")

    # 6. Simpan single-band GeoTIFF
    print("\n--- TAHAP 5: Simpan GeoTIFF Indeks Spektral & Tekstur ---")
    config.INDICES_DIR.mkdir(parents=True, exist_ok=True)

    pairs = [
        ("ndvi", indices_2018["ndvi"], config.NDVI_2018, indices_2026["ndvi"], config.NDVI_2026),
        ("lswi", indices_2018["lswi"], config.LSWI_2018, indices_2026["lswi"], config.LSWI_2026),
        ("ndbi", indices_2018["ndbi"], config.NDBI_2018, indices_2026["ndbi"], config.NDBI_2026),
        ("ndwi", indices_2018["ndwi"], config.NDWI_2018, indices_2026["ndwi"], config.NDWI_2026),
        ("bsi",  indices_2018["bsi"],  config.BSI_2018,  indices_2026["bsi"],  config.BSI_2026),
    ]

    for name, arr18, path18, arr26, path26 in pairs:
        save_single_band(arr18, meta_2018, path18, f"{name.upper()} 2018")
        save_single_band(arr26, meta_2026, path26, f"{name.upper()} 2026")

    save_single_band(texture_nir_2018, meta_2018, config.TEXTURE_NIR_2018, "Tekstur NIR 2018")
    save_single_band(texture_nir_2026, meta_2026, config.TEXTURE_NIR_2026, "Tekstur NIR 2026")

    # 7. Generate comparison plots
    print("\n--- TAHAP 6: Buat Plot Perbandingan Spektral ---")
    plot_comparison(indices_2018["ndvi"], indices_2026["ndvi"], "ndvi", "NDVI", "YlGn", norm_center=0.3)
    plot_comparison(indices_2018["lswi"], indices_2026["lswi"], "lswi", "LSWI (Kelembapan/Subak)", "Blues", norm_center=0.0)
    plot_comparison(indices_2018["ndbi"], indices_2026["ndbi"], "ndbi", "NDBI", "YlOrRd", norm_center=0.0)
    plot_comparison(indices_2018["ndwi"], indices_2026["ndwi"], "ndwi", "NDWI", "PuBu", norm_center=0.0)
    plot_comparison(indices_2018["bsi"],  indices_2026["bsi"],  "bsi",  "BSI",  "YlOrBr", norm_center=0.0)

    # Plot tekstur komparasi
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    im1 = axes[0].imshow(texture_nir_2018, cmap="magma", vmin=0, vmax=0.10)
    axes[0].set_title("Tekstur Simpangan Baku NIR 2018 (5x5)\n(Sawah Homogen < 0.045 vs Kanopi Kasar)", fontsize=11)
    axes[0].axis("off")
    plt.colorbar(im1, ax=axes[0], shrink=0.7)

    im2 = axes[1].imshow(texture_nir_2026, cmap="magma", vmin=0, vmax=0.10)
    axes[1].set_title("Tekstur Simpangan Baku NIR 2026 (5x5)", fontsize=11)
    axes[1].axis("off")
    plt.colorbar(im2, ax=axes[1], shrink=0.7)
    plt.suptitle("Analisis Tekstur Simpangan Baku NIR - Kabupaten Badung", fontsize=13)
    plt.tight_layout()
    tex_path = config.OUTPUT_MAPS / "comparison_texture.png"
    fig.savefig(tex_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot tekstur disimpan: {tex_path.name}")

    print("\n[SELESAI] Script 03_v2 selesai! Semua indeks dan filter tekstur tersimpan.")


if __name__ == "__main__":
    main()
