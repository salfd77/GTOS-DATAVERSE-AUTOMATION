#!/usr/bin/env python3
"""
verify_gtos_data.py
Read-only verification + CSV export of the live GTOS data (the six tables).

- Confirms the seeded demo records exist and their lookups resolve.
- Prints a reporting-style summary (findings by severity, audit timeline,
  transformation input->output, state lifecycle).
- Exports one CSV per table (with human-readable choice/lookup labels via
  Dataverse FormattedValue annotations) so you can build Power BI Desktop from
  the files even if "Link to Fabric" isn't available yet.

Reuses the same auth as provision_gtos_dataverse.py (interactive device-code).
Nothing here writes to Dataverse.

Usage:
  python verify_gtos_data.py --interactive              # summary + CSV export
  python verify_gtos_data.py --interactive --no-export  # summary only
  python verify_gtos_data.py --interactive --out ./reporting_export
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests': python -m pip install -r requirements.txt")

DEFAULT_PUBLIC_CLIENT = "51f81489-12ee-4a9e-aaae-a2591f45987d"
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"
FORMATTED = 'odata.include-annotations="OData.Community.Display.V1.FormattedValue"'


def load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_token_interactive(tenant_id, resource, client_id=None):
    try:
        import msal
    except ImportError:
        sys.exit("Missing dependency 'msal': python -m pip install -r requirements.txt")
    authority = f"https://login.microsoftonline.com/{tenant_id or 'organizations'}"
    app = msal.PublicClientApplication(client_id or DEFAULT_PUBLIC_CLIENT, authority=authority)
    flow = app.initiate_device_flow(scopes=[f"{resource}/.default"])
    if "user_code" not in flow:
        raise RuntimeError("Failed to start device flow: " + json.dumps(flow, ensure_ascii=False))
    print("\n" + flow["message"] + "\n")
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


class Dataverse:
    def __init__(self, base_url, token):
        self.api = base_url.rstrip("/") + "/api/data/v9.2"
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Prefer": FORMATTED,
        })

    def entity_set_name(self, logical):
        url = f"{self.api}/EntityDefinitions(LogicalName='{logical}')?$select=EntitySetName"
        r = self.s.get(url)
        r.raise_for_status()
        return r.json()["EntitySetName"]

    def rows(self, entity_set, select=None, order=None):
        url = f"{self.api}/{entity_set}"
        params = []
        if select:
            params.append("$select=" + ",".join(select))
        if order:
            params.append("$orderby=" + order)
        if params:
            url += "?" + "&".join(params)
        out = []
        while url:
            r = self.s.get(url)
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return out


def fv(row, key):
    """Formatted (display) value if present, else raw."""
    ann = row.get(key + "@OData.Community.Display.V1.FormattedValue")
    return ann if ann is not None else row.get(key)


def main():
    ap = argparse.ArgumentParser(description="Verify + export live GTOS data (read-only).")
    ap.add_argument("--schema", default=str(Path(__file__).with_name("schema.json")))
    ap.add_argument("--interactive", action="store_true", help="Sign in as yourself (device code).")
    ap.add_argument("--no-export", action="store_true", help="Print summary only; skip CSV export.")
    ap.add_argument("--out", default="reporting_export", help="Folder for CSV export.")
    args = ap.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))
    url = os.environ.get("DATAVERSE_URL")
    tenant = os.environ.get("TENANT_ID")
    client_id = os.environ.get("CLIENT_ID")
    if not url or "YOUR_ORG" in url:
        sys.exit("DATAVERSE_URL is not set in .env (e.g. https://org331e3f60.crm.dynamics.com).")

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    prefix = schema.get("publisherPrefix", "gtos")

    tenant_arg = tenant if (tenant and tenant != PLACEHOLDER) else None
    client_arg = client_id if (client_id and client_id != PLACEHOLDER) else None
    print("Interactive sign-in (device code):")
    token = get_token_interactive(tenant_arg, url, client_id=client_arg)
    dv = Dataverse(url, token)
    print("Authenticated.\n")

    # Resolve columns per table from schema (logical names) + primary + lookups.
    tables = {}
    for t in schema["tables"]:
        logical = f"{prefix}_{t['schemaName']}".lower()
        cols = [f"{prefix}_name"]
        cols += [f"{prefix}_{c['schemaName']}".lower() for c in t.get("columns", [])]
        tables[t["schemaName"]] = {"logical": logical, "cols": cols,
                                   "set": dv.entity_set_name(logical)}
    # Lookup columns (from relationships) live on the referencing table.
    for rel in schema.get("relationships", []):
        ref = rel["referencing"]
        lookup_logical = f"_{prefix}_{rel['lookupSchemaName']}_value".lower()
        tables[ref]["cols"].append(lookup_logical)

    print("== GTOS live data verification ==\n")
    total = 0
    data = {}
    for name, meta in tables.items():
        try:
            rows = dv.rows(meta["set"], select=meta["cols"], order=f"{prefix}_name asc")
        except requests.HTTPError:
            # Fall back to no $select if a column name is off.
            rows = dv.rows(meta["set"], order=f"{prefix}_name asc")
        data[name] = rows
        total += len(rows)
        print(f"  {meta['set']:<24} {len(rows):>3} row(s)")
    print(f"  {'TOTAL':<24} {total:>3} row(s)\n")

    # --- reporting-style summary ---
    findings = data.get("Finding", [])
    if findings:
        by_sev = {}
        open_cnt = 0
        for f in findings:
            sev = fv(f, f"{prefix}_severity")
            by_sev[sev] = by_sev.get(sev, 0) + 1
            if not f.get(f"{prefix}_accepted"):
                open_cnt += 1
        print("Findings by severity: " + ", ".join(f"{k}={v}" for k, v in sorted(by_sev.items())))
        print(f"Open (not accepted): {open_cnt} / {len(findings)}\n")

    audits = data.get("Audit", [])
    if audits:
        print("Audit timeline:")
        for a in sorted(audits, key=lambda r: r.get(f"{prefix}_occurredon", "")):
            when = fv(a, f"{prefix}_occurredon")
            print(f"  {when}  {a.get(f'{prefix}_name')}")
        print()

    trans = data.get("Transformation", [])
    if trans:
        print("Transformations:")
        for t in trans:
            ins = fv(t, f"_{prefix}_inputstate_value")
            outs = fv(t, f"_{prefix}_outputstate_value")
            st = fv(t, f"{prefix}_status")
            print(f"  {t.get(f'{prefix}_name')}  [{st}]  {ins} -> {outs}")
        print()

    states = data.get("State", [])
    if states:
        print("States:")
        for s in states:
            print(f"  {s.get(f'{prefix}_name')}  "
                  f"[{fv(s, f'{prefix}_lifecyclestage')}/{fv(s, f'{prefix}_status')}]")
        print()

    # --- CSV export ---
    if not args.no_export:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, meta in tables.items():
            rows = data.get(name, [])
            path = out / f"{meta['set']}.csv"
            fieldnames = list(meta["cols"])
            with path.open("w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(fieldnames)
                for r in rows:
                    w.writerow([fv(r, c) for c in fieldnames])
        print(f"Exported {len(tables)} CSV file(s) to {out.resolve()}")
        print("Open Power BI Desktop -> Get data -> Text/CSV -> pick this folder's files.")

    print("\nDone (read-only). No changes were written.")


if __name__ == "__main__":
    main()
