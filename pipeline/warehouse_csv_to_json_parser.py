import csv
import json
from typing import List, Dict

BOOLEAN_FIELDS = ("Available", "Inbound")        # optional yes/no flags
INTEGER_FIELDS = ("Quantity", "Shelf Level")     # numeric fields converted to integers


def parse_warehouse_csv_to_json(csv_file_path: str, json_file_path: str) -> None:
    """
    Parse a WMS stock export (CSV) and convert it to JSON: one object per stock record.

    Expected columns: Code, Area, Shelf Unit, Shelf Level, Quantity. Optional yes/no columns
    (Available, Inbound) are converted to booleans; numeric fields to integers; empty fields to null.
    """
    data: List[Dict] = []
    with open(csv_file_path, mode='r', encoding='utf-8-sig') as csv_file:
        for row in csv.DictReader(csv_file):
            record = {}
            for key, value in row.items():
                key = (key or "").strip()
                value = (value or "").strip()
                if not key:
                    continue
                if value == "":
                    record[key] = None
                elif key in BOOLEAN_FIELDS:
                    record[key] = value.lower() in ("yes", "true", "1")
                elif key in INTEGER_FIELDS:
                    try:
                        record[key] = int(float(value))
                    except ValueError:
                        record[key] = value
                else:
                    record[key] = value
            data.append(record)

    with open(json_file_path, mode='w', encoding='utf-8') as json_file:
        json.dump(data, json_file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Convert a warehouse (WMS) CSV export to JSON.")
    ap.add_argument("csv_file"); ap.add_argument("json_file")
    a = ap.parse_args()
    parse_warehouse_csv_to_json(a.csv_file, a.json_file)
