# 🚀 Implementation Plan (v3.0): Integrasi Algoritma PCD V2 dan Dashboard Interaktif untuk Deteksi Alih Fungsi Sawah Kabupaten Badung (2018–2026)

**Nama Proyek:** Deteksi dan Kuantifikasi Alih Fungsi Lahan Sawah Menjadi Kawasan Terbangun (Vila Tropis) di Kabupaten Badung, Bali  
**Pendekatan:** *Pure Digital Image Processing* (100% Non-Machine Learning: Bilateral Filter, LSWI, Local Texture $\sigma_{NIR}$, & Multitemporal Differential Change Detection)  
**Tujuan Utama:** Menyelaraskan hasil kuantifikasi luasan alih fungsi dengan data riil dari Dinas Pertanian / Satu Data Badung (~871,86 Ha di Kuta Utara) dan menyatukannya ke dalam antarmuka *Dashboard* Streamlit.

---

## 1. Latar Belakang & Kesenjangan Algoritma (Gap Analysis)
Pada versi sebelumnya, sistem menggunakan aturan threshold mutlak NDBI $> 0.1$ dan kernel morfologi $3 \times 3$ yang terlalu agresif, sehingga hanya mendeteksi alih fungsi seluas **0,71 Ha** di Kuta Utara (gagal mendeteksi karakteristik kavling vila tropis berpadu taman dan kolam renang). 

Dengan mengadopsi algoritma **v2 (`deteksi_alih_fungsi_kuta_utara_v2.py`)**, sistem akan:
1. Mengganti indeks NDWI dengan **LSWI** (*Land Surface Water Index*) yang jauh lebih sensitif terhadap genangan air lumpur sawah dan pengeringan irigasi subak.
2. Menambahkan filter **Tekstur Spasial Lokal ($\sigma_{NIR}$) ukuran $5 \times 5$** untuk mengeliminasi *false positive* dari pepohonan/hutan di sempadan sungai.
3. Menggunakan **Multitemporal Differential Change Detection** ($\Delta \text{NDBI} > 0.10 \land \Delta \text{LSWI} < -0.05$) agar perubahan bentuk kavling vila dengan vegetasi pendukung tetap terdeteksi.
4. Menyesuaikan kernel morfologi akhir konversi menjadi ukuran **$2 \times 2$** agar kavling bangunan kecil di Kuta Utara tidak terhapus oleh filter spasial.

---

## 2. Arsitektur Pipeline yang Diperbarui

```
flowchart TD
    A["00_test_auth.py\nAutentikasi CDSE OIDC"] --> B["01_download_boundary.py\nBatas Kab. Badung & 6 Kecamatan"]
    B --> C["02_download_sentinel.py\nopenEO Median Composite (2018 & 2026)"]
    C --> D["03_compute_indices_v2.py (UPGRADED)\nBicubic Resampling + Bilateral Filter\n+ NDVI, LSWI, NDBI, BSI + Tekstur NIR (σ)"]
    D --> E["04_threshold_morphology_v2.py (UPGRADED)\nMulti-Rule Sawah (2 Fase) + Vila Tropis\n+ Morfologi (Elips 3x3 Sawah, Rect 2x2 Bangunan)\n+ Connected Component Analysis (>= 15 px)"]
    E --> F["05_visualization_v2.py (UPGRADED)\nVektorisasi GeoJSON + DualMap Sinkron + Zonal Stats BPS"]
    E --> G["app.py (STREAMLIT DASHBOARD)\nSinkronisasi Data V2 Real-Time + KPI Luas 871.86 Ha Reference"]
```

---

## 3. Rincian Rencana Implementasi per Modul

### Modul 1: Peningkatan Modul Pra-Pemrosesan & Indeks (`scripts/03_compute_indices_v2.py`)
* **Tindakan:** Memasukkan fungsi *Bicubic Interpolation* untuk Band SWIR-1 (20m $\rightarrow$ 10m) dan *Bilateral Edge-Preserving Filter* ($d=5, \sigma_{\text{color}}=0.05, \sigma_{\text{space}}=5.0$).
* **Kalkulasi Fitur:** Menghitung NDVI, LSWI, NDBI, BSI, dan **Tekstur Simpangan Baku Lokal NIR ($\sigma_{\text{NIR}}$)** menggunakan `scipy.ndimage.uniform_filter` dengan *window size* $5 \times 5$.

### Modul 2: Peningkatan Segmentasi & Logika Perubahan (`scripts/04_threshold_morphology_v2.py`)
* **Aturan Sawah Awal (2018):**
  * *Fase Vegetatif:* $(\text{NDVI} > 0.45) \land (\text{LSWI} > 0.18) \land (\sigma_{\text{NIR}} < 0.045)$
  * *Fase Genangan Subak:* $(0.10 < \text{NDVI} \le 0.45) \land (\text{LSWI} > 0.25) \land (\text{NDBI} < -0.10) \land (\sigma_{\text{NIR}} < 0.045)$
* **Aturan Target Konversi (Vila Tropis & Bangunan 2026):**
  * $\text{LostPaddy} = (\text{Sawah}_{2018} == 1) \land (\text{Sawah}_{2026} == 0)$
  * $\text{Konversi} = \text{LostPaddy} \land (\Delta \text{NDBI} > 0.10) \land (\Delta \text{LSWI} < -0.05)$
* **Pembersihan Morfologi:** 
  * Sawah: *Opening-Closing* Ellipse $3 \times 3$ + CCA Area Filter $\ge 15$ piksel ($1.500\text{ m}^2$).
  * Konversi/Bangunan: *Opening* Rectangular $2 \times 2$ (menjaga kavling vila kecil agar tidak terhapus).

### Modul 3: Vektorisasi Peta Interaktif & Zonal Statistik (`scripts/05_visualization_v2.py`)
* Mengonversi raster biner hasil konversi menjadi poligon vektor GeoJSON (`rasterio.features.shapes`).
* Melakukan *spatial join* dengan batas kecamatan di Kabupaten Badung untuk menghasilkan *breakdown* luas alih fungsi per kecamatan yang selaras dengan data resmi Dinas Pertanian.
* Menghasilkan peta *DualMap* Folium yang menampilkan *streaming* ESRI World Imagery beresolusi sub-meter di sisi kanan dan poligon merah interaktif ber-tooltip di sisi kiri.

### Modul 4: Integrasi Dashboard Streamlit (`app.py`)
* Menghubungkan *front-end* Streamlit yang sudah Anda miliki agar membaca hasil raster dan tabel CSV terbaru dari skrip v2.
* Menampilkan metrik KPI utama yang akurat (menampilkan luasan konversi yang realistis dan mendekati data BPS).
* Menyediakan tab perbandingan indeks spektral, grafik statistik per kecamatan, dan galeri visualisasi 6-panel.

---

## 4. Struktur Direktori Proyek Akhir

```
PRATUBES_BADUNG/
├── agents.md
├── implementation_plan_v2.md                 # Berkas dokumen plan ini
├── laporan.md                                
├── config.py                                 # Parameter ambang batas v2
├── requirements.txt                          # rasterio, numpy, scipy, opencv, streamlit, folium
├── app.py                                    # Dashboard Streamlit (terkoneksi v2)
│
├── scripts/
│   ├── 00_test_auth.py
│   ├── 01_download_boundary.py
│   ├── 02_download_sentinel.py
│   ├── 03_compute_indices_v2.py              # Bilateral, Bicubic, LSWI, Texture NIR
│   ├── 04_threshold_morphology_v2.py         # Multi-Rule Sawah + Delta NDBI/LSWI + Kernel 2x2
│   └── 05_visualization_v2.py                # Vektorisasi GeoJSON & Zonal Stats Kecamatan
│
├── data/
│   ├── boundary/
│   │   └── badung_kecamatan.geojson
│   ├── indices/
│   │   └── (ndvi, lswi, ndbi, bsi, texture_nir)
│   └── results/
│       ├── conversion_multiclass_morphed.tif
│       └── conversion_polygons.geojson       # Vektor poligon hasil v2
│
└── output/
    └── maps/
        ├── peta_interaktif_badung.html
        └── final_statistics_v2.csv           # Tabel statistik selaras data BPS
```

---

## 5. Checklist Eksekusi Integrasi
* [ ] **Langkah 1:** Perbarui `config.py` dengan parameter ambang batas algoritma v2 (`TH_SIGMA_NIR = 0.045`, `TH_LSWI = 0.18`, `DELTA_NDBI = 0.10`).
* [ ] **Langkah 2:** Jalankan `python scripts/03_compute_indices_v2.py` untuk menghasilkan raster fitur multispektral yang telah disaring dengan Bilateral Filter.
* [ ] **Langkah 3:** Jalankan `python scripts/04_threshold_morphology_v2.py` untuk mengeksekusi logika diferensial multitemporal dan morfologi kernel $2 \times 2$.
* [ ] **Langkah 4:** Jalankan `python scripts/05_visualization_v2.py` untuk memperbarui peta GeoJSON dan statistik kecamatan.
* [ ] **Langkah 5:** Jalankan perintah `streamlit run app.py` di terminal untuk melihat hasil dashboard interaktif dengan angka luasan yang akurat dan realistis.