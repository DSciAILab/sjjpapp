import json, csv

with open('schools.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

with open('schools.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['id', 'nome', 'city', 'coaches'])
    for item in data:
        writer.writerow([
            item['id'],
            item['nome'],
            item.get('city', ''),
            str(item.get('coaches', []))
        ])