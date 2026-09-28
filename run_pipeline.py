"""
DTconnector - run the whole integration pipeline in one command.

    python run_pipeline.py --production examples/production_example.xlsx \
                           --warehouse examples/warehouse_example.csv --out output

Steps: spreadsheet -> JSON -> flattened JSON -> Plant Simulation XML (production feed),
       WMS CSV -> JSON -> Plant Simulation XML (warehouse feed).
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "pipeline"))

from excel_to_json_parser import excel_to_json_converter          # noqa: E402
from flatten_tasks import flatten_json_file                        # noqa: E402
from warehouse_csv_to_json_parser import parse_warehouse_csv_to_json  # noqa: E402
from json_to_xml_with_config import json_to_xml_with_config        # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--production", help="production/task spreadsheet (.xlsx)")
    ap.add_argument("--warehouse", help="warehouse stock export (.csv)")
    ap.add_argument("--out", default="output", help="output folder (default: output)")
    ap.add_argument("--json-config", default=str(HERE / "pipeline" / "to_json_config.yaml"))
    ap.add_argument("--xml-config", default=str(HERE / "pipeline" / "to_xml_config.yaml"))
    a = ap.parse_args()
    if not a.production and not a.warehouse:
        ap.error("give at least one of --production / --warehouse")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.production:
        prod_json, flat_json, prod_xml = out / "production.json", out / "production_flattened.json", out / "production.xml"
        excel_to_json_converter(a.production, str(prod_json), a.json_config)
        flatten_json_file(str(prod_json), str(flat_json))
        json_to_xml_with_config(str(flat_json), str(prod_xml), a.xml_config)
        print(f"Production feed: {prod_xml}")

    if a.warehouse:
        wh_json, wh_xml = out / "warehouse.json", out / "warehouse.xml"
        parse_warehouse_csv_to_json(a.warehouse, str(wh_json))
        json_to_xml_with_config(str(wh_json), str(wh_xml), a.xml_config)
        print(f"Warehouse feed: {wh_xml}")


if __name__ == "__main__":
    main()
