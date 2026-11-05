"""
Script 05_v2: Vektorisasi Poligon Alih Fungsi + Analisis Zonal Kecamatan + DualMap
===================================================================================
PCD Murni Versi 2.0:
  - Vektorisasi raster klasifikasi multi-kelas (rasterio.features.shapes)
  - Spatial Join dengan 6 kecamatan administratif Kabupaten Badung
  - Kuantifikasi luasan (Ha) per kecamatan
  - Sinkronisasi dengan referensi Dinas Pertanian / Satu Data Badung
  - Ekspor GeoJSON (conversion_polygons.geojson)
  - Pembuatan peta DualMap Folium (Streaming ESRI Sub-Meter) & peta utama
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

import json
import rasterio
from rasterio.features import shapes
import geopandas as gpd
from shapely.geometry import shape
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import folium
from folium import plugins


def vectorize_conversion(multiclass_path):
    """
    Mengonversi piksel alih fungsi (1 & 2) menjadi poligon vektor GeoJSON.
    """
    print(f"\n  Membaca raster multi-kelas: {multiclass_path.name}")
    with rasterio.open(multiclass_path) as src:
        image = src.read(1)
        transform = src.transform
        crs = src.crs

    mask = (image > 0)
    results = []

    # Ekstrak poligon menggunakan shapes generator
    for geom, value in shapes(image, mask=mask, transform=transform):
        val_int = int(value)
        poly_geom = shape(geom)
        luas_m2 = poly_geom.area
        luas_ha = luas_m2 / 10000.0

        if val_int == 1:
            kategori = "Bangunan Permanen / Vila Tropis"
            warna = "#E31A1C"
        else:
            kategori = "Lahan Terbuka / Konstruksi"
            warna = "#FF7F00"

        results.append({
            "geometry": poly_geom,
            "kelas_id": val_int,
            "kategori": kategori,
            "luas_ha": round(luas_ha, 3),
            "luas_m2": round(luas_m2, 1),
            "warna": warna
        })

    gdf = gpd.GeoDataFrame(results, crs=crs)
    gdf["id_klaster"] = range(1, len(gdf) + 1)
    return gdf


def perform_zonal_analysis(gdf_poly, kecamatan_path):
    """
    Menghitung Zonal Statistics untuk 6 kecamatan di Badung.
    """
    if not kecamatan_path.exists():
        print(f"  [PERINGATAN] File kecamatan {kecamatan_path.name} tidak ditemukan.")
        gdf_poly["kecamatan"] = "Kabupaten Badung"
        return gdf_poly, None

    gdf_kec = gpd.read_file(kecamatan_path)
    if gdf_kec.crs != gdf_poly.crs:
        gdf_kec = gdf_kec.to_crs(gdf_poly.crs)

    # Spatial join poligon alih fungsi dengan poligon kecamatan
    # Gunakan representative_point untuk menetapkan kecamatan klaster
    gdf_pts = gdf_poly.copy()
    gdf_pts["geom_rep"] = gdf_pts.geometry.representative_point()
    gdf_pts = gdf_pts.set_geometry("geom_rep")

    joined = gpd.sjoin(gdf_pts, gdf_kec[["kecamatan", "geometry"]], how="left", predicate="intersects")
    gdf_poly["kecamatan"] = joined["kecamatan"].fillna("Perbatasan / Lainnya")

    # Rekapitulasi per kecamatan
    summary_rows = []
    daftar_kec = sorted(list(gdf_kec["kecamatan"].unique()))

    total_kabupaten = gdf_poly["luas_ha"].sum()

    for kec in daftar_kec:
        sub = gdf_poly[gdf_poly["kecamatan"] == kec]
        bld_ha = sub[sub["kelas_id"] == 1]["luas_ha"].sum()
        cst_ha = sub[sub["kelas_id"] == 2]["luas_ha"].sum()
        tot_ha = bld_ha + cst_ha
        pct = (tot_ha / total_kabupaten * 100.0) if total_kabupaten > 0 else 0.0
        n_clusters = len(sub)

        summary_rows.append({
            "kecamatan": kec,
            "bangunan_permanen_ha": round(bld_ha, 2),
            "konstruksi_urukan_ha": round(cst_ha, 2),
            "total_alih_fungsi_ha": round(tot_ha, 2),
            "persen_kontribusi": round(pct, 1),
            "jumlah_klaster": n_clusters
        })

    df_kec = pd.DataFrame(summary_rows)
    # Urutkan berdasarkan total alih fungsi menurun
    df_kec = df_kec.sort_values(by="total_alih_fungsi_ha", ascending=False).reset_index(drop=True)
    return gdf_poly, df_kec


def make_interactive_maps(gdf_poly_wgs84, gdf_kec_wgs84, output_dir):
    """
    Membuat peta interaktif Folium (Peta Utama & DualMap Sinkron).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    center_lat, center_lon = -8.55, 115.18

    # 1. PETA INTERAKTIF UTAMA
    m = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles=None)

    folium.TileLayer('OpenStreetMap', name='OpenStreetMap', control=True).add_to(m)
    folium.TileLayer(
        tiles=config.ESRI_IMAGERY_URL,
        attr='Esri, Maxar, Earthstar Geographics, CNES/Airbus DS',
        name='ESRI World Imagery (Sub-Meter)',
        overlay=False,
        control=True
    ).add_to(m)

    # Batas Kecamatan
    if gdf_kec_wgs84 is not None:
        folium.GeoJson(
            gdf_kec_wgs84,
            name="Batas Kecamatan",
            style_function=lambda x: {
                'fillColor': '#3388ff',
                'color': '#0033cc',
                'weight': 1.5,
                'fillOpacity': 0.05
            },
            tooltip=folium.GeoJsonTooltip(fields=['kecamatan'], aliases=['Kecamatan:'])
        ).add_to(m)

    # Poligon Alih Fungsi
    if not gdf_poly_wgs84.empty:
        folium.GeoJson(
            gdf_poly_wgs84,
            name="Klaster Alih Fungsi (v2.0)",
            style_function=lambda feat: {
                'fillColor': feat['properties']['warna'],
                'color': feat['properties']['warna'],
                'weight': 1.5,
                'fillOpacity': 0.70
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['id_klaster', 'luas_ha', 'kategori', 'kecamatan'],
                aliases=['ID Klaster:', 'Luas (Ha):', 'Kategori:', 'Kecamatan:']
            )
        ).add_to(m)

    folium.LayerControl(position='topright').add_to(m)
    plugins.Fullscreen().add_to(m)

    map_path = output_dir / "peta_interaktif_badung.html"
    m.save(str(map_path))
    print(f"  ✓ Peta interaktif tersimpan: {map_path.name}")

    # 2. PETA DUALMAP KOMPARASI SPLIT-SCREEN
    dual_map = plugins.DualMap(location=[center_lat, center_lon], zoom_start=11)

    # Panel Kiri: OSM + Poligon Alih Fungsi
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(dual_map.m1)
    if not gdf_poly_wgs84.empty:
        folium.GeoJson(
            gdf_poly_wgs84,
            name="Alih Fungsi Sawah",
            style_function=lambda feat: {
                'fillColor': feat['properties']['warna'],
                'color': feat['properties']['warna'],
                'weight': 2,
                'fillOpacity': 0.8
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['id_klaster', 'luas_ha', 'kategori', 'kecamatan'],
                aliases=['ID Klaster:', 'Luas (Ha):', 'Kategori:', 'Kecamatan:']
            )
        ).add_to(dual_map.m1)

    # Panel Kanan: ESRI World Imagery Sub-Meter + Poligon
    folium.TileLayer(
        tiles=config.ESRI_IMAGERY_URL,
        attr='Esri, Maxar',
        name='ESRI Satellite (Sub-Meter)'
    ).add_to(dual_map.m2)

    if not gdf_poly_wgs84.empty:
        folium.GeoJson(
            gdf_poly_wgs84,
            name="Alih Fungsi (Overlay)",
            style_function=lambda feat: {
                'fillColor': feat['properties']['warna'],
                'color': '#FFFF00',
                'weight': 2,
                'fillOpacity': 0.6
            }
        ).add_to(dual_map.m2)

    dualmap_path = output_dir / "peta_dualmap_klaster.html"
    dual_map.save(str(dualmap_path))
    print(f"  ✓ Peta DualMap tersimpan: {dualmap_path.name}")


def main():
    print("=" * 70)
    print("Script 05_v2: Vektorisasi Poligon Alih Fungsi + Zonal Stats Kecamatan")
    print("=" * 70)

    # 1. Vektorisasi poligon dari raster multi-kelas hasil script 04_v2
    print("\n--- TAHAP 1: Vektorisasi Raster Alih Fungsi ---")
    if not config.CONVERSION_MULTICLASS.exists():
        print(f"[ERROR] Berkas raster {config.CONVERSION_MULTICLASS} belum ada. Jalankan script 04_v2 dahulu.")
        sys.exit(1)

    gdf_poly = vectorize_conversion(config.CONVERSION_MULTICLASS)
    print(f"  Total poligon diekstrak: {len(gdf_poly):,} klaster")
    print(f"  Total luasan alih fungsi: {gdf_poly['luas_ha'].sum():.2f} Ha")

    # 2. Zonal Analysis per Kecamatan
    print("\n--- TAHAP 2: Analisis Spasial Zonal 6 Kecamatan ---")
    gdf_poly, df_kec = perform_zonal_analysis(gdf_poly, config.KECAMATAN_FILE)

    if df_kec is not None:
        print("\n" + "=" * 70)
        print("DISTRIBUSI ALIH FUNGSI SAWAH PER KECAMATAN (KABUPATEN BADUNG)")
        print("=" * 70)
        for _, row in df_kec.iterrows():
            print(f"  {row['kecamatan']:15s}: Permanen={row['bangunan_permanen_ha']:7.2f} Ha | "
                  f"Konstruksi={row['konstruksi_urukan_ha']:6.2f} Ha | "
                  f"Total={row['total_alih_fungsi_ha']:7.2f} Ha ({row['persen_kontribusi']:5.1f}%) | "
                  f"{row['jumlah_klaster']:3d} klaster")
        print("=" * 70)

        # Simpan CSV statistik per kecamatan
        config.KECAMATAN_BREAKDOWN_CSV.parent.mkdir(parents=True, exist_ok=True)
        df_kec.to_csv(config.KECAMATAN_BREAKDOWN_CSV, index=False)
        print(f"  ✓ Tersimpan: {config.KECAMATAN_BREAKDOWN_CSV.name}")

        # Buat grafik batang per kecamatan
        fig, ax = plt.subplots(figsize=(10, 5))
        df_plot = df_kec.sort_values(by="total_alih_fungsi_ha", ascending=True)
        bars1 = ax.barh(df_plot["kecamatan"], df_plot["bangunan_permanen_ha"], label="Bangunan Permanen / Vila", color="#E31A1C")
        bars2 = ax.barh(df_plot["kecamatan"], df_plot["konstruksi_urukan_ha"], left=df_plot["bangunan_permanen_ha"], label="Lahan Konstruksi / Urukan", color="#FF7F00")

        ax.set_xlabel("Luas Alih Fungsi (Hektar)", fontsize=11)
        ax.set_title("Luas Alih Fungsi Lahan Sawah per Kecamatan di Kabupaten Badung (2018 - 2026)", fontsize=12)
        ax.legend(loc="lower right")

        for bar1, bar2 in zip(bars1, bars2):
            tot = bar1.get_width() + bar2.get_width()
            if tot > 0.5:
                ax.text(tot + 0.3, bar1.get_y() + bar1.get_height()/2, f"{tot:.2f} Ha", va="center", fontsize=9, fontweight="bold")

        plt.tight_layout()
        chart_path = config.OUTPUT_MAPS / "chart_kecamatan_breakdown.png"
        fig.savefig(chart_path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  ✓ Grafik tersimpan: {chart_path.name}")

    # 3. Ekspor Vektor GeoJSON dalam WGS84 (EPSG:4326) untuk Web Map
    print("\n--- TAHAP 3: Ekspor GeoJSON & Peta Interaktif Web ---")
    gdf_poly_wgs84 = gdf_poly.to_crs(epsg=4326)
    config.CONVERSION_POLYGONS.parent.mkdir(parents=True, exist_ok=True)
    gdf_poly_wgs84.to_file(config.CONVERSION_POLYGONS, driver="GeoJSON")
    print(f"  ✓ Vektor poligon tersimpan: {config.CONVERSION_POLYGONS.name}")

    gdf_kec_wgs84 = None
    if config.KECAMATAN_FILE.exists():
        gdf_kec_wgs84 = gpd.read_file(config.KECAMATAN_FILE).to_crs(epsg=4326)

    # 4. Generate Peta Folium & DualMap
    make_interactive_maps(gdf_poly_wgs84, gdf_kec_wgs84, config.OUTPUT_MAPS)

    print("\n[SELESAI] Script 05_v2 selesai dengan sukses!")


if __name__ == "__main__":
    main()
