"""
Script 04: Multi-Rule Thresholding, Tekstur NIR, Morfologi, dan Transisi 2-Kelas
================================================================================
Upgrade v2.0:
  1. Pemurnian Sawah 2018 menggunakan NDVI > 0.35 + Tekstur NIR (sigma < 0.045)
     untuk mengeliminasi kanopi pohon kasar / hutan.
  2. Klasifikasi Transisi 2-Kelas (PCD Murni):
     - Kelas 1: Bangunan Permanen (NDBI2026 > 0.10, Delta NDBI > 0.08)
     - Kelas 2: Lahan Konstruksi / Urukan Baru (BSI2026 > 0.08, Delta BSI > 0.10)
  3. Operasi Morfologi Adaptif + Connected Component Area Filtering (buang blob < 10 px).
  4. Penyimpanan GeoTIFF multi-kelas dan tabel parameter sweep.

Cara pakai:
    python scripts/04_threshold_morphology.py
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
from scipy import ndimage
import cv2
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import csv


# ========================================================================
# UTILITAS
# ========================================================================

def load_index(filepath):
    """Baca GeoTIFF indeks 1-band."""
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        res_x, res_y = src.res  # resolusi dalam meter (jika UTM)
    return data, meta, res_x, res_y


def pixel_area_m2(res_x, res_y):
    """Luas satu piksel dalam m²."""
    return abs(res_x) * abs(res_y)


def mask_area_km2(mask, res_x, res_y):
    """Hitung luas total piksel True dalam km²."""
    count = np.count_nonzero(mask)
    area_m2 = count * pixel_area_m2(res_x, res_y)
    return area_m2 / 1e6


def mask_area_ha(mask, res_x, res_y):
    """Hitung luas total piksel True dalam hektare."""
    return mask_area_km2(mask, res_x, res_y) * 100


def get_kernel(size, shape="square"):
    """Buat kernel untuk operasi morfologi."""
    if shape == "cross":
        kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (size, size))
    else:  # square
        kernel = np.ones((size, size), dtype=np.uint8)
    return kernel


def morphological_opening(binary_mask, kernel):
    """Opening = erosion lalu dilation. Menghapus noise kecil."""
    return cv2.morphologyEx(binary_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)


def morphological_closing(binary_mask, kernel):
    """Closing = dilation lalu erosion. Menutup lubang kecil."""
    return cv2.morphologyEx(binary_mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)


def filter_connected_components(binary_mask, min_size_pixels=10):
    """
    Menghilangkan komponen terhubung (blobs) yang ukurannya lebih kecil
    dari min_size_pixels (10 px = 0.10 Ha).
    """
    uint8_mask = binary_mask.astype(np.uint8)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        uint8_mask, connectivity=8
    )
    filtered = np.zeros_like(uint8_mask)
    for label in range(1, num_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        if area >= min_size_pixels:
            filtered[labels == label] = 1
    return filtered.astype(bool)


def save_mask(mask, reference_path, output_path, description="", dtype="uint8", nodata=255):
    """Simpan raster mask sebagai GeoTIFF."""
    with rasterio.open(reference_path) as src:
        meta = src.meta.copy()

    meta.update({"count": 1, "dtype": dtype, "nodata": nodata})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **meta) as dst:
        dst.write(mask.astype(getattr(np, dtype)), 1)
        if description:
            dst.set_band_description(1, description)

    print(f"    Saved: {output_path.name}")


# ========================================================================
# TAHAP 1: DETEKSI TRANSISI MULTI-KELAS (UPGRADE v2.0)
# ========================================================================

def detect_multiclass_transition(
    ndvi_2018, ndvi_2026,
    ndbi_2018, ndbi_2026,
    ndwi_2018, ndwi_2026,
    bsi_2018, bsi_2026,
    texture_nir_2018,
    res_x, res_y
):
    """
    Deteksi transisi multi-kelas (PCD Murni v2.0):
      1. Pemurnian Sawah 2018:
         NDVI > 0.35 & Texture_NIR < 0.045 & NDWI > -0.55
      2. Kelas 1 (Bangunan Permanen):
         NDVI2026 <= 0.30 & NDBI2026 > 0.10 & Delta NDBI > 0.08 & NDWI2026 <= 0
      3. Kelas 2 (Lahan Konstruksi / Urukan Baru):
         NDVI2026 <= 0.25 & BSI2026 > 0.08 & Delta BSI > 0.10 & bukan Kelas 1
    """
    print(f"\n{'=' * 70}")
    print(f"{'DETEKSI TRANSISI MULTI-KELAS (UPGRADE v2.0)':^70}")
    print(f"{'=' * 70}")

    # Common valid area
    common_valid = (
        ~np.isnan(ndvi_2018) & ~np.isnan(ndvi_2026)
        & ~np.isnan(ndbi_2018) & ~np.isnan(ndbi_2026)
        & ~np.isnan(ndwi_2018) & ~np.isnan(ndwi_2026)
        & ~np.isnan(bsi_2018) & ~np.isnan(bsi_2026)
        & ~np.isnan(texture_nir_2018)
    )
    print(f"  [0] Common Valid Area: {mask_area_km2(common_valid, res_x, res_y):.2f} km²")

    # 1. Pemurnian Lahan Sawah 2018
    # NDVI > 0.35 + Tekstur NIR < 0.045 (eliminasi pohon kasar) + NDWI > -0.55
    cond_veg = ndvi_2018 > config.TH_NDVI_SAWAH
    cond_texture = texture_nir_2018 < config.TH_SIGMA_NIR
    cond_not_arid = ndwi_2018 > config.TH_NDWI_SAWAH

    mask_sawah_2018 = common_valid & cond_veg & cond_texture & cond_not_arid
    area_sawah = mask_area_ha(mask_sawah_2018, res_x, res_y)
    area_all_veg = mask_area_ha(common_valid & cond_veg, res_x, res_y)
    print(f"\n  [1] Lahan Sawah Terverifikasi 2018:")
    print(f"      - Total Vegetasi Hijau (NDVI > {config.TH_NDVI_SAWAH}): {area_all_veg:.1f} ha")
    print(f"      - Sawah Murni Homogen (setelah filter tekstur σ < {config.TH_SIGMA_NIR}): {area_sawah:.1f} ha")
    print(f"      - Hutan/Pohon Kasar Tereliminasi: {area_all_veg - area_sawah:.1f} ha ({100*(area_all_veg - area_sawah)/max(area_all_veg,1):.1f}%)")

    # 2. Kelas 1: Bangunan Permanen
    delta_ndbi = ndbi_2026 - ndbi_2018
    mask_bangunan_raw = (
        mask_sawah_2018
        & (ndvi_2026 <= config.TH_NDVI_BUILT_2026)
        & (ndbi_2026 > config.TH_NDBI_BUILT_2026)
        & (delta_ndbi > config.TH_DELTA_NDBI)
        & (ndwi_2026 <= config.NDWI_WATER_THRESHOLD)
    )
    print(f"\n  [2] Kelas 1 (Bangunan Permanen - Mentah): {mask_area_ha(mask_bangunan_raw, res_x, res_y):.2f} ha")

    # 3. Kelas 2: Lahan Konstruksi / Urukan Baru
    delta_bsi = bsi_2026 - bsi_2018
    mask_konstruksi_raw = (
        mask_sawah_2018
        & (~mask_bangunan_raw)
        & (ndvi_2026 <= config.TH_NDVI_BARE_2026)
        & (bsi_2026 > config.TH_BSI_2026)
        & (delta_bsi > config.TH_DELTA_BSI)
    )
    print(f"  [3] Kelas 2 (Lahan Konstruksi / Urukan - Mentah): {mask_area_ha(mask_konstruksi_raw, res_x, res_y):.2f} ha")

    # Total Mentah
    total_raw = mask_bangunan_raw | mask_konstruksi_raw
    print(f"  ► Total Alih Fungsi Mentah: {mask_area_ha(total_raw, res_x, res_y):.2f} ha")

    return mask_sawah_2018, mask_bangunan_raw, mask_konstruksi_raw, total_raw


# ========================================================================
# TAHAP 2: PIPELINE MORFOLOGI & CONNECTED COMPONENTS
# ========================================================================

def apply_enhanced_morphology(binary_mask, kernel_size, min_cluster_px, res_x, res_y, name=""):
    """
    Penyempurnaan Morfologi 3 Langkah:
      1. Opening (3x3 Persegi): Hapus noise garis/pematang tipis
      2. Connected Components Area Filter: Buang poligon terisolasi < min_cluster_px
      3. Closing (3x3 Persegi): Satukan klaster atap/bangunan berdekatan
    """
    kernel = get_kernel(kernel_size, "square")

    # Langkah 1: Opening
    step1_open = morphological_opening(binary_mask, kernel)

    # Langkah 2: Connected Component Area Filter (min 10 piksel / 0.1 ha)
    step2_filtered = filter_connected_components(step1_open, min_size_pixels=min_cluster_px)

    # Langkah 3: Closing
    step3_closed = morphological_closing(step2_filtered, kernel)

    area_raw = mask_area_ha(binary_mask, res_x, res_y)
    area_final = mask_area_ha(step3_closed, res_x, res_y)
    red = 100 * (area_final - area_raw) / max(area_raw, 1e-9)

    print(f"  Morfologi [{name}]: Raw={area_raw:.2f} ha -> Final={area_final:.2f} ha (Reduksi: {red:+.1f}%)")

    return step3_closed


# ========================================================================
# TAHAP 3: PARAMETER SWEEP
# ========================================================================

def run_parameter_sweep(ndvi_2018, ndvi_2026, ndbi_2018, ndbi_2026,
                        ndwi_2018, ndwi_2026, bsi_2018, bsi_2026,
                        texture_nir_2018, res_x, res_y):
    """Uji sensitivitas ambang batas dan kernel morfologi."""
    print(f"\n{'=' * 70}")
    print(f"{'PARAMETER SWEEP (SENSITIVITAS v2.0)':^70}")
    print(f"{'=' * 70}")

    rows = []
    print(f"  {'NDVI_t':>7} {'NDBI_t':>7} {'Raw(ha)':>10} {'Square_3(ha)':>12} {'Cross_3(ha)':>12} {'Square_5(ha)':>12}")
    print(f"  {'─' * 68}")

    k_sq3 = get_kernel(3, "square")
    k_cr3 = get_kernel(3, "cross")
    k_sq5 = get_kernel(5, "square")

    for ndvi_t in [0.30, 0.35, 0.40]:
        for ndbi_t in [0.08, 0.10, 0.12]:
            cond_sawah = (
                (ndvi_2018 > ndvi_t)
                & (texture_nir_2018 < config.TH_SIGMA_NIR)
                & (ndwi_2018 > config.TH_NDWI_SAWAH)
            )
            cand = (
                cond_sawah
                & (ndvi_2026 <= 0.30)
                & (ndbi_2026 > ndbi_t)
                & ((ndbi_2026 - ndbi_2018) > 0.05)
                & (ndwi_2026 <= 0)
            )

            raw_ha = mask_area_ha(cand, res_x, res_y)
            sq3_ha = mask_area_ha(morphological_closing(morphological_opening(cand, k_sq3), k_sq3), res_x, res_y)
            cr3_ha = mask_area_ha(morphological_closing(morphological_opening(cand, k_cr3), k_cr3), res_x, res_y)
            sq5_ha = mask_area_ha(morphological_closing(morphological_opening(cand, k_sq5), k_sq5), res_x, res_y)

            print(f"  {ndvi_t:>7.2f} {ndbi_t:>7.2f} {raw_ha:>10.2f} {sq3_ha:>12.2f} {cr3_ha:>12.2f} {sq5_ha:>12.2f}")

            rows.append({
                "ndvi_thresh": ndvi_t,
                "ndbi_thresh": ndbi_t,
                "raw_ha": round(raw_ha, 2),
                "square_3x3_ha": round(sq3_ha, 2),
                "cross_3x3_ha": round(cr3_ha, 2),
                "square_5x5_ha": round(sq5_ha, 2),
            })

    csv_path = config.OUTPUT_STATS / "parameter_sweep.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  Tabel disimpan: {csv_path.name}")


# ========================================================================
# VISUALISASI
# ========================================================================

def plot_multiclass_results(sawah_2018, multiclass_raster, output_dir):
    """Plot visualisasi klasifikasi alih fungsi 2-kelas."""
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    # Panel 1: Sawah Murni 2018
    axes[0].imshow(sawah_2018, cmap=ListedColormap(["#f5f5f5", "#2ecc71"]))
    axes[0].set_title(f"Lahan Sawah Terverifikasi 2018\n(NDVI > {config.TH_NDVI_SAWAH} + Tekstur σ < {config.TH_SIGMA_NIR})", fontsize=12)
    axes[0].axis("off")

    # Panel 2: Peta Alih Fungsi 2-Kelas
    # 0: Non-konversi (abu-abu muda), 1: Bangunan Permanen (merah), 2: Lahan Konstruksi (oranye)
    cmap_multi = ListedColormap(["#f5f5f5", "#e74c3c", "#e67e22"])
    im2 = axes[1].imshow(multiclass_raster, cmap=cmap_multi, interpolation="nearest")
    axes[1].set_title("Deteksi Alih Fungsi Sawah 2-Kelas (2018 -> 2026)\nMerah: Bangunan Permanen | Oranye: Lahan Konstruksi/Urukan", fontsize=12)
    axes[1].axis("off")

    # Custom legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#f5f5f5", edgecolor="gray", label="Non-Konversi / Tetap Sawah"),
        Patch(facecolor="#e74c3c", edgecolor="none", label="Kelas 1: Bangunan Permanen (NDBI)"),
        Patch(facecolor="#e67e22", edgecolor="none", label="Kelas 2: Konstruksi/Urukan (BSI)"),
    ]
    axes[1].legend(handles=legend_elements, loc="lower right", fontsize=10)

    plt.suptitle("Hasil Deteksi Alih Fungsi Sawah Multi-Kelas (PCD Murni v2.0) - Kabupaten Badung", fontsize=14, y=0.98)
    plt.tight_layout()

    out_png = output_dir / "candidate_transition_morphology.png"
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  Plot hasil multi-kelas disimpan: {out_png.name}")


# ========================================================================
# MAIN
# ========================================================================

def main():
    print("=" * 70)
    print("Script 04 (Upgrade v2.0): Multi-Rule Thresholding & Morfologi 2-Kelas")
    print("=" * 70)

    # 1. Load semua data indeks spektral & tekstur
    print("\n  Memuat indeks spektral dan tekstur...")
    ndvi_2018, _, rx, ry = load_index(config.NDVI_2018)
    ndvi_2026, _, _, _ = load_index(config.NDVI_2026)
    ndbi_2018, _, _, _ = load_index(config.NDBI_2018)
    ndbi_2026, meta, _, _ = load_index(config.NDBI_2026)
    ndwi_2018, _, _, _ = load_index(config.NDWI_2018)
    ndwi_2026, _, _, _ = load_index(config.NDWI_2026)
    bsi_2018, _, _, _ = load_index(config.BSI_2018)
    bsi_2026, _, _, _ = load_index(config.BSI_2026)
    texture_nir_2018, _, _, _ = load_index(config.TEXTURE_NIR_2018)

    print(f"  Resolusi Raster: {rx:.1f} × {ry:.1f} meter")
    print(f"  Dimensi: {ndvi_2018.shape[0]} × {ndvi_2018.shape[1]} piksel")

    # 2. Deteksi Multi-Kelas (PCD Murni)
    sawah_2018, bang_raw, kons_raw, total_raw = detect_multiclass_transition(
        ndvi_2018, ndvi_2026,
        ndbi_2018, ndbi_2026,
        ndwi_2018, ndwi_2026,
        bsi_2018, bsi_2026,
        texture_nir_2018,
        rx, ry
    )

    # 3. Operasi Morfologi + Connected Components per Kelas
    print(f"\n{'─' * 60}")
    print("  Operasi Morfologi Adaptif (Opening 3x3 + CC Filter 10px + Closing 3x3)")
    print(f"{'─' * 60}")

    bang_morphed = apply_enhanced_morphology(
        bang_raw, config.MORPHOLOGY_KERNEL_SIZE, config.MIN_CLUSTER_PIXELS, rx, ry, "Bangunan Permanen"
    )
    kons_morphed = apply_enhanced_morphology(
        kons_raw, config.MORPHOLOGY_KERNEL_SIZE, config.MIN_CLUSTER_PIXELS, rx, ry, "Lahan Konstruksi"
    )

    # Pastikan tidak ada overlap (bangunan permanen memiliki prioritas tertinggi)
    kons_morphed = kons_morphed & (~bang_morphed)
    total_morphed = bang_morphed | kons_morphed

    print(f"\n  ► TOTAL TERVERIFIKASI AKHIR:")
    print(f"    - Kelas 1 (Bangunan Permanen)   : {mask_area_ha(bang_morphed, rx, ry):.2f} ha ({mask_area_km2(bang_morphed, rx, ry):.4f} km²)")
    print(f"    - Kelas 2 (Konstruksi / Urukan) : {mask_area_ha(kons_morphed, rx, ry):.2f} ha ({mask_area_km2(kons_morphed, rx, ry):.4f} km²)")
    print(f"    - Total Alih Fungsi Sawah       : {mask_area_ha(total_morphed, rx, ry):.2f} ha ({mask_area_km2(total_morphed, rx, ry):.4f} km²)")

    # 4. Gabungkan ke dalam Raster Multi-Kelas
    # 0 = Non-konversi, 1 = Bangunan Permanen, 2 = Konstruksi/Urukan
    multiclass_raster = np.zeros(bang_morphed.shape, dtype=np.uint8)
    multiclass_raster[kons_morphed] = 2
    multiclass_raster[bang_morphed] = 1

    # 5. Simpan Hasil Raster GeoTIFF
    print(f"\n  Menyimpan hasil GeoTIFF...")
    ref_file = str(config.NDBI_2026)
    save_mask(total_raw, ref_file, config.CANDIDATE_MASK, "candidate_transition_raw")
    save_mask(total_morphed, ref_file, config.CANDIDATE_MORPHED, "candidate_transition_morphed")
    save_mask(multiclass_raster, ref_file, config.CONVERSION_MULTICLASS, "conversion_multiclass", dtype="uint8", nodata=0)

    # 6. Parameter Sweep
    run_parameter_sweep(
        ndvi_2018, ndvi_2026, ndbi_2018, ndbi_2026,
        ndwi_2018, ndwi_2026, bsi_2018, bsi_2026,
        texture_nir_2018, rx, ry
    )

    # 7. Visualisasi Hasil
    print(f"\n  Membuat grafik visualisasi multi-kelas...")
    plot_multiclass_results(sawah_2018, multiclass_raster, config.OUTPUT_MAPS)

    print(f"\n[SELESAI] Script 04 selesai! Lanjut ke script 05 (vektorisasi & visualisasi).")


if __name__ == "__main__":
    main()
