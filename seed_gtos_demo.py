#!/usr/bin/env python3
"""
seed_gtos_demo.py
Populate the six provisioned GTOS tables with a small, realistic DEMO dataset so
the Fabric / Power BI dashboards (see docs/reporting/) light up with data.

This is OPTIONAL and clearly-labeled demo content. It is:
- Idempotent: records are matched by their primary name; existing ones are skipped.
- Reversible: run with --purge to delete exactly the demo records this script creates.
- Evidence-first: --whatif previews every write with no changes.

It reuses the same auth as provision_gtos_dataverse.py (interactive device-code by
default, or app-only when credentials are present). Choice option values are read
from schema.json so they always match what was provisioned.

Usage:
  python seed_gtos_demo.py --interactive --whatif   # preview (recommended first)
  python seed_gtos_demo.py --interactive            # create the demo records
  python seed_gtos_demo.py --interactive --purge    # delete the demo records
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests': python -m pip install -r requirements.txt")

DEFAULT_PUBLIC_CLIENT = "51f81489-12ee-4a9e-aaae-a2591f45987d"
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


# ------------------------------- helpers -----------------------------------

def load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _import_msal():
    try:
        import msal
        return msal
    except ImportError:
        sys.exit("Missing dependency 'msal': python -m pip install -r requirements.txt")


def get_token_interactive(tenant_id, resource, client_id=None):
    msal = _import_msal()
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


def get_token_client_credentials(tenant_id, client_id, client_secret, resource):
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


# ------------------------------ API client ---------------------------------

class Dataverse:
    def __init__(self, base_url, token, whatif=False):
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
        self._entity_set = {}
        self._nav_prop = {}

    def entity_set_name(self, logical):
        if logical not in self._entity_set:
            url = f"{self.api}/EntityDefinitions(LogicalName='{logical}')?$select=EntitySetName"
            r = self.s.get(url)
            r.raise_for_status()
            self._entity_set[logical] = r.json()["EntitySetName"]
        return self._entity_set[logical]

    def nav_property(self, rel_schema):
        """ReferencingEntityNavigationPropertyName for a 1:N relationship (used for @odata.bind)."""
        if rel_schema not in self._nav_prop:
            url = (f"{self.api}/RelationshipDefinitions(SchemaName='{rel_schema}')"
                   "/Microsoft.Dynamics.CRM.OneToManyRelationshipMetadata"
                   "?$select=ReferencingEntityNavigationPropertyName")
            r = self.s.get(url)
            r.raise_for_status()
            self._nav_prop[rel_schema] = r.json()["ReferencingEntityNavigationPropertyName"]
        return self._nav_prop[rel_schema]

    def find_by_name(self, entity_set, name):
        safe = name.replace("'", "''")
        url = f"{self.api}/{entity_set}?$filter=gtos_name eq '{safe}'&$top=1"
        r = self.s.get(url)
        r.raise_for_status()
        vals = r.json().get("value", [])
        if not vals:
            return None
        row = vals[0]
        idfield = next((k for k in row if k.endswith("id") and k.startswith("gtos_")), None)
        return row.get(idfield) if idfield else None

    def create(self, entity_set, payload):
        if self.whatif:
            return "whatif"
        r = self.s.post(f"{self.api}/{entity_set}", data=json.dumps(payload))
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"Create in {entity_set} failed [{r.status_code}]: {r.text}")
        loc = r.headers.get("OData-EntityId", "")
        return loc.split("(")[-1].rstrip(")") if "(" in loc else "created"

    def delete(self, entity_set, record_id):
        if self.whatif:
            return
        r = self.s.delete(f"{self.api}/{entity_set}({record_id})")
        if r.status_code not in (200, 204):
            raise RuntimeError(f"Delete {entity_set}({record_id}) failed [{r.status_code}]: {r.text}")


# --------------------------- demo data model -------------------------------

def choice_values(schema):
    """Map (table_schemaName, column_schemaName, option_label) -> integer option value."""
    prefix = schema.get("publisherPrefix", "gtos")
    out = {}
    for t in schema["tables"]:
        for c in t.get("columns", []):
            if c.get("type") == "choice":
                for i, opt in enumerate(c["options"]):
                    out[(t["schemaName"], c["schemaName"], opt)] = 100000000 + i
    out["_prefix"] = prefix
    return out


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_demo(schema, owner_upn):
    """Return an ordered list of demo records. Lookups reference earlier records by name."""
    cv = choice_values(schema)
    now = datetime.now(timezone.utc)

    def opt(table, col, val):
        return cv[(table, col, val)]

    states = [
        {"table": "State", "name": "S1 - Draft Charter",
         "fields": {"gtos_lifecyclestage": opt("State", "LifecycleStage", "Requirements"),
                    "gtos_status": opt("State", "Status", "Superseded"),
                    "gtos_entryconditions": "Charter drafted from stakeholder intake.",
                    "gtos_exitconditions": "Charter reviewed and superseded by verified version.",
                    "gtos_evidencebundle": "Intake notes; draft doc v0.1."}},
        {"table": "State", "name": "S2 - Verified Charter",
         "fields": {"gtos_lifecyclestage": opt("State", "LifecycleStage", "Verify"),
                    "gtos_status": opt("State", "Status", "Active"),
                    "gtos_entryconditions": "All charter findings resolved or accepted.",
                    "gtos_exitconditions": "Signed off by governance authority.",
                    "gtos_evidencebundle": "Verified doc v1.0; approval record G1."}},
    ]

    knowledge = [
        {"table": "Knowledge", "name": "K1 - Scope assumption",
         "fields": {"gtos_knowledgetype": opt("Knowledge", "KnowledgeType", "Assumption"),
                    "gtos_statement": "Reporting layer is read-only over Dataverse via Fabric mirroring.",
                    "gtos_evidence": "docs/reporting/build-steps.md",
                    "gtos_owner": owner_upn, "gtos_verified": True},
         "lookups": {"gtos_knowledge_state": ("State", "S1 - Draft Charter")}},
        {"table": "Knowledge", "name": "K2 - Verification lesson",
         "fields": {"gtos_knowledgetype": opt("Knowledge", "KnowledgeType", "Lesson"),
                    "gtos_statement": "Interactive device-code auth is the working path under MDM enrollment.",
                    "gtos_evidence": "Live run: created 0 across tables/columns/relationships.",
                    "gtos_owner": owner_upn, "gtos_verified": True},
         "lookups": {"gtos_knowledge_state": ("State", "S2 - Verified Charter")}},
    ]

    governance = [
        {"table": "Governance", "name": "G1 - Charter Authority",
         "fields": {"gtos_authorityscope": "Approve charter transitions for Sovereign_Sandbox_v1.",
                    "gtos_ownership": owner_upn,
                    "gtos_approvalstatus": opt("Governance", "ApprovalStatus", "Approved"),
                    "gtos_approvedby": owner_upn,
                    "gtos_evidence": "Approval thread; signed charter v1.0."}},
    ]

    transformation = [
        {"table": "Transformation", "name": "T1 - Draft to Verified Charter",
         "fields": {"gtos_goal": "Move the charter from Draft to Verified via review.",
                    "gtos_provider": "Verification Mesh",
                    "gtos_preconditions": "Draft charter exists (S1).",
                    "gtos_postconditions": "Verified charter exists (S2).",
                    "gtos_evidencerequirements": "All blocker/major findings resolved or accepted.",
                    "gtos_status": opt("Transformation", "Status", "Verified")},
         "lookups": {"gtos_transformation_inputstate": ("State", "S1 - Draft Charter"),
                     "gtos_transformation_outputstate": ("State", "S2 - Verified Charter")}},
    ]

    audit = [
        {"table": "Audit", "name": "A1 - Charter submitted",
         "fields": {"gtos_actor": owner_upn, "gtos_action": "Submitted draft charter for review.",
                    "gtos_occurredon": iso(now - timedelta(days=6)),
                    "gtos_evidencelink": "https://example/intake"},
         "lookups": {"gtos_audit_governance": ("Governance", "G1 - Charter Authority")}},
        {"table": "Audit", "name": "A2 - Charter approved",
         "fields": {"gtos_actor": owner_upn, "gtos_action": "Approved charter after retest passed.",
                    "gtos_occurredon": iso(now - timedelta(days=1)),
                    "gtos_evidencelink": "https://example/approval"},
         "lookups": {"gtos_audit_governance": ("Governance", "G1 - Charter Authority")}},
    ]

    finding = [
        {"table": "Finding", "name": "F1 - Missing evidence link",
         "fields": {"gtos_description": "Charter cites a decision with no evidence link.",
                    "gtos_severity": opt("Finding", "Severity", "Blocker"),
                    "gtos_owner": owner_upn, "gtos_fix": "Attach the decision-record URL.",
                    "gtos_retestresult": opt("Finding", "RetestResult", "Pass"),
                    "gtos_accepted": True, "gtos_detectedon": iso(now - timedelta(days=5))},
         "lookups": {"gtos_finding_transformation": ("Transformation", "T1 - Draft to Verified Charter")}},
        {"table": "Finding", "name": "F2 - Ambiguous scope wording",
         "fields": {"gtos_description": "Scope section uses 'etc.' without enumeration.",
                    "gtos_severity": opt("Finding", "Severity", "Major"),
                    "gtos_owner": owner_upn, "gtos_fix": "Enumerate in/out-of-scope items.",
                    "gtos_retestresult": opt("Finding", "RetestResult", "Pass"),
                    "gtos_accepted": True, "gtos_detectedon": iso(now - timedelta(days=4))},
         "lookups": {"gtos_finding_transformation": ("Transformation", "T1 - Draft to Verified Charter")}},
        {"table": "Finding", "name": "F3 - Typo in title",
         "fields": {"gtos_description": "Charter title has a spelling error.",
                    "gtos_severity": opt("Finding", "Severity", "Minor"),
                    "gtos_owner": owner_upn, "gtos_fix": "Correct the spelling.",
                    "gtos_retestresult": opt("Finding", "RetestResult", "Pending"),
                    "gtos_accepted": False, "gtos_detectedon": iso(now - timedelta(days=2))},
         "lookups": {"gtos_finding_transformation": ("Transformation", "T1 - Draft to Verified Charter")}},
    ]

    return states + knowledge + governance + transformation + audit + finding


# --------------------------------- main ------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Seed the GTOS tables with demo data for reporting.")
    ap.add_argument("--schema", default=str(Path(__file__).with_name("schema.json")))
    ap.add_argument("--whatif", action="store_true", help="Preview without writing.")
    ap.add_argument("--interactive", action="store_true", help="Sign in as yourself (device code).")
    ap.add_argument("--purge", action="store_true", help="Delete the demo records instead of creating them.")
    ap.add_argument("--owner", default=None, help="UPN to stamp as owner (defaults to OWNER_UPN env or a placeholder).")
    args = ap.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))
    url = os.environ.get("DATAVERSE_URL")
    tenant = os.environ.get("TENANT_ID")
    client_id = os.environ.get("CLIENT_ID")
    secret = os.environ.get("CLIENT_SECRET")
    owner_upn = args.owner or os.environ.get("OWNER_UPN") or "demo.owner@example.com"

    if not url or "YOUR_ORG" in url:
        sys.exit("DATAVERSE_URL is not set in .env (e.g. https://org331e3f60.crm.dynamics.com).")

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    prefix = schema.get("publisherPrefix", "gtos")
    records = build_demo(schema, owner_upn)

    action = "PURGE" if args.purge else "SEED"
    mode = "DRY RUN (--whatif)" if args.whatif else "LIVE"
    print(f"== GTOS demo {action} ==\nMode: {mode}\nOwner stamp: {owner_upn}\n")

    if args.whatif:
        for rec in records:
            verb = "delete" if args.purge else "create"
            print(f"[{verb}] {prefix}_{rec['table'].lower()}: {rec['name']}")
        print(f"\n{len(records)} record(s) would be {'deleted' if args.purge else 'created'} (dry run).")
        return

    if args.interactive:
        print("Interactive sign-in (device code):")
        tenant_arg = tenant if (tenant and tenant != PLACEHOLDER) else None
        client_arg = client_id if (client_id and client_id != PLACEHOLDER) else None
        token = get_token_interactive(tenant_arg, url, client_id=client_arg)
    else:
        token = get_token_client_credentials(tenant, client_id, secret, url)
    dv = Dataverse(url, token, whatif=False)
    print("Authenticated.\n")

    # Resolve entity set names once.
    set_of = {t["schemaName"]: dv.entity_set_name(f"{prefix}_{t['schemaName']}".lower())
              for t in schema["tables"]}

    if args.purge:
        deleted = 0
        for rec in reversed(records):  # children first
            es = set_of[rec["table"]]
            rid = dv.find_by_name(es, rec["name"])
            if rid:
                print(f"[delete] {es}: {rec['name']}")
                dv.delete(es, rid)
                deleted += 1
            else:
                print(f"[skip] not found: {rec['name']}")
        print(f"\nDone. Demo records deleted: {deleted}.")
        return

    created = 0
    id_by_name = {}
    for rec in records:
        es = set_of[rec["table"]]
        existing = dv.find_by_name(es, rec["name"])
        if existing:
            id_by_name[(rec["table"], rec["name"])] = existing
            print(f"[skip] exists: {rec['name']}")
            continue
        payload = {"gtos_name": rec["name"]}
        payload.update(rec.get("fields", {}))
        for rel_schema, (ref_table, ref_name) in rec.get("lookups", {}).items():
            nav = dv.nav_property(rel_schema)
            ref_set = set_of[ref_table]
            ref_id = id_by_name.get((ref_table, ref_name)) or dv.find_by_name(ref_set, ref_name)
            if not ref_id:
                raise RuntimeError(f"Lookup target not found: {ref_table} '{ref_name}' for {rec['name']}")
            payload[f"{nav}@odata.bind"] = f"/{ref_set}({ref_id})"
        print(f"[create] {es}: {rec['name']}")
        new_id = dv.create(es, payload)
        id_by_name[(rec["table"], rec["name"])] = new_id
        created += 1
        time.sleep(0.5)

    print(f"\nDone. Demo records created: {created} (skipped {len(records) - created}).")


if __name__ == "__main__":
    main()
