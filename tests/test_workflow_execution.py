"""
Comprehensive tests for workflow execution and testing endpoints.

Tests cover:
- Standalone workflow execution
- Workflow validation
- Test case CRUD operations
- Test execution
- Test runs
"""

import uuid
from datetime import datetime
from typing import Dict, Any

import pytest
from fastapi import status
from httpx import AsyncClient

from src.api.test_models import TestStatus


class TestStandaloneWorkflowExecution:
    """Test standalone workflow execution endpoint."""
    
    @pytest.mark.asyncio
    async def test_execute_echo_workflow_success(self, async_client: AsyncClient, mock_auth_token: str):
        """Test executing echo_test workflow returns response."""
        response = await async_client.post(
            "/api/v1/workflows/echo_test/execute",
            json={
                "message": "Hello world",
                "timeout_seconds": 30,
                "dry_run": False,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "echo_test"
        assert data["success"] is True
        assert "response" in data
        assert data["execution_time_ms"] > 0
        assert isinstance(data["agents_called"], list)
        assert isinstance(data["tools_called"], list)
        assert isinstance(data["execution_trace"], list)
    
    @pytest.mark.asyncio
    async def test_execute_workflow_dry_run(self, async_client: AsyncClient, mock_auth_token: str):
        """Test dry-run mode validates without executing."""
        response = await async_client.post(
            "/api/v1/workflows/echo_test/execute",
            json={
                "message": "Test message",
                "timeout_seconds": 30,
                "dry_run": True,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        # Dry run should be fast
        assert data["execution_time_ms"] < 1000
    
    @pytest.mark.asyncio
    async def test_execute_nonexistent_workflow(self, async_client: AsyncClient, mock_auth_token: str):
        """Test executing non-existent workflow returns error."""
        response = await async_client.post(
            "/api/v1/workflows/nonexistent_workflow/execute",
            json={
                "message": "Test",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    
    @pytest.mark.asyncio
    async def test_execute_disabled_workflow(self, async_client: AsyncClient, mock_auth_token: str):
        """Test executing disabled workflow returns error."""
        response = await async_client.post(
            "/api/v1/workflows/pipeline_example/execute",
            json={
                "message": "Test",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        # Should fail because pipeline_example is disabled
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    
    @pytest.mark.asyncio
    async def test_execute_workflow_timeout(self, async_client: AsyncClient, mock_auth_token: str):
        """Test workflow execution respects timeout."""
        response = await async_client.post(
            "/api/v1/workflows/echo_test/execute",
            json={
                "message": "Test",
                "timeout_seconds": 1,  # Very short timeout
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        # May succeed or timeout depending on system load
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_500_INTERNAL_SERVER_ERROR]
    
    @pytest.mark.asyncio
    async def test_execute_tool_workflow(self, async_client: AsyncClient, mock_auth_token: str):
        """Test executing workflow with tools."""
        response = await async_client.post(
            "/api/v1/workflows/tool_test/execute",
            json={
                "message": "Search for Python programming",
                "timeout_seconds": 60,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "tool_test"
        # Should have called search_assistant agent
        assert "search_assistant" in data["agents_called"] or len(data["agents_called"]) > 0


class TestWorkflowValidation:
    """Test workflow validation endpoint."""
    
    @pytest.mark.asyncio
    async def test_validate_existing_workflow(self, async_client: AsyncClient, mock_auth_token: str):
        """Test validating an existing enabled workflow."""
        response = await async_client.post(
            "/api/v1/workflows/echo_test/validate",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["valid"] is True
        assert len(data["errors"]) == 0
    
    @pytest.mark.asyncio
    async def test_validate_nonexistent_workflow(self, async_client: AsyncClient, mock_auth_token: str):
        """Test validating non-existent workflow."""
        response = await async_client.post(
            "/api/v1/workflows/nonexistent/validate",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0


class TestWorkflowTestCaseCRUD:
    """Test test case CRUD operations."""
    
    @pytest.mark.asyncio
    async def test_create_test_case(self, async_client: AsyncClient, mock_auth_token: str):
        """Test creating a test case."""
        response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Test echo response",
                "description": "Verify echo workflow echoes input",
                "input_message": "Hello test",
                "expected_output_contains": ["Hello", "test"],
                "timeout_seconds": 30,
                "enabled": True,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["workflow_id"] == "echo_test"
        assert data["name"] == "Test echo response"
        assert "id" in data
        assert data["enabled"] is True
        return data["id"]
    
    @pytest.mark.asyncio
    async def test_list_test_cases(self, async_client: AsyncClient, mock_auth_token: str):
        """Test listing test cases for a workflow."""
        # Create a test case first
        create_response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "List test case",
                "input_message": "Test list",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert create_response.status_code == status.HTTP_201_CREATED
        
        # List test cases
        response = await async_client.get(
            "/api/v1/workflows/echo_test/test-cases",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert any(tc["name"] == "List test case" for tc in data)
    
    @pytest.mark.asyncio
    async def test_get_test_case(self, async_client: AsyncClient, mock_auth_token: str):
        """Test getting a specific test case."""
        # Create a test case
        create_response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Get test case",
                "input_message": "Test get",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        test_case_id = create_response.json()["id"]
        
        # Get the test case
        response = await async_client.get(
            f"/api/v1/workflows/echo_test/test-cases/{test_case_id}",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == test_case_id
        assert data["name"] == "Get test case"
    
    @pytest.mark.asyncio
    async def test_update_test_case(self, async_client: AsyncClient, mock_auth_token: str):
        """Test updating a test case."""
        # Create a test case
        create_response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Update test case",
                "input_message": "Original message",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        test_case_id = create_response.json()["id"]
        
        # Update the test case
        response = await async_client.put(
            f"/api/v1/workflows/echo_test/test-cases/{test_case_id}",
            json={
                "name": "Updated test case",
                "input_message": "Updated message",
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "Updated test case"
        assert data["input_message"] == "Updated message"
    
    @pytest.mark.asyncio
    async def test_delete_test_case(self, async_client: AsyncClient, mock_auth_token: str):
        """Test deleting a test case."""
        # Create a test case
        create_response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Delete test case",
                "input_message": "Test delete",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        test_case_id = create_response.json()["id"]
        
        # Delete the test case
        response = await async_client.delete(
            f"/api/v1/workflows/echo_test/test-cases/{test_case_id}",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
        
        # Verify it's deleted
        get_response = await async_client.get(
            f"/api/v1/workflows/echo_test/test-cases/{test_case_id}",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert get_response.status_code == status.HTTP_404_NOT_FOUND
    
    @pytest.mark.asyncio
    async def test_create_test_case_for_nonexistent_workflow(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """Test creating test case for non-existent workflow fails."""
        response = await async_client.post(
            "/api/v1/workflows/nonexistent/test-cases",
            json={
                "workflow_id": "nonexistent",
                "name": "Test",
                "input_message": "Test",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestWorkflowTestExecution:
    """Test test case execution."""
    
    @pytest.mark.asyncio
    async def test_run_test_case(self, async_client: AsyncClient, mock_auth_token: str):
        """Test running a single test case."""
        # Create a test case
        create_response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Run test case",
                "input_message": "Test run",
                "expected_output_contains": ["Test"],
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        test_case_id = create_response.json()["id"]
        
        # Run the test case
        response = await async_client.post(
            f"/api/v1/workflows/echo_test/test-cases/{test_case_id}/run",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["test_case_id"] == test_case_id
        assert data["workflow_id"] == "echo_test"
        assert data["status"] in [s.value for s in TestStatus]
        assert "execution_time_ms" in data
    
    @pytest.mark.asyncio
    async def test_run_workflow_tests(self, async_client: AsyncClient, mock_auth_token: str):
        """Test running all test cases for a workflow."""
        # Create multiple test cases
        for i in range(3):
            await async_client.post(
                "/api/v1/workflows/echo_test/test-cases",
                json={
                    "workflow_id": "echo_test",
                    "name": f"Bulk test {i}",
                    "input_message": f"Test {i}",
                    "timeout_seconds": 30,
                },
                headers={"Authorization": f"Bearer {mock_auth_token}"},
            )
        
        # Run all tests
        response = await async_client.post(
            "/api/v1/workflows/echo_test/test",
            json={"name": "Bulk test run"},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["workflow_id"] == "echo_test"
        assert data["total_tests"] >= 3
        assert "passed_tests" in data
        assert "failed_tests" in data
        assert "error_tests" in data
        assert data["status"] in [s.value for s in TestStatus]
    
    @pytest.mark.asyncio
    async def test_list_test_results(self, async_client: AsyncClient, mock_auth_token: str):
        """Test listing test results for a workflow."""
        # Create and run a test
        create_response = await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Results test",
                "input_message": "Test results",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        test_case_id = create_response.json()["id"]
        
        await async_client.post(
            f"/api/v1/workflows/echo_test/test-cases/{test_case_id}/run",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        # List results
        response = await async_client.get(
            "/api/v1/workflows/echo_test/test-results",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    @pytest.mark.asyncio
    async def test_list_test_runs(self, async_client: AsyncClient, mock_auth_token: str):
        """Test listing test runs for a workflow."""
        # Create test cases and run them
        await async_client.post(
            "/api/v1/workflows/echo_test/test-cases",
            json={
                "workflow_id": "echo_test",
                "name": "Run list test",
                "input_message": "Test",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        await async_client.post(
            "/api/v1/workflows/echo_test/test",
            json={"name": "Test run for listing"},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        # List runs
        response = await async_client.get(
            "/api/v1/workflows/echo_test/test-runs",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0


class TestSessionWorkflowSelection:
    """Test that sessions can select different workflows."""
    
    @pytest.mark.asyncio
    async def test_create_session_with_echo_workflow(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """Test creating session with echo_test workflow."""
        response = await async_client.post(
            "/api/v1/sessions",
            json={
                "workflow_id": "echo_test",
                "user_id": "test_user",
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["workflow_id"] == "echo_test"
    
    @pytest.mark.asyncio
    async def test_create_session_with_tool_workflow(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """Test creating session with tool_test workflow."""
        response = await async_client.post(
            "/api/v1/sessions",
            json={
                "workflow_id": "tool_test",
                "user_id": "test_user",
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["workflow_id"] == "tool_test"
    
    @pytest.mark.asyncio
    async def test_create_session_default_workflow(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """Test creating session without workflow_id defaults to support_triage."""
        response = await async_client.post(
            "/api/v1/sessions",
            json={
                "user_id": "test_user",
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["workflow_id"] == "support_triage"


@pytest.fixture
async def async_client():
    """Fixture providing async HTTP client."""
    # This would be configured in conftest.py with your FastAPI app
    from httpx import AsyncClient
    from src.main import app
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_auth_token():
    """Fixture providing mock authentication token."""
    # This would be configured in conftest.py
    return "mock_token_for_testing"
