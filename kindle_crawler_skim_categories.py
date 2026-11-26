import json
from pathlib import Path

data = Path("data")

categories = json.loads(
    (data / "amazon_categories.json").read_text(encoding="utf-8")
)

main_categories = [
    {
        "id": category["id"],
        "name": category["name"],
        "url": category["url"]
    }
    for category in categories
    if category.get("depth") == 1
]

output = data / "amazon_main_categories.json"
output.write_text(
    json.dumps(main_categories, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"Categorías principales: {len(main_categories)}")
for category in main_categories:
    print(f"• {category['name']}")