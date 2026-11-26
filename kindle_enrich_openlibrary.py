
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data" / "kindle_plus_mexico.json"

TEST_LIMIT = 5

books = json.loads(CATALOG.read_text(encoding="utf-8"))

# Elegimos registros con ASIN alfanumérico
candidates = [
    b for b in books
    if len(str(b.get("asin", ""))) == 10
][:TEST_LIMIT]

# Control positivo: ISBN conocido, para comprobar
# que la API responde correctamente.
tests = [
    ("ISBN", "0590353427", "Control ISBN")
]

tests += [
    ("ASIN", b["asin"], b["title"])
    for b in candidates
]

for identifier_type, identifier, title in tests:
    params = urlencode({
        "bibkeys": f"{identifier_type}:{identifier}",
        "format": "json",
        "jscmd": "data"
    })

    url = f"https://openlibrary.org/api/books?{params}"

    print(f"\n📖 {title[:75]}")
    print(f"   {identifier_type}: {identifier}")

    request = Request(
        url,
        headers={
            "User-Agent": "KindleCatalogResearch/1.0",
            "Accept": "application/json"
        }
    )

    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)

        if not data:
            print("   ❌ Sin resultados")
            continue

        for key, record in data.items():
            authors = [
                a.get("name")
                for a in record.get("authors", [])
                if a.get("name")
            ]

            print(f"   ✅ {record.get('title')}")
            print(f"   ✍️ {', '.join(authors) or 'Sin autor'}")
            print(f"   🔗 {record.get('url')}")

    except Exception as error:
        print(f"   ⚠️ {error}")

    time.sleep(2)
