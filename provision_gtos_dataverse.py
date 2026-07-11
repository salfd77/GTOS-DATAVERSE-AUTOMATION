#!/usr/bin/env python3
"""
provision_gtos_dataverse.py
Automatically creates the GTOS tables + columns (+ relationships) in a Microsoft
Dataverse environment from schema.json, via the Dataverse Web API.

Design goals (aligned with GTOS governance):
- Deterministic, idempotent (safe to re-run: existing tables/columns/relationships are skipped).
- Least privilege: uses a dedicated app registration; you grant only what it needs.
- Evidence: prints every action; supports --whatif (dry run) to preview with no writes.

Auth: OAuth2 client credentials (MSAL) -> Dataverse Web API.

Usage:
  python provision_gtos_dataverse.py --whatif        # preview only, no changes
  python provision_gtos_dataverse.py                 # create tables/columns/relationships
  python provision_gtos_dataverse.py --schema schema.json

Required environment variables (or a .env file next to this script):
  DATAVERSE_URL     e.g. https://org331e3f60.crm.dynamics.com
  TENANT_ID         Entra tenant (GUID)
  CLIENT_ID         App registration (application) ID
  CLIENT_SECRET     App registration client secret
Optional:
  SOLUTION_NAME     unique name of an unmanaged solution to add objects to
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests': pip install -r requirements.txt")


# ----------------------------- helpers -------------------------------------

def load_dotenv(path: Path):
    """Minimal .env loader (no external dependency)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def label(text, lang):
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.Label",
        "LocalizedLabels": [{
            "@odata.type": "Microsoft.Dynamics.CRM.LocalizedLabel",
            "Label": text,
            "LanguageCode": lang,
        }],
    }


# Well-known Microsoft first-party PUBLIC client used by Dataverse sample tools.
# Lets you sign in as YOURSELF (delegated) with no app registration / secret.
DEFAULT_PUBLIC_CLIENT = "51f81489-12ee-4a9e-aaae-a2591f45987d"


def _import_msal():
    try:
        import msal
        return msal
    except ImportError:
        sys.exit("Missing dependency 'msal' (needed for live auth): "
                 "python -m pip install -r requirements.txt")


def get_token_client_credentials(tenant_id, client_id, client_secret, resource):
    """App-only auth (requires an app registration + secret + app user)."""
    msal = _import_msal()
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=[f"{resource}/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


def get_token_interactive(tenant_id, resource, client_id=None):
    """Delegated device-code auth: sign in as yourself. No app registration needed."""
    msal = _import_msal()
    authority = f"https://login.microsoftonline.com/{tenant_id or 'organizations'}"
    app = msal.PublicClientApplication(client_id or DEFAULT_PUBLIC_CLIENT, authority=authority)
    scopes = [f"{resource}/.default"]
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise RuntimeError("Failed to start device flow: " + json.dumps(flow, ensure_ascii=False))
    print("\n" + flow["message"] + "\n")  # e.g. go to microsoft.com/devicelogin and enter CODE
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Auth failed: {result.get('error')}: {result.get('error_description')}")
    return result["access_token"]


# ----------------------- metadata payload builders -------------------------

def build_string(col, prefix, lang):
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.StringAttributeMetadata",
        "SchemaName": f"{prefix}_{col['schemaName']}",
        "MaxLength": col.get("maxLength", 200),
        "FormatName": {"Value": "Text"},
        "RequiredLevel": {"Value": "None"},
        "DisplayName": label(col["displayName"], lang),
    }


def build_memo(col, prefix, lang):
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.MemoAttributeMetadata",
        "SchemaName": f"{prefix}_{col['schemaName']}",
        "MaxLength": col.get("maxLength", 4000),
        "Format": "TextArea",
        "RequiredLevel": {"Value": "None"},
        "DisplayName": label(col["displayName"], lang),
    }


def build_datetime(col, prefix, lang):
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.DateTimeAttributeMetadata",
        "SchemaName": f"{prefix}_{col['schemaName']}",
        "Format": "DateAndTime",
        "RequiredLevel": {"Value": "None"},
        "DisplayName": label(col["displayName"], lang),
    }


def build_boolean(col, prefix, lang):
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.BooleanAttributeMetadata",
        "SchemaName": f"{prefix}_{col['schemaName']}",
        "RequiredLevel": {"Value": "None"},
        "DisplayName": label(col["displayName"], lang),
        "OptionSet": {
            "@odata.type": "Microsoft.Dynamics.CRM.BooleanOptionSetMetadata",
            "TrueOption": {"Value": 1, "Label": label("Yes", lang)},
            "FalseOption": {"Value": 0, "Label": label("No", lang)},
        },
    }


def build_choice(col, prefix, lang):
    options = []
    for i, opt in enumerate(col["options"]):
        options.append({
            "Value": 100000000 + i,
            "Label": label(opt, lang),
        })
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.PicklistAttributeMetadata",
        "SchemaName": f"{prefix}_{col['schemaName']}",
        "RequiredLevel": {"Value": "None"},
        "DisplayName": label(col["displayName"], lang),
        "OptionSet": {
            "@odata.type": "Microsoft.Dynamics.CRM.OptionSetMetadata",
            "IsGlobal": False,
            "OptionSetType": "Picklist",
            "Options": options,
        },
    }


BUILDERS = {
    "string": build_string,
    "memo": build_memo,
    "datetime": build_datetime,
    "boolean": build_boolean,
    "choice": build_choice,
}


def build_column(col, prefix, lang):
    fn = BUILDERS.get(col["type"])
    if not fn:
        raise ValueError(f"Unsupported column type: {col['type']}")
    return fn(col, prefix, lang)


def build_entity(table, prefix, lang):
    pk = table["primaryName"]
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.EntityMetadata",
        "SchemaName": f"{prefix}_{table['schemaName']}",
        "DisplayName": label(table["displayName"], lang),
        "DisplayCollectionName": label(table["displayCollectionName"], lang),
        "Description": label(table.get("description", ""), lang),
        "OwnershipType": "UserOwned",
        "HasActivities": False,
        "HasNotes": False,
        "IsActivity": False,
        "Attributes": [{
            "@odata.type": "Microsoft.Dynamics.CRM.StringAttributeMetadata",
            "SchemaName": f"{prefix}_{pk['schemaName']}",
            "MaxLength": pk.get("maxLength", 200),
            "FormatName": {"Value": "Text"},
            "RequiredLevel": {"Value": "ApplicationRequired"},
            "DisplayName": label(pk["displayName"], lang),
            "IsPrimaryName": True,
        }],
    }


def build_relationship(rel, prefix, lang):
    """Build a One-to-Many (lookup) relationship metadata payload.

    schema.json relationship shape:
      { "schemaName": "gtos_transformation_inputstate",
        "referenced": "State",          # the "one" side (parent) table schemaName (no prefix)
        "referencing": "Transformation",# the "many" side (child) table schemaName (no prefix)
        "lookupSchemaName": "InputState",       # lookup column schemaName (no prefix)
        "lookupDisplayName": "Input State",
        "lookupDescription": "..." }
    """
    referenced = f"{prefix}_{rel['referenced']}".lower()
    referencing = f"{prefix}_{rel['referencing']}".lower()
    lookup_schema = f"{prefix}_{rel['lookupSchemaName']}"
    return {
        "@odata.type": "Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata",
        "SchemaName": rel["schemaName"],
        "ReferencedEntity": referenced,
        "ReferencingEntity": referencing,
        "CascadeConfiguration": {
            "Assign": "NoCascade",
            "Delete": "RemoveLink",
            "Merge": "NoCascade",
            "Reparent": "NoCascade",
            "Share": "NoCascade",
            "Unshare": "NoCascade",
        },
        "Lookup": {
            "@odata.type": "Microsoft.Dynamics.CRM.LookupAttributeMetadata",
            "SchemaName": lookup_schema,
            "DisplayName": label(rel.get("lookupDisplayName", rel["lookupSchemaName"]), lang),
            "Description": label(rel.get("lookupDescription", ""), lang),
            "RequiredLevel": {"Value": "None"},
        },
    }


# ------------------------------- API client --------------------------------

class Dataverse:
    def __init__(self, base_url, token, solution=None, whatif=False):
        self.api = base_url.rstrip("/") + "/api/data/v9.2"
        self.whatif = whatif
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        })
        if solution:
            self.s.headers["MSCRM.SolutionUniqueName"] = solution

    def entity_exists(self, logical_name):
        url = f"{self.api}/EntityDefinitions(LogicalName='{logical_name}')?$select=LogicalName"
        r = self.s.get(url)
        return r.status_code == 200

    def attribute_exists(self, logical_name, attr_logical):
        url = (f"{self.api}/EntityDefinitions(LogicalName='{logical_name}')"
               f"/Attributes(LogicalName='{attr_logical}')?$select=LogicalName")
        r = self.s.get(url)
        return r.status_code == 200

    def relationship_exists(self, schema_name):
        """True if a relationship with this SchemaName already exists (any type)."""
        url = (f"{self.api}/RelationshipDefinitions"
               f"?$select=SchemaName&$filter=SchemaName eq '{schema_name}'")
        r = self.s.get(url)
        if r.status_code != 200:
            return False
        try:
            return bool(r.json().get("value"))
        except ValueError:
            return False

    def _post_with_retry(self, url, payload, what):
        """POST that retries on customization-lock / throttling (429, 0x80071151)."""
        max_attempts = 8
        delay = 10
        for attempt in range(1, max_attempts + 1):
            r = self.s.post(url, data=json.dumps(payload))
            if r.status_code in (200, 201, 204):
                return r
            locked = (r.status_code == 429) or ("0x80071151" in r.text) or \
                     ("CustomizationLockException" in r.text) or ("another [Import]" in r.text)
            if locked and attempt < max_attempts:
                print(f"    [locked] {what}: environment busy (attempt {attempt}/{max_attempts}). "
                      f"Waiting {delay}s and retrying ...")
                time.sleep(delay)
                delay = min(delay + 10, 60)
                continue
            raise RuntimeError(f"{what} failed [{r.status_code}]: {r.text}")
        raise RuntimeError(f"{what} failed after {max_attempts} attempts (environment stayed locked).")

    def create_entity(self, payload):
        if self.whatif:
            return "whatif"
        r = self._post_with_retry(f"{self.api}/EntityDefinitions", payload, "Create entity")
        return r.headers.get("OData-EntityId", "created")

    def create_attribute(self, logical_name, payload):
        if self.whatif:
            return "whatif"
        url = f"{self.api}/EntityDefinitions(LogicalName='{logical_name}')/Attributes"
        self._post_with_retry(url, payload, "Create attribute")
        return "created"

    def create_relationship(self, payload):
        if self.whatif:
            return "whatif"
        self._post_with_retry(f"{self.api}/RelationshipDefinitions", payload, "Create relationship")
        return "created"


# --------------------------------- main ------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Provision GTOS Dataverse tables from schema.json")
    ap.add_argument("--schema", default=str(Path(__file__).with_name("schema.json")))
    ap.add_argument("--whatif", action="store_true", help="Preview actions without writing")
    ap.add_argument("--interactive", action="store_true",
                    help="Sign in as yourself (device code). No app registration/secret needed.")
    args = ap.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))

    url = os.environ.get("DATAVERSE_URL")
    tenant = os.environ.get("TENANT_ID")
    client_id = os.environ.get("CLIENT_ID")
    secret = os.environ.get("CLIENT_SECRET")
    solution = os.environ.get("SOLUTION_NAME") or None

    PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

    if not args.whatif:
        if not url or "YOUR_ORG" in (url or ""):
            sys.exit("DATAVERSE_URL is not set. Edit .env and set your environment URL, "
                     "e.g. https://org331e3f60.crm.dynamics.com")
        if args.interactive:
            # Only the environment URL is required; you sign in as yourself.
            pass
        else:
            missing = [k for k, v in {
                "TENANT_ID": tenant, "CLIENT_ID": client_id, "CLIENT_SECRET": secret,
            }.items() if not v or v == PLACEHOLDER or "your-app" in str(v)]
            if missing:
                sys.exit("These still hold placeholder/empty values in .env: "
                         + ", ".join(missing)
                         + "\nEither fill them with real app-registration values, "
                           "or run with --interactive to sign in as yourself (no app registration).")

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    prefix = schema.get("publisherPrefix", "gtos")
    lang = schema.get("languageCode", 1033)
    solution = solution or (schema.get("solutionUniqueName") or None)

    mode = "DRY RUN (--whatif): no changes will be written" if args.whatif else "LIVE: creating objects"
    print(f"== GTOS Dataverse provisioning ==\nMode: {mode}\nPrefix: {prefix}_\n")

    dv = None
    if not args.whatif:
        if args.interactive:
            print("Interactive sign-in (device code). Follow the instructions below:")
            # Ignore placeholder/empty tenant & client so we fall back to the
            # multi-tenant 'organizations' authority and the default public client.
            tenant_arg = tenant if (tenant and tenant != PLACEHOLDER) else None
            client_arg = client_id if (client_id and client_id != PLACEHOLDER) else None
            token = get_token_interactive(tenant_arg, url, client_id=client_arg)
        else:
            print("Authenticating to Dataverse (app-only) ...")
            token = get_token_client_credentials(tenant, client_id, secret, url)
        dv = Dataverse(url, token, solution=solution, whatif=False)
        print("Authenticated.\n")
    else:
        dv = Dataverse("https://example.crm.dynamics.com", "dry", solution=solution, whatif=True)

    created_tables = 0
    created_cols = 0

    for table in schema["tables"]:
        ent_logical = f"{prefix}_{table['schemaName']}".lower()
        entity_payload = build_entity(table, prefix, lang)

        exists = (not args.whatif) and dv.entity_exists(ent_logical)
        if exists:
            print(f"[skip] table {ent_logical} already exists")
        else:
            print(f"[create] table {ent_logical}  (primary: {prefix}_{table['primaryName']['schemaName']})")
            dv.create_entity(entity_payload)
            created_tables += 1
            if not args.whatif:
                time.sleep(2)  # let metadata settle before adding columns

        for col in table["columns"]:
            attr_logical = f"{prefix}_{col['schemaName']}".lower()
            if (not args.whatif) and exists and dv.attribute_exists(ent_logical, attr_logical):
                print(f"    [skip] column {attr_logical} exists")
                continue
            print(f"    [create] column {attr_logical}  ({col['type']})")
            dv.create_attribute(ent_logical, build_column(col, prefix, lang))
            created_cols += 1
            if not args.whatif:
                time.sleep(1)

    # ---- relationships (lookups) -----------------------------------------
    # Created after all tables/columns so both endpoints are guaranteed to exist.
    created_rels = 0
    for rel in schema.get("relationships", []):
        rel_schema = rel["schemaName"]
        exists_rel = (not args.whatif) and dv.relationship_exists(rel_schema)
        if exists_rel:
            print(f"[skip] relationship {rel_schema} already exists")
            continue
        print(f"[create] relationship {rel_schema}  "
              f"({prefix}_{rel['referencing']} -> {prefix}_{rel['referenced']} "
              f"as {prefix}_{rel['lookupSchemaName']})")
        dv.create_relationship(build_relationship(rel, prefix, lang))
        created_rels += 1
        if not args.whatif:
            time.sleep(2)  # relationship publish can briefly lock customization

    print(f"\nDone. Tables created: {created_tables}, columns created: {created_cols}, "
          f"relationships created: {created_rels}.")
    if args.whatif:
        print("This was a dry run. Re-run without --whatif to apply.")


if __name__ == "__main__":
    main()
