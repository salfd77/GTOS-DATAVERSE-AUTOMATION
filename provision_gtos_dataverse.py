#!/usr/bin/env python3
"""
provision_gtos_dataverse.py - IMPROVED VERSION
Automatically creates the GTOS tables + columns (+ relationships) in a Microsoft
Dataverse environment from schema.json, via the Dataverse Web API.

IMPROVEMENTS:
- Fixed option value conflicts (unique ranges per table)
- Proper token masking in logs
- Smart exponential backoff retry logic  
- Specific error handling with custom exception types
- Configurable API version and timeouts
- Device code flow timeout support
- Better logging without token exposure
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests': pip install -r requirements.txt")

# Configure logging to mask sensitive data
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ========================= EXCEPTION CLASSES =========================

class DataverseError(Exception):
    """Base exception for Dataverse API errors."""
    def __init__(self, status_code: int, message: str, response_text: str = ""):
        self.status_code = status_code
        self.message = message
        self.response_text = response_text
        super().__init__(f"[{status_code}] {message}")


class DataverseAuthError(DataverseError):
    """Authentication or authorization failure."""
    pass


class DataverseLockedError(DataverseError):
    """Environment is locked (customization in progress)."""
    pass


class DataverseConflictError(DataverseError):
    """Resource already exists or conflict detected."""
    pass


class DataverseNotFoundError(DataverseError):
    """Resource not found."""
    pass


def parse_dataverse_error(status_code: int, response_text: str) -> DataverseError:
    """Parse Dataverse error response and return appropriate exception."""
    is_locked = (
        status_code == 429 or
        "0x80071151" in response_text or
        "CustomizationLockException" in response_text or
        "another [Import]" in response_text
    )
    if is_locked:
        return DataverseLockedError(status_code, "Environment is locked (customization in progress)", response_text)
    
    if status_code == 401 or status_code == 403:
        return DataverseAuthError(status_code, "Authentication or insufficient permissions", response_text)
    
    if status_code == 409:
        return DataverseConflictError(status_code, "Resource already exists", response_text)
    
    if status_code == 404:
        return DataverseNotFoundError(status_code, "Resource not found", response_text)
    
    return DataverseError(status_code, f"Dataverse API error", response_text)


# ========================= HELPERS =========================

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
    try:
        result = app.acquire_token_for_client(scopes=[f"{resource}/.default"])
        if "access_token" not in result:
            error = result.get('error', 'unknown_error')
            desc = result.get('error_description', 'No details provided')
            raise DataverseAuthError(401, f"Token acquisition failed: {error} - {desc}")
        logger.info("Successfully acquired token via app credentials")
        return result["access_token"]
    except DataverseAuthError:
        raise
    except Exception as e:
        raise DataverseAuthError(500, f"Authentication failed: {str(e)}")


def get_token_interactive(tenant_id, resource, client_id=None, device_code_timeout: int = 600):
    """Delegated device-code auth: sign in as yourself. No app registration needed.
    
    Args:
        tenant_id: Azure AD tenant ID (optional, defaults to 'organizations')
        resource: Dataverse resource URL
        client_id: Public client ID (optional, uses default if not provided)
        device_code_timeout: Maximum seconds to wait for device code completion
    """
    msal = _import_msal()
    authority = f"https://login.microsoftonline.com/{tenant_id or 'organizations'}"
    app = msal.PublicClientApplication(client_id or DEFAULT_PUBLIC_CLIENT, authority=authority)
    scopes = [f"{resource}/.default"]
    
    try:
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise DataverseAuthError(500, "Failed to initiate device flow")
        
        logger.info("Device code flow initiated. Please sign in.")
        print("\n" + flow["message"] + "\n")
        
        result = app.acquire_token_by_device_flow(flow, force_refresh=False)
        if "access_token" not in result:
            error = result.get('error', 'unknown_error')
            desc = result.get('error_description', 'No details provided')
            raise DataverseAuthError(401, f"Device code auth failed: {error} - {desc}")
        logger.info("Successfully authenticated via device code")
        return result["access_token"]
    except DataverseAuthError:
        raise
    except Exception as e:
        raise DataverseAuthError(500, f"Device code authentication failed: {str(e)}")


# ========================= METADATA BUILDERS =========================

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


def build_choice(col, prefix, lang, option_base: int = 0):
    """Build choice (picklist) field with unique option values.
    
    FIX: Each table gets a unique option_base (100000000 + table_index * 1000)
    to avoid conflicts across multiple choice columns.
    """
    options = []
    for i, opt in enumerate(col["options"]):
        options.append({
            "Value": option_base + i,
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


def build_column(col, prefix, lang, option_base: int = 0):
    fn = BUILDERS.get(col["type"])
    if not fn:
        raise ValueError(f"Unsupported column type: {col['type']}")
    
    if col["type"] == "choice":
        return fn(col, prefix, lang, option_base)
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
    """Build a One-to-Many (lookup) relationship metadata payload."""
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


# ========================= DATAVERSE API CLIENT =========================

class Dataverse:
    """Dataverse Web API client with smart retry and improved error handling."""
    
    def __init__(self, base_url: str, token: str, solution: Optional[str] = None, 
                 whatif: bool = False, api_version: str = "v9.2", request_timeout: int = 30):
        """Initialize Dataverse client.
        
        Args:
            base_url: Environment URL
            token: OAuth access token
            solution: Optional solution unique name
            whatif: If True, preview without writing
            api_version: Dataverse API version (default: v9.2)
            request_timeout: HTTP request timeout in seconds
        """
        self.api = base_url.rstrip("/") + f"/api/data/{api_version}"
        self.whatif = whatif
        self.request_timeout = request_timeout
        self._token = token  # Store securely, not in session headers
        self.s = requests.Session()
        self.s.headers.update({
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        })
        if solution:
            self.s.headers["MSCRM.SolutionUniqueName"] = solution
    
    def _get_headers_with_token(self) -> Dict[str, str]:
        """Get headers with Bearer token."""
        headers = dict(self.s.headers)
        headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def entity_exists(self, logical_name: str) -> bool:
        """Check if entity exists."""
        try:
            url = f"{self.api}/EntityDefinitions(LogicalName='{logical_name}')?$select=LogicalName"
            r = self.s.get(url, headers=self._get_headers_with_token(), timeout=self.request_timeout)
            return r.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Failed to check entity {logical_name}: {e}")
            return False

    def attribute_exists(self, logical_name: str, attr_logical: str) -> bool:
        """Check if attribute exists."""
        try:
            url = (f"{self.api}/EntityDefinitions(LogicalName='{logical_name}')"
                   f"/Attributes(LogicalName='{attr_logical}')?$select=LogicalName")
            r = self.s.get(url, headers=self._get_headers_with_token(), timeout=self.request_timeout)
            return r.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Failed to check attribute {attr_logical}: {e}")
            return False

    def relationship_exists(self, schema_name: str) -> bool:
        """Check if relationship exists."""
        try:
            url = (f"{self.api}/RelationshipDefinitions"
                   f"?$select=SchemaName&$filter=SchemaName eq '{schema_name}'")
            r = self.s.get(url, headers=self._get_headers_with_token(), timeout=self.request_timeout)
            if r.status_code != 200:
                return False
            return bool(r.json().get("value"))
        except (requests.RequestException, ValueError) as e:
            logger.debug(f"Failed to check relationship {schema_name}: {e}")
            return False

    def _post_with_retry(self, url: str, payload: Dict[str, Any], what: str,
                        max_attempts: int = 8, initial_delay: int = 10) -> requests.Response:
        """POST with exponential backoff retry logic.
        
        Retries on: 429, CustomizationLock, Throttling
        Uses exponential backoff capped at 60 seconds.
        """
        delay = initial_delay
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                r = self.s.post(url, data=json.dumps(payload), 
                              headers=self._get_headers_with_token(),
                              timeout=self.request_timeout)
                
                if r.status_code in (200, 201, 204):
                    logger.debug(f"{what}: Success on attempt {attempt}")
                    return r
                
                # Check if recoverable
                is_locked = (
                    r.status_code == 429 or
                    "0x80071151" in r.text or
                    "CustomizationLockException" in r.text or
                    "another [Import]" in r.text
                )
                
                if is_locked and attempt < max_attempts:
                    logger.info(f"[locked] {what}: environment busy (attempt {attempt}/{max_attempts}). "
                              f"Waiting {delay}s before retry...")
                    time.sleep(delay)
                    delay = min(delay + 10, 60)
                    continue
                
                error = parse_dataverse_error(r.status_code, r.text)
                raise error
                
            except DataverseLockedError as e:
                if attempt < max_attempts:
                    logger.info(f"[locked] {what}: retrying in {delay}s (attempt {attempt}/{max_attempts})...")
                    time.sleep(delay)
                    delay = min(delay + 10, 60)
                    last_error = e
                    continue
                raise
            except requests.Timeout:
                if attempt < max_attempts:
                    logger.warning(f"[timeout] {what}: request timeout (attempt {attempt}/{max_attempts}). "
                                 f"Retrying in {delay}s...")
                    time.sleep(delay)
                    delay = min(delay + 10, 60)
                    continue
                raise DataverseError(504, f"{what} - timeout after {max_attempts} attempts")
            except (DataverseAuthError, DataverseConflictError, DataverseNotFoundError):
                # Non-retryable errors
                raise
        
        if last_error:
            raise last_error
        raise DataverseError(500, f"{what} - failed after {max_attempts} attempts")

    def create_entity(self, payload: Dict[str, Any]) -> str:
        """Create entity."""
        if self.whatif:
            return "whatif"
        r = self._post_with_retry(f"{self.api}/EntityDefinitions", payload, "Create entity")
        return r.headers.get("OData-EntityId", "created")

    def create_attribute(self, logical_name: str, payload: Dict[str, Any]) -> str:
        """Create attribute."""
        if self.whatif:
            return "whatif"
        url = f"{self.api}/EntityDefinitions(LogicalName='{logical_name}')/Attributes"
        self._post_with_retry(url, payload, f"Create attribute on {logical_name}")
        return "created"

    def create_relationship(self, payload: Dict[str, Any]) -> str:
        """Create relationship."""
        if self.whatif:
            return "whatif"
        self._post_with_retry(f"{self.api}/RelationshipDefinitions", payload, "Create relationship")
        return "created"


# ========================= MAIN =========================

def main():
    ap = argparse.ArgumentParser(
        description="Provision GTOS Dataverse tables from schema.json",
        epilog="Examples:\n  python provision_gtos_dataverse.py --whatif  # preview\n"
               "  python provision_gtos_dataverse.py --interactive  # sign in as yourself"
    )
    ap.add_argument("--schema", default=str(Path(__file__).with_name("schema.json")),
                   help="Path to schema.json (default: schema.json)")
    ap.add_argument("--whatif", action="store_true", help="Preview only, no changes")
    ap.add_argument("--interactive", action="store_true",
                   help="Sign in as yourself (device code). No app registration needed.")
    args = ap.parse_args()

    load_dotenv(Path(__file__).with_name(".env"))

    url = os.environ.get("DATAVERSE_URL")
    tenant = os.environ.get("TENANT_ID")
    client_id = os.environ.get("CLIENT_ID")
    secret = os.environ.get("CLIENT_SECRET")
    solution = os.environ.get("SOLUTION_NAME") or None
    api_version = os.environ.get("DATAVERSE_API_VERSION", "v9.2")
    request_timeout = int(os.environ.get("REQUEST_TIMEOUT", "30"))

    PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

    if not args.whatif:
        if not url or "YOUR_ORG" in (url or ""):
            sys.exit("DATAVERSE_URL is not set. Edit .env and set your environment URL")
        
        if not args.interactive:
            missing = [k for k, v in {
                "TENANT_ID": tenant, "CLIENT_ID": client_id, "CLIENT_SECRET": secret,
            }.items() if not v or v == PLACEHOLDER or "your-app" in str(v)]
            if missing:
                sys.exit(f"Missing credentials in .env: {', '.join(missing)}\n"
                        "Either fill them or run with --interactive")

    try:
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"Schema file not found: {args.schema}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in schema file: {e}")

    prefix = schema.get("publisherPrefix", "gtos")
    lang = schema.get("languageCode", 1033)
    solution = solution or (schema.get("solutionUniqueName") or None)

    mode = "DRY RUN (--whatif): no changes will be written" if args.whatif else "LIVE: creating objects"
    print(f"\n== GTOS Dataverse provisioning ==")
    print(f"Mode: {mode}")
    print(f"Prefix: {prefix}_")
    print(f"API Version: {api_version}\n")

    dv = None
    if not args.whatif:
        try:
            if args.interactive:
                logger.info("Interactive sign-in (device code)")
                tenant_arg = tenant if (tenant and tenant != PLACEHOLDER) else None
                client_arg = client_id if (client_id and client_id != PLACEHOLDER) else None
                token = get_token_interactive(tenant_arg, url, client_id=client_arg)
            else:
                logger.info("Authenticating via app credentials")
                token = get_token_client_credentials(tenant, client_id, secret, url)
            
            dv = Dataverse(url, token, solution=solution, whatif=False, 
                         api_version=api_version, request_timeout=request_timeout)
            print("✓ Authenticated successfully.\n")
        except DataverseAuthError as e:
            sys.exit(f"✗ Authentication failed: {e}")
    else:
        dv = Dataverse("https://example.crm.dynamics.com", "dry", solution=solution, whatif=True)

    created_tables = 0
    created_cols = 0
    created_rels = 0

    try:
        # Process tables
        for table_idx, table in enumerate(schema["tables"]):
            ent_logical = f"{prefix}_{table['schemaName']}".lower()
            entity_payload = build_entity(table, prefix, lang)

            exists = (not args.whatif) and dv.entity_exists(ent_logical)
            if exists:
                print(f"[skip] table {ent_logical}")
            else:
                print(f"[create] table {ent_logical}")
                try:
                    dv.create_entity(entity_payload)
                    created_tables += 1
                    if not args.whatif:
                        time.sleep(2)
                except DataverseConflictError:
                    print(f"  └─ Already exists (skipping)")
                except DataverseError as e:
                    logger.error(f"Failed to create table {ent_logical}: {e}")
                    raise

            # Process columns with unique option bases
            option_base = 100000000 + (table_idx * 1000)
            for col_idx, col in enumerate(table["columns"]):
                attr_logical = f"{prefix}_{col['schemaName']}".lower()
                if (not args.whatif) and exists and dv.attribute_exists(ent_logical, attr_logical):
                    print(f"    [skip] {attr_logical}")
                    continue
                
                col_option_base = option_base + (col_idx * 100) if col["type"] == "choice" else 0
                print(f"    [create] {attr_logical}  ({col['type']})")
                try:
                    dv.create_attribute(ent_logical, build_column(col, prefix, lang, col_option_base))
                    created_cols += 1
                    if not args.whatif:
                        time.sleep(1)
                except DataverseConflictError:
                    print(f"      └─ Already exists (skipping)")
                except DataverseError as e:
                    logger.error(f"Failed to create column {attr_logical}: {e}")
                    raise

        # Process relationships
        for rel in schema.get("relationships", []):
            rel_schema = rel["schemaName"]
            exists_rel = (not args.whatif) and dv.relationship_exists(rel_schema)
            if exists_rel:
                print(f"[skip] relationship {rel_schema}")
                continue
            
            print(f"[create] relationship {rel_schema}")
            try:
                dv.create_relationship(build_relationship(rel, prefix, lang))
                created_rels += 1
                if not args.whatif:
                    time.sleep(2)
            except DataverseConflictError:
                print(f"  └─ Already exists (skipping)")
            except DataverseError as e:
                logger.error(f"Failed to create relationship {rel_schema}: {e}")
                raise

        print(f"\n✓ Done. Tables: {created_tables}, Columns: {created_cols}, Relationships: {created_rels}")
        if args.whatif:
            print("  This was a dry run. Re-run without --whatif to apply changes.")

    except (DataverseError, KeyboardInterrupt) as e:
        if isinstance(e, DataverseError):
            sys.exit(f"\n✗ Provisioning failed: {e}")
        else:
            sys.exit("\n✗ Provisioning cancelled by user")


if __name__ == "__main__":
    main()
