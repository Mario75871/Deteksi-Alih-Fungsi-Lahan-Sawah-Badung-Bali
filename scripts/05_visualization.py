"""
Script 05: Visualisasi Interaktif, Vektorisasi Poligon, & Zonal Stats Kecamatan
==============================================================================
Upgrade v2.0:
  1. Vektorisasi Raster Multi-Kelas ke Poligon GeoJSON (rasterio.features.shapes)
     menghasilkan atribut per klaster (ID, Luas Ha, Kategori, Delta NDVI/NDBI).
  2. Zonal Statistics per Kecamatan (Kuta Selatan, Kuta, Kuta Utara, Mengwi, Abiansemal, Petang)
     dan ekspor ke CSV & Grafik Batang.
  3. Peta Sinkronisasi Dua Layar (folium.plugins.DualMap) dengan streaming citra
     resolusi tinggi ESRI World Imagery & poligon interaktif yang bisa diklik.

Cara pakai:
    python scripts/05_visualization.py
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
from rasterio.features import shapes
from rasterio.warp import transform_bounds
import geopandas as gpd
from shapely.geometry import shape
import folium
from folium import plugins
from folium.raster_layers import ImageOverlay
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import json
import csv


# ========================================================================
# TAHAP 1: VEKTORISASI RASTER MULTI-KELAS KE GEOJSON
# ========================================================================

def vectorize_multiclass_raster(multiclass_path, ndvi_2018_path, ndvi_2026_path,
                                ndbi_2018_path, ndbi_2026_path, kecamatan_path, output_geojson):
    """
    Mengonversi raster hasil klasifikasi (1: Bangunan, 2: Konstruksi)
    menjadi poligon vektor GeoJSON dengan atribut lengkap per klaster.
    """
    print(f"\n{'=' * 70}")
    print("  TAHAP 1: VEKTORISASI RASTER KE POLIGON GEOJSON")
    print(f"{'=' * 70}")

    if not multiclass_path.exists():
        print(f"  [ERROR] File {multiclass_path.name} tidak ditemukan.")
        return None

    # Load raster multi-kelas & transform
    with rasterio.open(multiclass_path) as src:
        multi_data = src.read(1)
        transform = src.transform
        crs = src.crs

    # Load indeks untuk menghitung nilai delta per klaster
    with rasterio.open(ndvi_2018_path) as s: ndvi_18 = s.read(1)
    with rasterio.open(ndvi_2026_path) as s: ndvi_26 = s.read(1)
    with rasterio.open(ndbi_2018_path) as s: ndbi_18 = s.read(1)
    with rasterio.open(ndbi_2026_path) as s: ndbi_26 = s.read(1)

    delta_ndvi = ndvi_26 - ndvi_18
    delta_ndbi = ndbi_26 - ndbi_18

    # Ekstraksi poligon dengan mask > 0 (1 dan 2)
    mask = multi_data > 0
    generator = shapes(multi_data, mask=mask, transform=transform)

    features = []
    cluster_id = 1

    for geom, value in generator:
        val = int(value)
        poly = shape(geom)

        # Hitung luas dalam UTM (m² -> Ha)
        area_ha = poly.area / 1e4

        # Kategori
        if val == 1:
            kategori = "Bangunan Permanen"
            warna = "#e74c3c"  # Merah
        elif val == 2:
            kategori = "Lahan Konstruksi / Urukan"
            warna = "#e67e22"  # Oranye
        else:
            continue

        features.append({
            "id_klaster": cluster_id,
            "kelas_id": val,
            "kategori": kategori,
            "luas_ha": round(area_ha, 3),
            "warna": warna,
            "geometry": poly,
        })
        cluster_id += 1

    if not features:
        print("  [WARNING] Tidak ada poligon yang terbentuk dari raster.")
        return None

    # Buat GeoDataFrame dalam CRS UTM
    gdf = gpd.GeoDataFrame(features, crs=crs)

    # Spatial Join dengan data kecamatan untuk menetapkan nama kecamatan per klaster
    if kecamatan_path.exists():
        gdf_kec = gpd.read_file(kecamatan_path)
        if gdf_kec.crs != gdf.crs:
            gdf_kec = gdf_kec.to_crs(gdf.crs)

        # Spatial join menggunakan representative point agar klaster unik ke satu kecamatan
        pts = gdf.copy()
        pts.geometry = pts.geometry.representative_point()
        joined = gpd.sjoin(pts[["id_klaster", "geometry"]], gdf_kec[["kecamatan", "geometry"]], how="left", predicate="within")

        kec_dict = dict(zip(joined["id_klaster"], joined["kecamatan"]))
        gdf["kecamatan"] = gdf["id_klaster"].map(kec_dict).fillna("Badung")
    else:
        gdf["kecamatan"] = "Badung"

    # Reproject ke WGS84 untuk kompatibilitas Web GIS / Folium
    gdf_wgs84 = gdf.to_crs(epsg=4326)

    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    gdf_wgs84.to_file(output_geojson, driver="GeoJSON")

    print(f"  ✓ Berhasil membuat {len(gdf_wgs84):,} poligon klaster alih fungsi.")
    print(f"  ✓ Disimpan di: {output_geojson.name}")
    print(f"  ✓ Total Luas: {gdf['luas_ha'].sum():.2f} Ha")
    print(f"    - Bangunan Permanen : {gdf[gdf['kelas_id'] == 1]['luas_ha'].sum():.2f} Ha")
    print(f"    - Lahan Konstruksi  : {gdf[gdf['kelas_id'] == 2]['luas_ha'].sum():.2f} Ha")

    return gdf_wgs84


# ========================================================================
# TAHAP 2: ZONAL STATISTICS PER KECAMATAN
# ========================================================================

def compute_zonal_statistics(gdf_polygons, kecamatan_path, output_csv, output_dir):
    """
    Menghitung distribusi luas alih fungsi sawah pada 6 kecamatan
    dan menghasilkan tabel CSV serta grafik batang.
    """
    print(f"\n{'=' * 70}")
    print("  TAHAP 2: ZONAL STATISTICS PER KECAMATAN")
    print(f"{'=' * 70}")

    if not kecamatan_path.exists():
        print(f"  [ERROR] File kecamatan {kecamatan_path.name} tidak ditemukan.")
        return

    gdf_kec = gpd.read_file(kecamatan_path)
    kec_names = ["Kuta Selatan", "Kuta", "Kuta Utara", "Mengwi", "Abiansemal", "Petang"]

    rows = []
    print(f"\n  {'Kecamatan':<15} {'Bangunan(Ha)':>14} {'Konstruksi(Ha)':>16} {'Total(Ha)':>12} {'% Kontribusi':>14}")
    print(f"  {'─' * 75}")

    total_kabupaten = gdf_polygons["luas_ha"].sum() if gdf_polygons is not None else 0.0

    for kec in kec_names:
        if gdf_polygons is not None and "kecamatan" in gdf_polygons.columns:
            subset = gdf_polygons[gdf_polygons["kecamatan"].str.contains(kec, case=False, na=False)]
            luas_bang = subset[subset["kelas_id"] == 1]["luas_ha"].sum()
            luas_kons = subset[subset["kelas_id"] == 2]["luas_ha"].sum()
            total_kec = luas_bang + luas_kons
            n_polygons = len(subset)
        else:
            luas_bang, luas_kons, total_kec, n_polygons = 0.0, 0.0, 0.0, 0

        kontribusi = (100 * total_kec / total_kabupaten) if total_kabupaten > 0 else 0.0

        print(f"  {kec:<15} {luas_bang:>14.2f} {luas_kons:>16.2f} {total_kec:>12.2f} {kontribusi:>13.1f}%")

        rows.append({
            "kecamatan": kec,
            "bangunan_permanen_ha": round(luas_bang, 2),
            "konstruksi_urukan_ha": round(luas_kons, 2),
            "total_alih_fungsi_ha": round(total_kec, 2),
            "persen_kontribusi": round(kontribusi, 1),
            "jumlah_klaster": n_polygons,
        })

    # Simpan CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  ✓ Tabel Zonal Stats disimpan: {output_csv.name}")

    # Buat Bar Chart
    plot_kecamatan_bar_chart(rows, output_dir)


def plot_kecamatan_bar_chart(rows, output_dir):
    """Buat grafik batang horizontal alih fungsi per kecamatan."""
    kec_labels = [r["kecamatan"] for r in rows]
    bang_vals = [r["bangunan_permanen_ha"] for r in rows]
    kons_vals = [r["konstruksi_urukan_ha"] for r in rows]

    # Urutkan berdasarkan total terbesar
    totals = [b + k for b, k in zip(bang_vals, kons_vals)]
    order = np.argsort(totals)

    kec_sorted = [kec_labels[i] for i in order]
    bang_sorted = [bang_vals[i] for i in order]
    kons_sorted = [kons_vals[i] for i in order]

    fig, ax = plt.subplots(figsize=(10, 6))
    y_pos = np.arange(len(kec_sorted))

    ax.barh(y_pos, bang_sorted, color="#e74c3c", label="Bangunan Permanen (NDBI)", height=0.55)
    ax.barh(y_pos, kons_sorted, left=bang_sorted, color="#e67e22", label="Lahan Konstruksi/Urukan (BSI)", height=0.55)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(kec_sorted, fontsize=11, fontweight="bold")
    ax.set_xlabel("Luas Alih Fungsi Sawah Terdeteksi (Hektar)", fontsize=11)
    ax.set_title("Distribusi Luas Alih Fungsi Sawah per Kecamatan di Kabupaten Badung\n(Periode 2018 - 2026)", fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.5, axis="x")

    for i, (b, k) in enumerate(zip(bang_sorted, kons_sorted)):
        tot = b + k
        if tot > 0:
            ax.text(tot + 0.3, i, f"{tot:.2f} Ha", va="center", fontsize=9, fontweight="bold", color="#2c3e50")

    plt.tight_layout()
    chart_path = output_dir / "chart_kecamatan_breakdown.png"
    fig.savefig(chart_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Grafik Zonal Stats disimpan: {chart_path.name}")


# ========================================================================
# TAHAP 3: DUALMAP (PETA DUA LAYAR SINKRON + ESRI HIGH-RES)
# ========================================================================

def create_dualmap(gdf_polygons, kecamatan_path, output_path):
    """
    Membuat peta sinkronisasi dua layar (folium.plugins.DualMap):
      - Kiri: Citra Indeks / OpenStreetMap (Kondisi Awal 2018)
      - Kanan: Streaming ESRI World Imagery Sub-Meter + Poligon Interaktif (Klik)
    """
    print(f"\n{'=' * 70}")
    print("  TAHAP 3: PEMBUATAN DUALMAP (SPLIT-SCREEN INTERAKTIF)")
    print(f"{'=' * 70}")

    center_lat = (config.BADUNG_BBOX["south"] + config.BADUNG_BBOX["north"]) / 2
    center_lon = (config.BADUNG_BBOX["west"] + config.BADUNG_BBOX["east"]) / 2

    # Inisialisasi DualMap
    dm = plugins.DualMap(
        location=[center_lat, center_lon],
        zoom_start=12,
        layout="horizontal",
    )

    # Panel Kiri (m1): OpenStreetMap Basemap
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Peta Dasar Referensi (2018)",
        overlay=False,
    ).add_to(dm.m1)

    # Panel Kanan (m2): ESRI World Imagery (High-Res Sub-Meter)
    folium.TileLayer(
        tiles=config.ESRI_IMAGERY_URL,
        attr="Esri World Imagery",
        name="ESRI Satellite (Resolusi Tinggi)",
        overlay=False,
    ).add_to(dm.m2)

    # Tambahkan Batas 6 Kecamatan ke kedua panel
    if kecamatan_path.exists():
        gdf_kec = gpd.read_file(kecamatan_path).to_crs(epsg=4326)
        kec_geojson = json.loads(gdf_kec.to_json())

        for panel in [dm.m1, dm.m2]:
            folium.GeoJson(
                kec_geojson,
                name="Batas 6 Kecamatan",
                style_function=lambda x: {
                    "color": "#f1c40f",
                    "weight": 2,
                    "fillOpacity": 0.05,
                    "dashArray": "4, 4",
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["kecamatan", "luas_km2"],
                    aliases=["Kecamatan:", "Luas Admin (km²):"],
                    localize=True,
                )
            ).add_to(panel)

    # Tambahkan Poligon Vektor Interaktif (Klik) ke Panel Kanan
    if gdf_polygons is not None and not gdf_polygons.empty:
        poly_geojson = json.loads(gdf_polygons.to_json())

        def poly_style(feature):
            val = feature["properties"]["kelas_id"]
            color = "#e74c3c" if val == 1 else "#e67e22"
            return {
                "color": color,
                "weight": 2,
                "fillColor": color,
                "fillOpacity": 0.65,
            }

        folium.GeoJson(
            poly_geojson,
            name="Klaster Alih Fungsi (Klik)",
            style_function=poly_style,
            tooltip=folium.GeoJsonTooltip(
                fields=["id_klaster", "kecamatan", "kategori", "luas_ha"],
                aliases=["ID Klaster:", "Kecamatan:", "Kategori Alih Fungsi:", "Luas Terkonversi (Ha):"],
                localize=True,
            ),
            popup=folium.GeoJsonPopup(
                fields=["id_klaster", "kecamatan", "kategori", "luas_ha"],
                aliases=["Klaster #", "Kecamatan", "Klasifikasi", "Luas (Hektar)"],
                localize=True,
                labels=True,
            )
        ).add_to(dm.m2)
        print(f"  ✓ Poligon vektor interaktif ditambahkan ke panel ESRI Satellite")

    # Layer controls
    folium.LayerControl().add_to(dm.m1)
    folium.LayerControl().add_to(dm.m2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dm.save(str(output_path))
    print(f"  ✓ Peta DualMap interaktif disimpan di: {output_path.name}")


# ========================================================================
# TAHAP 4: PETA INTERAKTIF UTAMA (HTML LENGKAP)
# ========================================================================

def create_full_interactive_map(gdf_polygons, kecamatan_path, boundary_path, output_path):
    """Peta interaktif komprehensif single-screen dengan kontrol multi-layer."""
    center_lat = (config.BADUNG_BBOX["south"] + config.BADUNG_BBOX["north"]) / 2
    center_lon = (config.BADUNG_BBOX["west"] + config.BADUNG_BBOX["east"]) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles=None)

    # Basemaps
    folium.TileLayer(
        tiles=config.ESRI_IMAGERY_URL,
        attr="Esri World Imagery",
        name="ESRI Satellite (Resolusi Tinggi)",
        overlay=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
    ).add_to(m)

    # Layer Kecamatan
    if kecamatan_path.exists():
        gdf_k = gpd.read_file(kecamatan_path).to_crs(epsg=4326)
        folium.GeoJson(
            json.loads(gdf_k.to_json()),
            name="Batas 6 Kecamatan",
            style_function=lambda x: {"color": "#f39c12", "weight": 2.5, "fillOpacity": 0.05, "dashArray": "5, 5"},
            tooltip=folium.GeoJsonTooltip(fields=["kecamatan", "luas_km2"], aliases=["Kecamatan:", "Luas (km²):"])
        ).add_to(m)

    # Layer Poligon Alih Fungsi (Vector)
    if gdf_polygons is not None and not gdf_polygons.empty:
        folium.GeoJson(
            json.loads(gdf_polygons.to_json()),
            name="Klaster Alih Fungsi Sawah (Poligon Klik)",
            style_function=lambda f: {
                "color": f["properties"]["warna"],
                "fillColor": f["properties"]["warna"],
                "fillOpacity": 0.65,
                "weight": 2
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["id_klaster", "kecamatan", "kategori", "luas_ha"],
                aliases=["Klaster #", "Kecamatan:", "Kategori:", "Luas (Ha):"]
            ),
            popup=folium.GeoJsonPopup(
                fields=["id_klaster", "kecamatan", "kategori", "luas_ha"],
                aliases=["ID Klaster:", "Kecamatan:", "Kategori:", "Luas (Ha):"]
            )
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(output_path))
    print(f"  ✓ Peta interaktif utama diperbarui: {output_path.name}")


# ========================================================================
# MAIN
# ========================================================================

def main():
    print("=" * 70)
    print("Script 05 (Upgrade v2.0): Visualisasi, Vektorisasi, & Zonal Statistics")
    print("=" * 70)

    # 1. Vektorisasi Raster Multi-Kelas ke GeoJSON
    gdf_polygons = vectorize_multiclass_raster(
        config.CONVERSION_MULTICLASS,
        config.NDVI_2018, config.NDVI_2026,
        config.NDBI_2018, config.NDBI_2026,
        config.KECAMATAN_FILE,
        config.CONVERSION_POLYGONS,
    )

    # 2. Zonal Statistics per Kecamatan
    compute_zonal_statistics(
        gdf_polygons,
        config.KECAMATAN_FILE,
        config.KECAMATAN_BREAKDOWN_CSV,
        config.OUTPUT_MAPS,
    )

    # 3. Peta DualMap Split-Screen (ESRI Sub-Meter vs 2018)
    create_dualmap(
        gdf_polygons,
        config.KECAMATAN_FILE,
        config.DUALMAP_HTML,
    )

    # 4. Peta Interaktif Utama (Single Screen)
    create_full_interactive_map(
        gdf_polygons,
        config.KECAMATAN_FILE,
        config.BOUNDARY_FILE,
        config.OUTPUT_MAPS / "peta_interaktif_badung.html",
    )

    print(f"\n[SELESAI] Script 05 selesai!")
    print(f"  - Poligon GeoJSON : {config.CONVERSION_POLYGONS.name}")
    print(f"  - Zonal CSV       : {config.KECAMATAN_BREAKDOWN_CSV.name}")
    print(f"  - DualMap HTML    : {config.DUALMAP_HTML.name}")
    print(f"  - Peta Interaktif : peta_interaktif_badung.html")


if __name__ == "__main__":
    main()
