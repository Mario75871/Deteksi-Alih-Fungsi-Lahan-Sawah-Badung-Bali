import requests

url = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
query = (
    "Collection/Name eq 'SENTINEL-2' and "
    "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
    "contains(Name, '50LKR') and "
    "ContentDate/Start gt 2026-10-01T00:00:00.000Z and ContentDate/Start lt 2026-10-31T23:59:59.000Z"
)
params = {
    "$filter": query,
    "$top": 30,
    "$select": "Name,ContentDate,Attributes"
}
try:
    r = requests.get(url, params=params, timeout=30).json()
    products = r.get("value", [])
    print(f"Ditemukan {len(products)} produk untuk tile 50LKR di Oktober 2026:")
    for p in products:
        name = p["Name"]
        date = p["ContentDate"]["Start"][:10]
        # Cari cloud cover di attributes
        cloud = None
        for a in p.get("Attributes", []):
            if a.get("Name") == "cloudCover":
                cloud = a.get("Value")
        print(f"  Tanggal: {date} | Cloud: {cloud}% | File: {name[:50]}")
except Exception as e:
    print("Error:", e)
