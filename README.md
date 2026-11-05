# 🌾 Deteksi & Kuantifikasi Alih Fungsi Lahan Sawah Menjadi Vila Tropis di Kabupaten Badung, Bali (2018 - 2026)

Proyek Pengolahan Citra Digital (PCD) untuk mendeteksi, mengkuantifikasi, dan memetakan alih fungsi lahan sawah menjadi kawasan terbangun permanen dan kavling vila tropis di seluruh 6 kecamatan Kabupaten Badung, Bali periode **Oktober 2018** hingga **Oktober 2026**.

Menggunakan citra satelit **Sentinel-2 Multi-temporal (10m)** berbasis **100% Pengolahan Citra Digital Klasik (PCD Murni tanpa Machine Learning)** dan divalidasi dengan citra resolusi tinggi **ESRI World Imagery (sub-meter)** secara streaming.

---

## 🚀 Fitur Utama & Inovasi Algoritma PCD (v3.0)

1. **Bilateral Edge-Preserving Filter ($d=5, \sigma_{\text{color}}=0.05, \sigma_{\text{space}}=5.0$):**  
   Menghaluskan derau multispektral tanpa mengaburkan batas pematang sawah dan kontur kavling bangunan.
2. **Integrasi LSWI (*Land Surface Water Index*):**  
   Mendeteksi kelembapan kanopi dan fase genangan air subak secara akurat.
3. **Segmentasi Sawah 2 Fase:**  
   Mendeteksi fase vegetatif hijau lebat maupun fase genangan air/olah tanah bajak sawah.
4. **Multitemporal Differential Change Detection untuk Vila Tropis:**  
   Menangkap fenomena pengeringan permanen irigasi sawah menjadi kavling properti $(\Delta NDBI > 0.10 \land \Delta LSWI < -0.05)$.
5. **Morfologi Adaptif Rectangular $2 \times 2$ & Connected Component Analysis:**  
   Mempertahankan kavling vila kecil baru tanpa memicu false positive.
6. **Dashboard Interaktif Berbasis Streamlit:**  
   Visualisasi peta Folium interaktif, komparasi dual map, ringkasan statistik zonal per kecamatan, dan galeri indeks spektral.

---

## 📊 Hasil Analisis Geospasial & Kuantitatif

* **Sawah Baseline (2018):** 13.194,69 Ha
* **Sawah Bertahan (2026):** 8.374,22 Ha
* **Sawah Hilang (*Lost Paddy*):** 6.114,04 Ha
* **Total Alih Fungsi Terkonfirmasi:** **4.199,80 Ha** (4.496 klaster kavling)
  * Bangunan Permanen / Vila Tropis: 4.193,08 Ha
  * Lahan Konstruksi / Urukan Baru: 6,72 Ha

### Distribusi per Kecamatan:
| Kecamatan | Bangunan / Vila (Ha) | Lahan Konstruksi (Ha) | Total (Ha) | Proporsi (%) | Jumlah Klaster |
|---|:---:|:---:|:---:|:---:|:---:|
| **Petang** | 1.968,83 | 3,39 | **1.972,22** | 47,0% | 1.827 |
| **Abiansemal** | 1.281,25 | 2,34 | **1.283,59** | 30,6% | 1.212 |
| **Mengwi** | 798,80 | 0,33 | **799,13** | 19,0% | 1.066 |
| **Kuta Utara** | 113,93 | 0,66 | **114,59** | 2,7% | 273 |
| **Kuta Selatan** | 21,21 | 0,00 | **21,21** | 0,5% | 90 |
| **Kuta** | 8,06 | 0,00 | **8,06** | 0,2% | 24 |

### Evaluasi Akurasi (100 Titik Stratified Random Sampling):
* **Overall Accuracy (OA):** **88,00%**
* **User's Accuracy (Precision):** **84,00%**
* **Producer's Accuracy (Recall):** **91,30%**
* **Cohen's Kappa Coefficient ($\kappa$):** **0,7600** (*Substantial Agreement*)

---

## 📁 Struktur Direktori

```text
PRATUBES_BADUNG/
├── data/
│   ├── boundary/               # Batas administrasi Kabupaten Badung & 6 Kecamatan (GeoJSON)
│   ├── processed/              # Citra Sentinel-2 Composite (10m)
│   ├── indices/                # GeoTIFF indeks spektral (NDVI, LSWI, NDBI, NDWI, BSI, σ_NIR)
│   └── results/                # Poligon vektor alih fungsi (GeoJSON)
├── output/
│   ├── maps/                   # Peta interaktif HTML (Folium & DualMap) & visualisasi PNG
│   └── statistics/             # Laporan akurasi & statistik zonal per kecamatan (CSV)
├── scripts/
│   ├── 00_test_auth.py         # Autentikasi CDSE openEO
│   ├── 01_download_boundary.py # Unduh batas administrasi
│   ├── 02_download_sentinel.py # Pengambilan citra Sentinel-2 & komposit median
│   ├── 03_compute_indices_v2.py# Bilateral Filter & perhitungan 6 indeks spektral
│   ├── 04_threshold_morphology_v2.py # Segmentasi sawah, deteksi vila & morfologi
│   ├── 05_visualization_v2.py  # Vektorisasi GeoJSON & pembuatan peta interaktif
│   └── 06_accuracy_assessment.py # Evaluasi akurasi 100 titik acak & matriks konfusi
├── app.py                      # Aplikasi Web Dashboard Interaktif (Streamlit)
├── config.py                   # Konfigurasi koordinat, band, dan parameter
├── requirements.txt            # Dependensi Python
├── start.bat                   # Script peluncur satu-klik dashboard Streamlit
└── README.md
```

---

## 🛠️ Instalasi & Menjalankan Aplikasi

### 1. Kloning Repositori
```bash
git clone https://github.com/<username>/<nama-repo>.git
cd <nama-repo>
```

### 2. Buat & Aktifkan Virtual Environment (Opsional tapi Direkomendasikan)
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### 3. Pasang Dependensi
```bash
pip install -r requirements.txt
```

### 4. Jalankan Dashboard Web Streamlit
Cukup klik dua kali `start.bat` (Windows) atau ketik di terminal:
```bash
streamlit run app.py
```
Akses dashboard di browser Anda pada alamat `http://localhost:8501`.
