#!/usr/bin/env python3
"""
test_improvements.py
Comprehensive tests validating all improvements made to provision_gtos_dataverse.py
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import provision_gtos_dataverse as prov

def test_option_value_conflicts():
    """Test that option values are unique across tables."""
    print("\n=== Test 1: Option Value Uniqueness ===")
    
    schema = json.loads(Path('schema.json').read_text())
    tables = schema['tables']
    
    all_option_values = {}  # Track all option values globally
    conflicts = 0
    
    for table_idx, table in enumerate(tables):
        option_base = 100000000 + (table_idx * 1000)
        table_name = table['schemaName']
        
        for col_idx, col in enumerate(table.get('columns', [])):
            if col['type'] != 'choice':
                continue
            
            col_option_base = option_base + (col_idx * 100)
            
            for i, opt in enumerate(col['options']):
                val = col_option_base + i
                key = f"{table_name}.{col['schemaName']}.{opt}"
                
                if val in all_option_values.values():
                    print(f"  ✗ Conflict: Value {val} used for {key} and {[k for k, v in all_option_values.items() if v == val][0]}")
                    conflicts += 1
                else:
                    all_option_values[key] = val
    
    if conflicts == 0:
        print(f"  ✓ All {len(all_option_values)} option values are unique!")
        print(f"    - Option base range: 100000000 to {max(all_option_values.values())}")
        return True
    else:
        print(f"  ✗ Found {conflicts} conflicts!")
        return False


def test_exception_classes():
    """Test that exception classes exist and work."""
    print("\n=== Test 2: Exception Classes ===")
    
    try:
        # Test DataverseError
        err = prov.DataverseError(500, "Test error")
        assert err.status_code == 500
        assert "Test error" in str(err)
        print(f"  ✓ DataverseError works")
        
        # Test DataverseAuthError
        err = prov.DataverseAuthError(401, "Auth failed")
        assert isinstance(err, prov.DataverseError)
        print(f"  ✓ DataverseAuthError works")
        
        # Test DataverseLockedError
        err = prov.DataverseLockedError(429, "Locked")
        assert isinstance(err, prov.DataverseError)
        print(f"  ✓ DataverseLockedError works")
        
        # Test DataverseConflictError
        err = prov.DataverseConflictError(409, "Conflict")
        assert isinstance(err, prov.DataverseError)
        print(f"  ✓ DataverseConflictError works")
        
        # Test DataverseNotFoundError
        err = prov.DataverseNotFoundError(404, "Not found")
        assert isinstance(err, prov.DataverseError)
        print(f"  ✓ DataverseNotFoundError works")
        
        return True
    except Exception as e:
        print(f"  ✗ Exception test failed: {e}")
        return False


def test_error_parsing():
    """Test error parsing logic."""
    print("\n=== Test 3: Error Parsing ===")
    
    test_cases = [
        (429, "Throttled", prov.DataverseLockedError),
        (401, "Unauthorized", prov.DataverseAuthError),
        (403, "Forbidden", prov.DataverseAuthError),
        (409, "Conflict", prov.DataverseConflictError),
        (404, "Not found", prov.DataverseNotFoundError),
        (500, "Generic error", prov.DataverseError),
        (429, "0x80071151 CustomizationLock", prov.DataverseLockedError),
    ]
    
    passed = 0
    for status, text, expected_type in test_cases:
        err = prov.parse_dataverse_error(status, text)
        if type(err) == expected_type:
            print(f"  ✓ [{status}] {text[:30]}... → {expected_type.__name__}")
            passed += 1
        else:
            print(f"  ✗ [{status}] Expected {expected_type.__name__}, got {type(err).__name__}")
    
    return passed == len(test_cases)


def test_token_masking():
    """Test that tokens are properly masked."""
    print("\n=== Test 4: Token Masking ===")
    
    try:
        # Create a mock client
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "supersecrettoken123456789",
            whatif=True
        )
        
        headers = dv.s.headers
        auth_header = headers.get("Authorization", "")
        
        if "superse" in auth_header or "789" in auth_header:
            print(f"  ✗ Token is not masked in session headers: {auth_header[:50]}")
            return False
        
        if auth_header in ["Bearer ***", ""]:
            print(f"  ✓ Token is properly masked in session headers")
        
        # Check that actual token is stored separately
        if dv._token == "supersecrettoken123456789":
            print(f"  ✓ Actual token is stored securely in _token attribute")
        else:
            print(f"  ✗ Token not stored correctly")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ Token masking test failed: {e}")
        return False


def test_configurable_parameters():
    """Test that parameters are configurable."""
    print("\n=== Test 5: Configurable Parameters ===")
    
    try:
        # Test custom API version
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            api_version="v9.1",
            request_timeout=60,
            whatif=True
        )
        
        if "/api/data/v9.1" in dv.api:
            print(f"  ✓ Custom API version (v9.1) configured")
        else:
            print(f"  ✗ API version not applied: {dv.api}")
            return False
        
        if dv.request_timeout == 60:
            print(f"  ✓ Custom request timeout (60s) configured")
        else:
            print(f"  ✗ Request timeout not applied: {dv.request_timeout}")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ Configurable parameters test failed: {e}")
        return False


def test_column_builders():
    """Test column builder functions."""
    print("\n=== Test 6: Column Builder Functions ===")
    
    try:
        lang = 1033
        prefix = "gtos"
        
        # Test string builder
        col = {"schemaName": "Name", "displayName": "Name", "maxLength": 100, "type": "string"}
        result = prov.build_string(col, prefix, lang)
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.StringAttributeMetadata"
        print(f"  ✓ String builder works")
        
        # Test memo builder
        col = {"schemaName": "Description", "displayName": "Description", "type": "memo"}
        result = prov.build_memo(col, prefix, lang)
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.MemoAttributeMetadata"
        print(f"  ✓ Memo builder works")
        
        # Test boolean builder
        col = {"schemaName": "IsActive", "displayName": "Is Active", "type": "boolean"}
        result = prov.build_boolean(col, prefix, lang)
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.BooleanAttributeMetadata"
        print(f"  ✓ Boolean builder works")
        
        # Test choice builder with option_base
        col = {"schemaName": "Status", "displayName": "Status", "type": "choice", 
               "options": ["Active", "Inactive"]}
        result = prov.build_choice(col, prefix, lang, option_base=200000000)
        options = result["OptionSet"]["Options"]
        if options[0]["Value"] == 200000000 and options[1]["Value"] == 200000001:
            print(f"  ✓ Choice builder with option_base works (values: {options[0]['Value']}, {options[1]['Value']})")
        else:
            print(f"  ✗ Choice builder option values incorrect: {[o['Value'] for o in options]}")
            return False
        
        return True
    except Exception as e:
        print(f"  ✗ Column builder test failed: {e}")
        return False


def run_all_tests():
    """Run all tests."""
    print("\n" + "="*60)
    print("GTOS DATAVERSE AUTOMATION - IMPROVEMENT TESTS")
    print("="*60)
    
    tests = [
        ("Option Value Uniqueness", test_option_value_conflicts),
        ("Exception Classes", test_exception_classes),
        ("Error Parsing", test_error_parsing),
        ("Token Masking", test_token_masking),
        ("Configurable Parameters", test_configurable_parameters),
        ("Column Builders", test_column_builders),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n✗ {name} FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60 + "\n")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
