"""
Script 01: Download Batas Administratif Kabupaten Badung
========================================================
Mengunduh batas wilayah dari GADM (Global Administrative Areas Database)
atau OpenStreetMap (Nominatim) dan menyimpannya sebagai GeoJSON.

Cara pakai:
    python scripts/01_download_boundary.py
"""

import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Tambahkan root project ke path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

import requests
import geopandas as gpd
from shapely.geometry import shape
import matplotlib.pyplot as plt
import time


def download_kecamatan():
    """
    Download batas 6 kecamatan di Kabupaten Badung:
    Kuta Selatan, Kuta, Kuta Utara, Mengwi, Abiansemal, Petang.
    Disimpan ke data/boundary/badung_kecamatan.geojson.
    """
    output_path = config.KECAMATAN_FILE
    if output_path.exists():
        print(f"\n[INFO] File kecamatan sudah ada: {output_path}")
        gdf_k = gpd.read_file(output_path)
        print(f"  Jumlah kecamatan: {len(gdf_k)}")
        for _, row in gdf_k.iterrows():
            print(f"  - {row['kecamatan']}: {row['luas_km2']:.2f} km²")
        return gdf_k

    print("\n" + "=" * 60)
    print("MENGUNDUH BATAS 6 KECAMATAN DI KABUPATEN BADUNG")
    print("=" * 60)

    kecamatans = ["Kuta Selatan", "Kuta", "Kuta Utara", "Mengwi", "Abiansemal", "Petang"]
    features = []

    for kec in kecamatans:
        print(f"  Mengunduh batas Kecamatan {kec}...")
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": f"Kecamatan {kec}, Badung, Bali, Indonesia",
            "format": "json",
            "polygon_geojson": 1,
            "limit": 1,
        }
        headers = {"User-Agent": "PRATUBES_BADUNG_Academic_Research/2.0"}

        try:
            r = requests.get(url, params=params, headers=headers, timeout=30).json()
            if r and "geojson" in r[0]:
                geom = shape(r[0]["geojson"])
                features.append({
                    "kabupaten": "Badung",
                    "kecamatan": kec,
                    "geometry": geom,
                })
                print(f"    [OK] Berhasil: {kec} ({geom.geom_type})")
            else:
                print(f"    [FAIL] Gagal menemukan geometri untuk {kec}")
        except Exception as e:
            print(f"    [FAIL] Error pada {kec}: {e}")

        time.sleep(1)  # Sopan terhadap rate limit Nominatim

    if not features:
        raise RuntimeError("Gagal mengunduh batas kecamatan.")

    gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")

    # Hitung luas dalam UTM 50S (km²)
    gdf_utm = gdf.to_crs(epsg=32750)
    gdf["luas_km2"] = gdf_utm.geometry.area / 1e6

    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_path, driver="GeoJSON")
    print(f"\n[SUKSES] Batas 6 kecamatan disimpan di: {output_path}")

    # Buat preview plot kecamatan
    plot_kecamatan(gdf)
    return gdf


def plot_kecamatan(gdf):
    """Plot batas 6 kecamatan dengan warna berbeda."""
    fig, ax = plt.subplots(1, 1, figsize=(9, 10))
    gdf.plot(
        column="kecamatan",
        cmap="Set3",
        edgecolor="black",
        linewidth=1.2,
        legend=True,
        ax=ax,
        legend_kwds={"loc": "upper left", "bbox_to_anchor": (1, 1), "title": "Kecamatan"}
    )

    for idx, row in gdf.iterrows():
        # Label kecamatan pada centroid
        pt = row.geometry.representative_point()
        ax.annotate(
            text=f"{row['kecamatan']}\n({row['luas_km2']:.1f} km²)",
            xy=(pt.x, pt.y),
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="#1a237e",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7, edgecolor="none")
        )

    ax.set_title("Batas 6 Kecamatan di Kabupaten Badung", fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, linestyle="--", alpha=0.4)

    preview_path = config.OUTPUT_MAPS / "kecamatan_preview.png"
    fig.savefig(preview_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  Preview peta kecamatan disimpan: {preview_path.name}")


def download_boundary_nominatim():
    """
    Download batas Kabupaten Badung dari OpenStreetMap via Nominatim API.
    Metode ini sangat cepat, ringan, dan langsung mengembalikan poligon spesifik.
    """
    print("\n[1/2] Mengunduh batas Kabupaten Badung dari OpenStreetMap (Nominatim)...")

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": "Kabupaten Badung, Bali, Indonesia",
        "format": "json",
        "polygon_geojson": 1,
        "limit": 1,
    }
    headers = {"User-Agent": "PRATUBES_BADUNG_Academic_Research/1.0"}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data or "geojson" not in data[0]:
            raise ValueError("Nominatim tidak mengembalikan geometri geojson")

        geometry = shape(data[0]["geojson"])
        gdf = gpd.GeoDataFrame(
            {
                "name": ["Kabupaten Badung"],
                "province": ["Bali"],
                "source": ["OpenStreetMap/Nominatim"],
            },
            geometry=[geometry],
            crs="EPSG:4326",
        )

        output_path = config.BOUNDARY_FILE
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(output_path, driver="GeoJSON")

        # Hitung luas dalam UTM Zone 50S (Bali)
        gdf_utm = gdf.to_crs(epsg=32750)
        area_km2 = gdf_utm.area.sum() / 1e6

        print(f"\n{'=' * 60}")
        print(f"BERHASIL!")
        print(f"  File   : {output_path}")
        print(f"  CRS    : EPSG:4326 (WGS84)")
        print(f"  Luas   : {area_km2:.4f} km²")
        print(f"  Bounds : {gdf.total_bounds}")
        print(f"{'=' * 60}")

        # Buat preview visualisasi
        plot_boundary(gdf, area_km2)
        return gdf

    except Exception as e:
        print(f"  [ERROR] Gagal download dari Nominatim: {e}")
        print("  Mencoba metode alternatif (GADM)...")
        return download_boundary_gadm()


def download_boundary_gadm():
    """Fallback: Mengunduh dari GADM jika OSM gagal."""
    print("\n[ALT] Mengunduh data dari GADM...")
    gadm_url = "https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_IDN_2.json.zip"

    try:
        gdf_all = gpd.read_file(gadm_url)
        badung = gdf_all[
            (gdf_all["NAME_1"].str.contains("Bali", case=False, na=False))
            & (gdf_all["NAME_2"].str.contains("Badung", case=False, na=False))
        ]

        if len(badung) == 0:
            badung = gdf_all[gdf_all["NAME_2"].str.contains("Badung", case=False, na=False)]

        badung = badung.to_crs(epsg=4326)
        output_path = config.BOUNDARY_FILE
        output_path.parent.mkdir(parents=True, exist_ok=True)
        badung.to_file(output_path, driver="GeoJSON")

        area_km2 = badung.to_crs(epsg=32750).area.sum() / 1e6
        print(f"  Berhasil dari GADM! Luas: {area_km2:.4f} km²")
        plot_boundary(badung, area_km2)
        return badung
    except Exception as e:
        print(f"  [FATAL] Gagal download boundary: {e}")
        sys.exit(1)


def plot_boundary(gdf, area_km2):
    """Buat preview plot dari boundary."""
    fig, ax = plt.subplots(1, 1, figsize=(8, 8))
    gdf.plot(ax=ax, facecolor="#e1f5fe", edgecolor="#0277bd", linewidth=2)
    ax.set_title(
        f"Batas Wilayah Kerja Kabupaten Badung\n(Luas terhitung: {area_km2:.2f} km²)",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, linestyle="--", alpha=0.5)

    plot_path = config.OUTPUT_MAPS / "boundary_preview.png"
    plot_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    print(f"  Preview disimpan: {plot_path}")
    plt.close(fig)


def main():
    print("=" * 60)
    print("Tahap 1: Download Batas Administratif Kabupaten & Kecamatan")
    print("=" * 60)

    # 1. Batas Kabupaten Badung
    if not config.BOUNDARY_FILE.exists():
        download_boundary_nominatim()
    else:
        print(f"\n[INFO] File boundary kabupaten sudah ada: {config.BOUNDARY_FILE}")

    # 2. Batas 6 Kecamatan
    download_kecamatan()


if __name__ == "__main__":
    main()
