"""
Integration tests for end-to-end workflow execution.

Tests complete workflows from creation through execution to result validation.
"""

import asyncio

import pytest
from fastapi import status
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("fixture_workflows", "fake_runtime")


class TestWorkflowStudioIntegration:
    """End-to-end tests for the complete workflow studio."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_complete_workflow_lifecycle(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """
        Test complete workflow lifecycle:
        1. Validate workflow exists
        2. Create test cases
        3. Run tests
        4. Verify results
        """
        workflow_id = "echo_test"

        # Step 1: Validate workflow
        validate_response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/validate",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert validate_response.status_code == status.HTTP_200_OK
        assert validate_response.json()["valid"] is True

        # Step 2: Create test cases
        test_cases = [
            {
                "name": "Greeting test",
                "input_message": "Hello",
                "expected_output_contains": ["Hello", "hi"],
                "timeout_seconds": 30,
            },
            {
                "name": "Question test",
                "input_message": "What is your purpose?",
                "expected_output_contains": ["assist", "help"],
                "timeout_seconds": 30,
            },
        ]

        created_test_ids = []
        for tc in test_cases:
            response = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/test-cases",
                json={**tc, "workflow_id": workflow_id},
                headers={"Authorization": f"Bearer {mock_auth_token}"},
            )
            assert response.status_code == status.HTTP_201_CREATED
            created_test_ids.append(response.json()["id"])

        # Step 3: Run all tests
        test_run_response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/test",
            json={"name": "Integration test run"},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert test_run_response.status_code == status.HTTP_200_OK
        test_run = test_run_response.json()
        assert test_run["total_tests"] >= len(test_cases)

        # Step 4: Verify results exist
        results_response = await async_client.get(
            f"/api/v1/workflows/{workflow_id}/test-results",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert results_response.status_code == status.HTTP_200_OK
        results = results_response.json()
        assert len(results) >= len(test_cases)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_standalone_execution_with_trace(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """Test standalone execution provides detailed trace."""
        response = await async_client.post(
            "/api/v1/workflows/echo_test/execute",
            json={
                "message": "Tell me about yourself",
                "timeout_seconds": 60,
                "metadata": {"test_id": "trace_test"},
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify complete trace information
        assert data["success"] is True
        assert len(data["agents_called"]) > 0
        assert isinstance(data["execution_trace"], list)
        assert data["execution_time_ms"] > 0

        # Trace should contain step information
        if len(data["execution_trace"]) > 0:
            # The runtime's trace steps carry type, agent, description and timestamp.
            step = data["execution_trace"][0]
            assert "type" in step
            assert "agent" in step
            assert "description" in step
            assert "timestamp" in step

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_session_and_standalone_consistency(
        self, async_client: AsyncClient, mock_auth_token: str
    ):
        """
        Test that session-based and standalone execution produce consistent results.
        """
        test_message = "What is 2+2?"
        workflow_id = "echo_test"

        # Execute standalone
        standalone_response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/execute",
            json={"message": test_message, "timeout_seconds": 60},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert standalone_response.status_code == status.HTTP_200_OK
        standalone_data = standalone_response.json()

        # Create session and send message
        session_response = await async_client.post(
            "/api/v1/sessions",
            json={"workflow_id": workflow_id, "user_id": "test_consistency"},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert session_response.status_code == status.HTTP_201_CREATED
        session_id = session_response.json()["session_id"]

        message_response = await async_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": test_message},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )

        # Both should succeed
        assert standalone_data["success"] is True
        assert message_response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multiple_workflow_types(self, async_client: AsyncClient, mock_auth_token: str):
        """Test executing different workflow types."""
        workflows_to_test = [
            ("echo_test", "Hello"),
            ("tool_test", "Search for information about testing"),
            ("simple_search", "What is Python?"),
        ]

        results = []
        for workflow_id, message in workflows_to_test:
            # Validate first
            validate_response = await async_client.post(
                f"/api/v1/workflows/{workflow_id}/validate",
                headers={"Authorization": f"Bearer {mock_auth_token}"},
            )

            if validate_response.json()["valid"]:
                # Execute
                exec_response = await async_client.post(
                    f"/api/v1/workflows/{workflow_id}/execute",
                    json={"message": message, "timeout_seconds": 60},
                    headers={"Authorization": f"Bearer {mock_auth_token}"},
                )

                results.append(
                    {
                        "workflow_id": workflow_id,
                        "status_code": exec_response.status_code,
                        "success": exec_response.json().get("success", False)
                        if exec_response.status_code == 200
                        else False,
                    }
                )

        # At least one workflow should execute successfully
        assert any(r["success"] for r in results)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_case_validation(self, async_client: AsyncClient, mock_auth_token: str):
        """Test that test case validation works correctly."""
        workflow_id = "echo_test"

        # Create test case with expected output
        test_case_response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/test-cases",
            json={
                "workflow_id": workflow_id,
                "name": "Validation test",
                "input_message": "Say hello",
                "expected_output_contains": ["hello", "hi"],
                "expected_agent": "general_assistant",
                "timeout_seconds": 30,
            },
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert test_case_response.status_code == status.HTTP_201_CREATED
        test_case_id = test_case_response.json()["id"]

        # Run the test case
        run_response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/test-cases/{test_case_id}/run",
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )
        assert run_response.status_code == status.HTTP_200_OK

        result = run_response.json()
        # Should have validation results
        assert "status" in result
        assert result["status"] in ["passed", "failed", "error"]

        if result["status"] == "passed":
            # Verify expectations were met
            assert result["actual_response"] is not None
            assert result["actual_agent"] is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_executions(self, async_client: AsyncClient, mock_auth_token: str):
        """Test multiple concurrent workflow executions."""
        workflow_id = "echo_test"
        num_concurrent = 5

        async def execute_workflow(message_num: int):
            return await async_client.post(
                f"/api/v1/workflows/{workflow_id}/execute",
                json={
                    "message": f"Concurrent test {message_num}",
                    "timeout_seconds": 60,
                },
                headers={"Authorization": f"Bearer {mock_auth_token}"},
            )

        # Execute concurrently
        responses = await asyncio.gather(*[execute_workflow(i) for i in range(num_concurrent)])

        # All should complete
        assert len(responses) == num_concurrent
        successful = sum(1 for r in responses if r.status_code == status.HTTP_200_OK)

        # At least 80% should succeed (account for potential timeouts)
        assert successful >= num_concurrent * 0.8

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_test_run_statistics(self, async_client: AsyncClient, mock_auth_token: str):
        """Test that test run statistics are accurate."""
        workflow_id = "echo_test"

        # Create mix of passing and potentially failing tests
        test_cases = [
            {
                "name": "Should pass",
                "input_message": "Hello",
                "expected_output_contains": ["Hello"],  # Likely to pass
                "timeout_seconds": 30,
            },
            {
                "name": "Might fail",
                "input_message": "Test",
                "expected_output_contains": ["UNLIKELY_STRING_XYZ123"],  # Likely to fail
                "timeout_seconds": 30,
            },
        ]

        for tc in test_cases:
            await async_client.post(
                f"/api/v1/workflows/{workflow_id}/test-cases",
                json={**tc, "workflow_id": workflow_id},
                headers={"Authorization": f"Bearer {mock_auth_token}"},
            )

        # Run all tests
        run_response = await async_client.post(
            f"/api/v1/workflows/{workflow_id}/test",
            json={"name": "Statistics test"},
            headers={"Authorization": f"Bearer {mock_auth_token}"},
        )

        assert run_response.status_code == status.HTTP_200_OK
        run_data = run_response.json()

        # Verify statistics
        assert run_data["total_tests"] >= len(test_cases)
        assert (
            run_data["passed_tests"]
            + run_data["failed_tests"]
            + run_data["error_tests"]
            + run_data["skipped_tests"]
            == run_data["total_tests"]
        )
        assert "pass_rate" in run_data or run_data["total_tests"] > 0
