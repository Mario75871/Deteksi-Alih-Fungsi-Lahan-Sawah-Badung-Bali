"""
Script 04_v2: Segmentasi Sawah 2 Fase + Deteksi Alih Fungsi Vila Tropis + Morfologi 2x2
========================================================================================
PCD Murni (Non-Machine Learning) Versi 2.0:
  - Sawah 2018: Fase Vegetatif (NDVI>0.45, LSWI>0.18) OR Fase Genangan Subak (0.1<NDVI<=0.45, LSWI>0.25, NDBI<-0.10)
  - Filter Tekstur Simpangan Baku NIR: sigma_NIR < 0.045
  - Morfologi Sawah: Ellipse 3x3 + CCA Area Filter >= 15 piksel (1.500 m²)
  - Deteksi Sawah Hilang (Lost Paddy): Sawah 2018 == 1 and Sawah 2026 == 0
  - Konversi Vila Tropis / Bangunan: LostPaddy and (Delta NDBI > 0.10 and Delta LSWI < -0.05)
  - Konversi Konstruksi / Urukan: LostPaddy and Delta BSI > 0.10
  - Morfologi Konversi: Rectangular 2x2 (menjaga kavling vila kecil tidak terhapus) + CCA >= 5 piksel
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
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap


def read_raster(filepath):
    """Membaca single-band GeoTIFF sebagai numpy array float32."""
    with rasterio.open(filepath) as src:
        data = src.read(1).astype(np.float32)
        meta = src.meta.copy()
        profile = src.profile.copy()
        res_x = abs(src.transform[0])
        res_y = abs(src.transform[4])
    return data, meta, profile, (res_x, res_y)


def filter_connected_components(binary_mask, min_pixels):
    """
    Menghapus klaster piksel terisolasi yang lebih kecil dari min_pixels
    menggunakan Connected Component Analysis (CCA) 8-connectivity (vectorized).
    """
    if min_pixels <= 1:
        return binary_mask

    mask_uint8 = binary_mask.astype(np.uint8)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_uint8, connectivity=8)

    areas = stats[:, cv2.CC_STAT_AREA]
    keep = (areas >= min_pixels)
    keep[0] = False  # background selalu False

    filtered_mask = keep[labels]
    return filtered_mask


def apply_sawah_morphology(binary_mask, min_pixels=15):
    """
    Pembersihan morfologi untuk sawah:
    1. Opening Ellipse 3x3: menghapus garis pematang tipis dan derau jalan
    2. Closing Ellipse 3x3: mengisi lubang kecil di dalam hamparan petak
    3. CCA Filter: menghapus fragmen sawah < 15 piksel (1.500 m²)
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_u8 = binary_mask.astype(np.uint8)
    opened = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
    filtered = filter_connected_components(closed.astype(bool), min_pixels=min_pixels)
    return filtered


def apply_conversion_morphology(binary_mask, min_pixels=5):
    """
    Pembersihan morfologi untuk alih fungsi (vila / bangunan):
    1. Opening Rectangular 2x2: membersihkan derau piksel tunggal tanpa menghapus kavling vila kecil
    2. CCA Filter: menghapus klaster < 5 piksel (500 m²)
    """
    kernel = np.ones((2, 2), dtype=np.uint8)
    mask_u8 = binary_mask.astype(np.uint8)
    opened = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
    filtered = filter_connected_components(opened.astype(bool), min_pixels=min_pixels)
    return filtered


def main():
    print("=" * 70)
    print("Script 04_v2: Segmentasi Sawah 2 Fase + Deteksi Vila Tropis + Morfologi 2x2")
    print("=" * 70)

    # 1. Load semua indeks hasil script 03_v2
    print("\n--- TAHAP 1: Load Indeks Spektral & Tekstur NIR ---")
    ndvi_2018, meta, profile, (res_x, res_y) = read_raster(config.NDVI_2018)
    ndvi_2026, _, _, _ = read_raster(config.NDVI_2026)

    lswi_2018, _, _, _ = read_raster(config.LSWI_2018)
    lswi_2026, _, _, _ = read_raster(config.LSWI_2026)

    ndbi_2018, _, _, _ = read_raster(config.NDBI_2018)
    ndbi_2026, _, _, _ = read_raster(config.NDBI_2026)

    bsi_2018, _, _, _ = read_raster(config.BSI_2018)
    bsi_2026, _, _, _ = read_raster(config.BSI_2026)

    texture_2018, _, _, _ = read_raster(config.TEXTURE_NIR_2018)
    texture_2026, _, _, _ = read_raster(config.TEXTURE_NIR_2026)

    pixel_area_m2 = res_x * res_y
    pixel_area_ha = pixel_area_m2 / 10000.0
    print(f"  Resolusi spasial: {res_x:.1f}m x {res_y:.1f}m ({pixel_area_ha:.4f} Ha/pixel)")

    # 2. Common Valid Area (irisan piksel valid kedua tahun)
    common_valid = (
        (~np.isnan(ndvi_2018)) & (~np.isnan(ndvi_2026)) &
        (~np.isnan(lswi_2018)) & (~np.isnan(lswi_2026)) &
        (~np.isnan(ndbi_2018)) & (~np.isnan(ndbi_2026)) &
        (~np.isnan(bsi_2018))  & (~np.isnan(bsi_2026))  &
        (~np.isnan(texture_2018)) & (~np.isnan(texture_2026))
    )
    common_valid_ha = np.count_nonzero(common_valid) * pixel_area_ha
    print(f"  Common Valid Area: {np.count_nonzero(common_valid):,} piksel ({common_valid_ha:.2f} Ha / {common_valid_ha/100:.2f} km²)")

    # 3. Klasifikasi Sawah 2018 (Baseline)
    print("\n--- TAHAP 2: Klasifikasi Sawah 2018 (Fase Vegetatif & Subak) ---")
    # Fase Vegetatif
    sawah_veg_2018 = (
        common_valid &
        (ndvi_2018 > config.TH_NDVI_SAWAH_VEG) &
        (lswi_2018 > config.TH_LSWI_SAWAH_VEG) &
        (texture_2018 < config.TH_SIGMA_NIR)
    )
    # Fase Genangan Air Subak / Pengolahan Tanah
    sawah_water_2018 = (
        common_valid &
        (ndvi_2018 > config.TH_NDVI_SAWAH_WATER_MIN) &
        (ndvi_2018 <= config.TH_NDVI_SAWAH_WATER_MAX) &
        (lswi_2018 > config.TH_LSWI_SAWAH_WATER) &
        (ndbi_2018 < config.TH_NDBI_SAWAH_WATER) &
        (texture_2018 < config.TH_SIGMA_NIR)
    )
    sawah_2018_raw = sawah_veg_2018 | sawah_water_2018
    sawah_2018_morphed = apply_sawah_morphology(sawah_2018_raw, min_pixels=config.MIN_SAWAH_PIXELS)

    px_veg_18 = np.count_nonzero(sawah_veg_2018)
    px_wat_18 = np.count_nonzero(sawah_water_2018)
    px_sawah_18 = np.count_nonzero(sawah_2018_morphed)
    print(f"  Sawah Vegetatif 2018: {px_veg_18:,} px ({px_veg_18 * pixel_area_ha:.2f} Ha)")
    print(f"  Sawah Subak/Genang 2018: {px_wat_18:,} px ({px_wat_18 * pixel_area_ha:.2f} Ha)")
    print(f"  Total Sawah 2018 (Morphed Ellipse 3x3): {px_sawah_18:,} px ({px_sawah_18 * pixel_area_ha:.2f} Ha)")

    # 4. Deteksi Sawah 2026 (Apakah masih bertahan sebagai sawah?)
    print("\n--- TAHAP 3: Deteksi Kondisi Sawah 2026 ---")
    sawah_veg_2026 = (
        common_valid &
        (ndvi_2026 > config.TH_NDVI_SAWAH_VEG) &
        (lswi_2026 > config.TH_LSWI_SAWAH_VEG) &
        (texture_2026 < config.TH_SIGMA_NIR)
    )
    sawah_water_2026 = (
        common_valid &
        (ndvi_2026 > config.TH_NDVI_SAWAH_WATER_MIN) &
        (ndvi_2026 <= config.TH_NDVI_SAWAH_WATER_MAX) &
        (lswi_2026 > config.TH_LSWI_SAWAH_WATER) &
        (ndbi_2026 < config.TH_NDBI_SAWAH_WATER) &
        (texture_2026 < config.TH_SIGMA_NIR)
    )
    sawah_2026_raw = sawah_veg_2026 | sawah_water_2026
    sawah_2026_morphed = apply_sawah_morphology(sawah_2026_raw, min_pixels=config.MIN_SAWAH_PIXELS)
    px_sawah_26 = np.count_nonzero(sawah_2026_morphed)
    print(f"  Total Sawah 2026 (Morphed Ellipse 3x3): {px_sawah_26:,} px ({px_sawah_26 * pixel_area_ha:.2f} Ha)")

    # 5. Sawah Hilang (Lost Paddy)
    lost_paddy = (sawah_2018_morphed) & (~sawah_2026_morphed)
    px_lost = np.count_nonzero(lost_paddy)
    print(f"  Sawah Hilang (Lost Paddy): {px_lost:,} px ({px_lost * pixel_area_ha:.2f} Ha)")

    # 6. Multitemporal Differential Change Detection (Vila Tropis & Bangunan vs Konstruksi)
    print("\n--- TAHAP 4: Multitemporal Differential Change Detection (Vila Tropis) ---")
    delta_ndbi = ndbi_2026 - ndbi_2018
    delta_lswi = lswi_2026 - lswi_2018
    delta_bsi  = bsi_2026 - bsi_2018

    # Kelas 1: Bangunan Permanen / Vila Tropis
    # Karakteristik Vila Tropis: NDBI meningkat (atap/semen), LSWI anjlok (saluran irigasi kering),
    # atau NDBI 2026 positif dengan kenaikan material terbangun
    is_built_raw = lost_paddy & (
        ((delta_ndbi > config.TH_DELTA_NDBI) & (delta_lswi < config.TH_DELTA_LSWI)) |
        ((ndbi_2026 > config.TH_NDBI_BUILT_2026) & (delta_ndbi > 0.05))
    )

    # Kelas 2: Lahan Konstruksi / Urukan Tanah / Cut & Fill
    is_const_raw = lost_paddy & (~is_built_raw) & (
        (delta_bsi > config.TH_DELTA_BSI) |
        ((bsi_2026 > 0.05) & (delta_bsi > 0.05))
    )

    # 7. Pembersihan Morfologi Konversi (Rectangular 2x2 + CCA)
    print("\n--- TAHAP 5: Morfologi Rectangular 2x2 & Filter Kavling (CCA >= 5 px) ---")
    built_morphed = apply_conversion_morphology(is_built_raw, min_pixels=config.MIN_CONVERSION_PIXELS)
    const_morphed = apply_conversion_morphology(is_const_raw, min_pixels=config.MIN_CONVERSION_PIXELS)

    # Prioritas kelas: Jika tumpang tindih, Bangunan Permanen meng-override Konstruksi
    const_morphed = const_morphed & (~built_morphed)

    # Buat raster multi-kelas (0: Non, 1: Bangunan/Vila, 2: Konstruksi)
    multiclass_raster = np.zeros(ndvi_2018.shape, dtype=np.uint8)
    multiclass_raster[built_morphed] = 1
    multiclass_raster[const_morphed] = 2

    # Raster biner gabungan
    combined_binary = (multiclass_raster > 0)

    # Hitung Statistik Luasan
    px_built = np.count_nonzero(built_morphed)
    px_const = np.count_nonzero(const_morphed)
    px_total = px_built + px_const

    ha_built = px_built * pixel_area_ha
    ha_const = px_const * pixel_area_ha
    ha_total = px_total * pixel_area_ha

    print("=" * 55)
    print(f"  Kelas 1 (Bangunan Permanen / Vila): {px_built:7,d} px ({ha_built:8.2f} Ha)")
    print(f"  Kelas 2 (Lahan Konstruksi / Urukan): {px_const:7,d} px ({ha_const:8.2f} Ha)")
    print(f"  TOTAL ALIH FUNGSI SAWAH (v2.0):    {px_total:7,d} px ({ha_total:8.2f} Ha)")
    print("=" * 55)

    # 8. Simpan Raster GeoTIFF Hasil
    print("\n--- TAHAP 6: Simpan Berkas GeoTIFF Hasil ---")
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    out_meta = meta.copy()
    out_meta.update({
        "count": 1,
        "dtype": "uint8",
        "nodata": 0,
    })

    with rasterio.open(config.CONVERSION_MULTICLASS, "w", **out_meta) as dst:
        dst.write(multiclass_raster, 1)
    print(f"  ✓ Tersimpan: {config.CONVERSION_MULTICLASS.name} (Multi-Class Raster)")

    with rasterio.open(config.CANDIDATE_MASK, "w", **out_meta) as dst:
        dst.write((is_built_raw | is_const_raw).astype(np.uint8), 1)
    print(f"  ✓ Tersimpan: {config.CANDIDATE_MASK.name} (Raw Candidate Mask)")

    with rasterio.open(config.CANDIDATE_MORPHED, "w", **out_meta) as dst:
        dst.write(combined_binary.astype(np.uint8), 1)
    print(f"  ✓ Tersimpan: {config.CANDIDATE_MORPHED.name} (Combined Morphed Mask)")

    # 9. Buat Visualisasi Plot Morfologi Komparatif
    print("\n--- TAHAP 7: Buat Visualisasi Plot Morfologi ---")
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    axes[0].imshow(sawah_2018_morphed, cmap="Greens")
    axes[0].set_title(f"Sawah Baseline 2018 (Morphed Ellipse 3x3)\nTotal: {px_sawah_18 * pixel_area_ha:.2f} Ha", fontsize=11)
    axes[0].axis("off")

    raw_conv = is_built_raw | is_const_raw
    axes[1].imshow(raw_conv, cmap="Reds")
    axes[1].set_title(f"Kandidat Alih Fungsi Mentah (Raw)\nTotal: {np.count_nonzero(raw_conv) * pixel_area_ha:.2f} Ha", fontsize=11)
    axes[1].axis("off")

    cmap_multi = ListedColormap(["#f0f0f0", "#E31A1C", "#FF7F00"])
    axes[2].imshow(multiclass_raster, cmap=cmap_multi, vmin=0, vmax=2)
    axes[2].set_title(f"Hasil Alih Fungsi v2 (Morfologi 2x2 & CCA)\nMerah: Vila/Bangunan ({ha_built:.2f} Ha)\nOranye: Konstruksi ({ha_const:.2f} Ha)", fontsize=11)
    axes[2].axis("off")

    plt.suptitle("Deteksi Alih Fungsi Sawah Menjadi Vila Tropis / Kawasan Terbangun (v2.0) - Kabupaten Badung", fontsize=13)
    plt.tight_layout()

    out_plot = config.OUTPUT_MAPS / "candidate_transition_morphology.png"
    out_plot.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_plot, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Plot morfologi disimpan: {out_plot.name}")

    # Simpan ringkasan statistik
    df_final = pd.DataFrame([
        {"kategori": "Sawah Baseline 2018", "luas_ha": px_sawah_18 * pixel_area_ha, "piksel": px_sawah_18},
        {"kategori": "Sawah Bertahan 2026", "luas_ha": px_sawah_26 * pixel_area_ha, "piksel": px_sawah_26},
        {"kategori": "Sawah Hilang (Lost Paddy)", "luas_ha": px_lost * pixel_area_ha, "piksel": px_lost},
        {"kategori": "Bangunan Permanen / Vila", "luas_ha": ha_built, "piksel": px_built},
        {"kategori": "Lahan Konstruksi / Urukan", "luas_ha": ha_const, "piksel": px_const},
        {"kategori": "Total Alih Fungsi Sawah", "luas_ha": ha_total, "piksel": px_total},
    ])
    df_final.to_csv(config.FINAL_STATS_CSV, index=False)
    print(f"  ✓ Ringkasan statistik disimpan: {config.FINAL_STATS_CSV.name}")

    print("\n[SELESAI] Script 04_v2 selesai dengan sukses!")


if __name__ == "__main__":
    main()
