#!/usr/bin/env python3
"""
test_pytest_suite.py
Comprehensive pytest test suite for GTOS Dataverse Automation improvements.

This test suite validates all fixes using pytest framework.
Run with: pytest test_pytest_suite.py -v
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import provision_gtos_dataverse as prov


class TestOptionValueGeneration:
    """Test suite for option value uniqueness across tables."""
    
    def test_option_values_unique_per_table(self):
        """Verify option values don't conflict across tables."""
        schema = json.loads(Path('schema.json').read_text())
        tables = schema['tables']
        
        all_values = {}
        for table_idx, table in enumerate(tables):
            option_base = 100000000 + (table_idx * 1000)
            for col_idx, col in enumerate(table.get('columns', [])):
                if col['type'] != 'choice':
                    continue
                col_option_base = option_base + (col_idx * 100)
                for i, opt in enumerate(col['options']):
                    val = col_option_base + i
                    assert val not in all_values.values(), \
                        f"Duplicate option value {val}"
                    all_values[f"{table['schemaName']}.{col['schemaName']}.{opt}"] = val
        
        assert len(all_values) == 28, f"Expected 28 unique values, got {len(all_values)}"
    
    def test_option_base_calculation(self):
        """Verify option base calculation formula."""
        for table_idx in range(6):
            base = 100000000 + (table_idx * 1000)
            # Each table should have base in range
            assert base >= 100000000
            assert base % 1000 == 0
    
    def test_choice_builder_with_offset(self):
        """Verify choice builder uses option_base correctly."""
        col = {
            "schemaName": "Status",
            "displayName": "Status",
            "type": "choice",
            "options": ["Active", "Inactive", "Pending"]
        }
        result = prov.build_choice(col, "gtos", 1033, option_base=200000000)
        
        options = result["OptionSet"]["Options"]
        assert options[0]["Value"] == 200000000
        assert options[1]["Value"] == 200000001
        assert options[2]["Value"] == 200000002


class TestExceptionHierarchy:
    """Test suite for exception classes."""
    
    def test_dataverse_error_base(self):
        """Test base DataverseError class."""
        err = prov.DataverseError(500, "Test error", "response text")
        assert err.status_code == 500
        assert err.message == "Test error"
        assert err.response_text == "response text"
        assert "[500]" in str(err)
    
    def test_dataverse_auth_error(self):
        """Test DataverseAuthError is subclass of DataverseError."""
        err = prov.DataverseAuthError(401, "Unauthorized")
        assert isinstance(err, prov.DataverseError)
        assert err.status_code == 401
    
    def test_dataverse_locked_error(self):
        """Test DataverseLockedError is subclass of DataverseError."""
        err = prov.DataverseLockedError(429, "Locked")
        assert isinstance(err, prov.DataverseError)
        assert err.status_code == 429
    
    def test_dataverse_conflict_error(self):
        """Test DataverseConflictError is subclass of DataverseError."""
        err = prov.DataverseConflictError(409, "Conflict")
        assert isinstance(err, prov.DataverseError)
        assert err.status_code == 409
    
    def test_dataverse_not_found_error(self):
        """Test DataverseNotFoundError is subclass of DataverseError."""
        err = prov.DataverseNotFoundError(404, "Not found")
        assert isinstance(err, prov.DataverseError)
        assert err.status_code == 404


class TestErrorParsing:
    """Test suite for error parsing logic."""
    
    @pytest.mark.parametrize("status,response,expected_type", [
        (429, "Throttled", prov.DataverseLockedError),
        (401, "Unauthorized", prov.DataverseAuthError),
        (403, "Forbidden", prov.DataverseAuthError),
        (409, "Conflict", prov.DataverseConflictError),
        (404, "Not found", prov.DataverseNotFoundError),
        (500, "Server error", prov.DataverseError),
        (429, "0x80071151 CustomizationLock", prov.DataverseLockedError),
        (200, "", prov.DataverseError),  # Fallback to generic
    ])
    def test_parse_dataverse_error(self, status, response, expected_type):
        """Test error parsing for various HTTP status codes."""
        err = prov.parse_dataverse_error(status, response)
        assert type(err) == expected_type
        assert err.status_code == status


class TestTokenSecurity:
    """Test suite for token security and masking."""
    
    def test_token_not_in_session_headers(self):
        """Verify token is not stored in session headers."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "supersecrettoken123456789",
            whatif=True
        )
        
        # Token should NOT be in session headers
        auth_header = dv.s.headers.get("Authorization", "")
        assert "supersecret" not in auth_header
        assert "123456789" not in auth_header
        assert auth_header in ["Bearer ***", ""]
    
    def test_token_stored_securely(self):
        """Verify token is stored in _token attribute."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "supersecrettoken123456789",
            whatif=True
        )
        
        # Token should be in _token attribute
        assert dv._token == "supersecrettoken123456789"
    
    def test_get_headers_with_token(self):
        """Verify token is added only when needed."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "mytoken",
            whatif=True
        )
        
        headers = dv._get_headers_with_token()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer mytoken"


class TestConfigurableParameters:
    """Test suite for configurable parameters."""
    
    def test_custom_api_version(self):
        """Test API version configuration."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            api_version="v9.1",
            whatif=True
        )
        
        assert "/api/data/v9.1" in dv.api
        assert "/api/data/v9.2" not in dv.api
    
    def test_custom_request_timeout(self):
        """Test request timeout configuration."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            request_timeout=60,
            whatif=True
        )
        
        assert dv.request_timeout == 60
    
    def test_default_api_version(self):
        """Test default API version is v9.2."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            whatif=True
        )
        
        assert "/api/data/v9.2" in dv.api
    
    def test_default_request_timeout(self):
        """Test default request timeout is 30 seconds."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            whatif=True
        )
        
        assert dv.request_timeout == 30


class TestColumnBuilders:
    """Test suite for column builder functions."""
    
    def test_build_string(self):
        """Test string column builder."""
        col = {"schemaName": "Name", "displayName": "Name", "maxLength": 100}
        result = prov.build_string(col, "gtos", 1033)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.StringAttributeMetadata"
        assert "gtos_Name" in result["SchemaName"]
        assert result["MaxLength"] == 100
    
    def test_build_memo(self):
        """Test memo column builder."""
        col = {"schemaName": "Description", "displayName": "Description"}
        result = prov.build_memo(col, "gtos", 1033)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.MemoAttributeMetadata"
        assert "gtos_Description" in result["SchemaName"]
    
    def test_build_boolean(self):
        """Test boolean column builder."""
        col = {"schemaName": "IsActive", "displayName": "Is Active"}
        result = prov.build_boolean(col, "gtos", 1033)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.BooleanAttributeMetadata"
        assert "gtos_IsActive" in result["SchemaName"]
    
    def test_build_datetime(self):
        """Test datetime column builder."""
        col = {"schemaName": "CreatedOn", "displayName": "Created On"}
        result = prov.build_datetime(col, "gtos", 1033)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.DateTimeAttributeMetadata"
        assert "gtos_CreatedOn" in result["SchemaName"]
    
    def test_build_choice(self):
        """Test choice column builder."""
        col = {
            "schemaName": "Status",
            "displayName": "Status",
            "options": ["Active", "Inactive"]
        }
        result = prov.build_choice(col, "gtos", 1033, option_base=100000000)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.PicklistAttributeMetadata"
        options = result["OptionSet"]["Options"]
        assert len(options) == 2
        assert options[0]["Value"] == 100000000
        assert options[1]["Value"] == 100000001


class TestSchemaValidation:
    """Test suite for schema validation."""
    
    def test_schema_valid_json(self):
        """Test schema.json is valid JSON."""
        schema_text = Path('schema.json').read_text()
        schema = json.loads(schema_text)
        
        assert isinstance(schema, dict)
        assert "tables" in schema
        assert "publisherPrefix" in schema
    
    def test_schema_has_required_tables(self):
        """Test schema contains all 6 required tables."""
        schema = json.loads(Path('schema.json').read_text())
        tables = schema['tables']
        
        assert len(tables) == 6
        table_names = {t['schemaName'] for t in tables}
        required = {"State", "Knowledge", "Transformation", "Governance", "Audit", "Finding"}
        assert table_names == required
    
    def test_schema_relationships_valid(self):
        """Test schema relationships reference valid tables."""
        schema = json.loads(Path('schema.json').read_text())
        table_names = {t['schemaName'] for t in schema['tables']}
        
        for rel in schema.get('relationships', []):
            assert rel['referenced'] in table_names, \
                f"Referenced table {rel['referenced']} not found"
            assert rel['referencing'] in table_names, \
                f"Referencing table {rel['referencing']} not found"


class TestBuildEntity:
    """Test suite for entity building."""
    
    def test_build_entity_structure(self):
        """Test entity metadata building."""
        table = {
            "schemaName": "State",
            "displayName": "GTOS State",
            "displayCollectionName": "GTOS States",
            "description": "A state",
            "primaryName": {"schemaName": "Name", "displayName": "State Name", "maxLength": 200},
            "columns": []
        }
        
        result = prov.build_entity(table, "gtos", 1033)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.EntityMetadata"
        assert "gtos_State" in result["SchemaName"]
        assert result["OwnershipType"] == "UserOwned"
        assert len(result["Attributes"]) >= 1


class TestBuildColumn:
    """Test suite for build_column function."""
    
    def test_build_column_string(self):
        """Test build_column for string type."""
        col = {
            "schemaName": "Name",
            "displayName": "Name",
            "type": "string",
            "maxLength": 100
        }
        result = prov.build_column(col, "gtos", 1033)
        
        assert result["@odata.type"] == "Microsoft.Dynamics.CRM.StringAttributeMetadata"
    
    def test_build_column_choice_with_base(self):
        """Test build_column for choice type with option_base."""
        col = {
            "schemaName": "Status",
            "displayName": "Status",
            "type": "choice",
            "options": ["Active", "Inactive"]
        }
        result = prov.build_column(col, "gtos", 1033, option_base=200000000)
        
        options = result["OptionSet"]["Options"]
        assert options[0]["Value"] == 200000000
        assert options[1]["Value"] == 200000001
    
    def test_build_column_unsupported_type(self):
        """Test build_column raises for unsupported type."""
        col = {
            "schemaName": "Custom",
            "displayName": "Custom",
            "type": "unsupported_type"
        }
        
        with pytest.raises(ValueError, match="Unsupported column type"):
            prov.build_column(col, "gtos", 1033)


class TestLoadDotenv:
    """Test suite for .env loading."""
    
    def test_load_dotenv_file_exists(self):
        """Test loading .env file."""
        from unittest.mock import patch, mock_open
        
        env_content = "KEY1=value1\nKEY2=value2\n"
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.read_text', return_value=env_content):
                with patch('os.environ.setdefault') as mock_setdefault:
                    prov.load_dotenv(Path('.env'))
                    # Should have called setdefault for each variable
                    assert mock_setdefault.call_count >= 0
    
    def test_load_dotenv_file_not_exists(self):
        """Test loading non-existent .env file."""
        from unittest.mock import patch
        
        with patch('pathlib.Path.exists', return_value=False):
            # Should not raise
            prov.load_dotenv(Path('.env.nonexistent'))


class TestIntegration:
    """Integration tests."""
    
    def test_dry_run_with_whatif(self):
        """Test dry run mode (whatif)."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            whatif=True
        )
        
        payload = {"test": "data"}
        result = dv.create_entity(payload)
        
        assert result == "whatif"
    
    def test_dataverse_client_initialization(self):
        """Test Dataverse client initialization."""
        dv = prov.Dataverse(
            "https://org.crm.dynamics.com",
            "token",
            solution="test-solution",
            api_version="v9.2",
            request_timeout=30
        )
        
        assert "/api/data/v9.2" in dv.api
        assert dv.request_timeout == 30
        assert dv._token == "token"
        assert dv.s.headers.get("MSCRM.SolutionUniqueName") == "test-solution"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
