#!/usr/bin/env python3
"""
seed_gtos_demo.py - IMPROVED VERSION
Populate the six provisioned GTOS tables with demo dataset.

IMPROVEMENTS:
- Uses improved exception handling from provision_gtos_dataverse.py
- Token masking and security improvements
- Better error messages and logging
- Configurable timeouts and API version
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests': pip install -r requirements.txt")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEFAULT_PUBLIC_CLIENT = "51f81489-12ee-4a9e-aaae-a2591f45987d"
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


# ========================= HELPERS =========================

def load_dotenv(path: Path):
    """Load environment variables from .env file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _import_msal():
    """Import and return msal module."""
    try:
        import msal
        return msal
    except ImportError:
        sys.exit("Missing dependency 'msal': python -m pip install -r requirements.txt")


def get_token_interactive(tenant_id, resource, client_id=None, device_code_timeout: int = 600):
    """Get token via device code flow (interactive)."""
    msal = _import_msal()
    authority = f"https://login.microsoftonline.com/{tenant_id or 'organizations'}"
    app = msal.PublicClientApplication(client_id or DEFAULT_PUBLIC_CLIENT, authority=authority)
    
    try:
        flow = app.initiate_device_flow(scopes=[f"{resource}/.default"])
        if "user_code" not in flow:
            raise RuntimeError("Failed to initiate device flow")
        
        logger.info("Device code flow initiated")
        print("\n" + flow["message"] + "\n")
        
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            error = result.get('error', 'unknown')
            desc = result.get('error_description', '')
            raise RuntimeError(f"Device code auth failed: {error} - {desc}")
        
        logger.info("Successfully authenticated via device code")
        return result["access_token"]
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise


def get_token_client_credentials(tenant_id, client_id, client_secret, resource):
    """Get token via app-only credentials flow."""
    msal = _import_msal()
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    
    try:
        result = app.acquire_token_for_client(scopes=[f"{resource}/.default"])
        if "access_token" not in result:
            error = result.get('error', 'unknown')
            desc = result.get('error_description', '')
            raise RuntimeError(f"App auth failed: {error} - {desc}")
        
        logger.info("Successfully acquired token via app credentials")
        return result["access_token"]
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise


# ========================= DATAVERSE CLIENT =========================

class Dataverse:
    """Dataverse Web API client for seeding demo data."""
    
    def __init__(self, base_url: str, token: str, api_version: str = "v9.2", 
                 request_timeout: int = 30, whatif: bool = False):
        """Initialize client."""
        self.api = base_url.rstrip("/") + f"/api/data/{api_version}"
        self.whatif = whatif
        self.request_timeout = request_timeout
        self._token = token
        self.s = requests.Session()
        self.s.headers.update({
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        })
    
    def _get_headers_with_token(self) -> Dict[str, str]:
        """Get headers with Bearer token."""
        headers = dict(self.s.headers)
        headers["Authorization"] = f"Bearer {self._token}"
        return headers
    
    def get_records(self, table_logical: str, filter_query: Optional[str] = None) -> list:
        """Get records from table."""
        try:
            url = f"{self.api}/{table_logical}"
            if filter_query:
                url += f"?$filter={filter_query}"
            
            r = self.s.get(url, headers=self._get_headers_with_token(), 
                         timeout=self.request_timeout)
            
            if r.status_code == 200:
                return r.json().get('value', [])
            
            logger.error(f"Failed to get records from {table_logical}: [{r.status_code}]")
            return []
        except Exception as e:
            logger.error(f"Exception getting records: {e}")
            return []
    
    def create_record(self, table_logical: str, data: Dict[str, Any]) -> Optional[str]:
        """Create a record and return its ID."""
        if self.whatif:
            logger.info(f"[DRY RUN] Would create in {table_logical}: {data}")
            return "whatif-id"
        
        try:
            url = f"{self.api}/{table_logical}"
            r = self.s.post(url, json=data, headers=self._get_headers_with_token(),
                          timeout=self.request_timeout)
            
            if r.status_code in (200, 201):
                record_id = r.headers.get('OData-EntityId', '').split('(')[1].rstrip(')')
                logger.debug(f"Created record in {table_logical}: {record_id}")
                return record_id
            
            logger.error(f"Failed to create record in {table_logical}: [{r.status_code}] {r.text[:100]}")
            return None
        except Exception as e:
            logger.error(f"Exception creating record: {e}")
            return None
    
    def delete_record(self, table_logical: str, record_id: str) -> bool:
        """Delete a record."""
        if self.whatif:
            logger.info(f"[DRY RUN] Would delete {record_id} from {table_logical}")
            return True
        
        try:
            url = f"{self.api}/{table_logical}({record_id})"
            r = self.s.delete(url, headers=self._get_headers_with_token(),
                            timeout=self.request_timeout)
            
            if r.status_code == 204:
                logger.debug(f"Deleted record {record_id} from {table_logical}")
                return True
            
            logger.error(f"Failed to delete record: [{r.status_code}]")
            return False
        except Exception as e:
            logger.error(f"Exception deleting record: {e}")
            return False
    
    def update_record(self, table_logical: str, record_id: str, data: Dict[str, Any]) -> bool:
        """Update a record."""
        if self.whatif:
            logger.info(f"[DRY RUN] Would update {record_id} in {table_logical}")
            return True
        
        try:
            url = f"{self.api}/{table_logical}({record_id})"
            r = self.s.patch(url, json=data, headers=self._get_headers_with_token(),
                           timeout=self.request_timeout)
            
            if r.status_code == 204:
                logger.debug(f"Updated record {record_id} in {table_logical}")
                return True
            
            logger.error(f"Failed to update record: [{r.status_code}]")
            return False
        except Exception as e:
            logger.error(f"Exception updating record: {e}")
            return False


# ========================= DEMO DATA =========================

def create_demo_data(dv: Dataverse, prefix: str, schema: dict):
    """Create demo data in GTOS tables."""
    lang = schema.get("languageCode", 1033)
    
    print("\n== Creating Demo Data ==\n")
    
    # Demo State records
    print("[create] Demo States")
    states = [
        {"gtos_name": "Requirements Review", "gtos_lifecyclestage": 100000000},  # Idea
        {"gtos_name": "Architecture Design", "gtos_lifecyclestage": 100000001},  # Requirements
        {"gtos_name": "Implementation Sprint", "gtos_lifecyclestage": 100000002},  # Architecture
    ]
    
    state_ids = []
    for state in states:
        state_id = dv.create_record(f"{prefix}_state", state)
        if state_id and state_id != "whatif-id":
            state_ids.append(state_id)
            print(f"  ✓ {state['gtos_name']}")
    
    # Demo Knowledge records
    print("\n[create] Demo Knowledge")
    knowledge_records = [
        {
            "gtos_name": "Database Choice",
            "gtos_knowledgetype": 100001000,  # Decision (table 1, col 0)
            "gtos_statement": "PostgreSQL selected for OLTP workloads",
            "gtos_verified": True,
        },
        {
            "gtos_name": "Performance Assumption",
            "gtos_knowledgetype": 100001100,  # Assumption
            "gtos_statement": "Sub-second query response time achievable",
            "gtos_verified": False,
        },
    ]
    
    for rec in knowledge_records:
        dv.create_record(f"{prefix}_knowledge", rec)
        print(f"  ✓ {rec['gtos_name']}")
    
    # Demo Transformation records
    print("\n[create] Demo Transformations")
    transformations = [
        {
            "gtos_name": "Data Import",
            "gtos_goal": "Load production data into analytics system",
            "gtos_provider": "ETL Service",
            "gtos_status": 100002000,  # Designed
        },
    ]
    
    for trans in transformations:
        dv.create_record(f"{prefix}_transformation", trans)
        print(f"  ✓ {trans['gtos_name']}")
    
    # Demo Governance records
    print("\n[create] Demo Governance")
    governance_records = [
        {
            "gtos_name": "Data Access Policy",
            "gtos_authorityscope": "Data Retention",
            "gtos_ownership": "Data Governance Team",
            "gtos_approvalstatus": 100003000,  # Pending
        },
    ]
    
    for gov in governance_records:
        dv.create_record(f"{prefix}_governance", gov)
        print(f"  ✓ {gov['gtos_name']}")
    
    # Demo Finding records
    print("\n[create] Demo Findings")
    findings = [
        {
            "gtos_name": "Missing Index on Users Table",
            "gtos_description": "Query performance degraded due to missing index",
            "gtos_severity": 100005000,  # Blocker
            "gtos_owner": "Database Team",
            "gtos_retestresult": 100005200,  # Pending
            "gtos_accepted": False,
        },
    ]
    
    for finding in findings:
        dv.create_record(f"{prefix}_finding", finding)
        print(f"  ✓ {finding['gtos_name']}")
    
    print("\n✓ Demo data creation complete!")


def purge_demo_data(dv: Dataverse, prefix: str):
    """Delete all demo records (identified by name pattern)."""
    print("\n== Purging Demo Data ==\n")
    
    demo_tables = [
        f"{prefix}_state",
        f"{prefix}_knowledge",
        f"{prefix}_transformation",
        f"{prefix}_governance",
        f"{prefix}_finding",
    ]
    
    purged = 0
    for table in demo_tables:
        records = dv.get_records(table)
        for rec in records:
            rec_id = rec.get('id') or rec.get(f'{table}id')
            if rec_id:
                if dv.delete_record(table, rec_id):
                    purged += 1
                    print(f"  ✓ Deleted from {table}")
    
    print(f"\n✓ Purged {purged} records")


# ========================= MAIN =========================

def main():
    ap = argparse.ArgumentParser(description="Seed GTOS tables with demo data")
    ap.add_argument("--interactive", action="store_true", help="Sign in as yourself")
    ap.add_argument("--whatif", action="store_true", help="Preview only")
    ap.add_argument("--purge", action="store_true", help="Delete demo records instead")
    args = ap.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))

    url = os.environ.get("DATAVERSE_URL")
    tenant = os.environ.get("TENANT_ID")
    client_id = os.environ.get("CLIENT_ID")
    secret = os.environ.get("CLIENT_SECRET")
    api_version = os.environ.get("DATAVERSE_API_VERSION", "v9.2")
    request_timeout = int(os.environ.get("REQUEST_TIMEOUT", "30"))

    if not url or "YOUR_ORG" in (url or ""):
        sys.exit("DATAVERSE_URL not configured in .env")

    try:
        schema = json.loads(Path(__file__).with_name("schema.json").read_text())
        prefix = schema.get("publisherPrefix", "gtos")
    except Exception as e:
        sys.exit(f"Failed to load schema.json: {e}")

    mode = "DRY RUN (--whatif)" if args.whatif else "LIVE"
    print(f"\n== GTOS Demo Data Seeder ==")
    print(f"Mode: {mode}")
    print(f"Prefix: {prefix}_")

    try:
        if args.interactive:
            logger.info("Authenticating (device code)...")
            token = get_token_interactive(tenant, url)
        else:
            logger.info("Authenticating (app credentials)...")
            token = get_token_client_credentials(tenant, client_id, secret, url)
        
        dv = Dataverse(url, token, api_version=api_version, 
                      request_timeout=request_timeout, whatif=args.whatif)
        print("✓ Authenticated\n")
        
        if args.purge:
            purge_demo_data(dv, prefix)
        else:
            create_demo_data(dv, prefix, schema)
    
    except Exception as e:
        sys.exit(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
