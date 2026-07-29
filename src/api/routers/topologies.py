"""Workflow topology management endpoints."""

from fastapi import APIRouter, HTTPException, Request, status

from src.api.models import (
    TopologyCreateRequest,
    TopologyResponse,
    TopologyValidationResponse,
    WorkflowExecutionStatusResponse,
)
from src.api.session_manager import get_session_manager
from src.audit_logging import get_logger
from src.config.topology_models import (
    AgentNode,
    AgentEdge,
    ContextStrategy,
    TerminationCondition,
    TerminationConditionType,
    TopologyConfig,
    TopologyType,
)

from src.api.workflow_diagnostics import structural_checks_applicable

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/topologies", tags=["topologies"])


@router.post("", response_model=TopologyResponse, status_code=status.HTTP_201_CREATED)
async def create_topology(
    request: Request,
    body: TopologyCreateRequest,
) -> TopologyResponse:
    """
    Create a workflow topology configuration.
    
    Args:
        request: FastAPI request object
        body: Topology creation request
        
    Returns:
        Created topology configuration
        
    Requirements: 2.1, 2.5
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Creating topology",
        request_id=request_id,
        workflow_id=body.workflow_id,
        topology_type=body.type,
    )
    
    try:
        # Convert request to topology config
        topology_type = TopologyType(body.type)
        
        # Create nodes
        nodes = [
            AgentNode(
                id=node.id,
                agent_id=node.agent_id,
                input_transform=node.input_transform,
                output_transform=node.output_transform,
                timeout=node.timeout,
                config_override=node.config_override,
            )
            for node in body.nodes
        ]
        
        # Create edges
        edges = [
            AgentEdge(
                from_node=edge.from_node,
                to_node=edge.to_node,
                context_strategy=ContextStrategy(edge.context_strategy),
                fields=edge.fields,
                condition=edge.condition,
            )
            for edge in body.edges
        ]
        
        # Create termination conditions for cyclic graphs
        termination_conditions = []
        if body.max_iterations is not None:
            termination_conditions.append(
                TerminationCondition(
                    type=TerminationConditionType.MAX_ITERATIONS,
                    value=body.max_iterations,
                )
            )
        
        # Create topology config
        topology_config = TopologyConfig(
            type=topology_type,
            nodes=nodes,
            edges=edges,
            entry_node=body.entry_node,
            termination_conditions=termination_conditions,
        )
        
        # Validate topology
        workflow_graph = WorkflowGraph(topology_config)
        validation = workflow_graph.validate()
        
        if not validation.is_valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "type": "validation_error",
                    "message": "Invalid topology configuration",
                    "errors": validation.errors,
                    "warnings": validation.warnings,
                },
            )
        
        # TODO: Store topology configuration in workflow
        # For now, return the validated topology
        
        logger.info(
            "Created topology",
            request_id=request_id,
            workflow_id=body.workflow_id,
            node_count=len(nodes),
            edge_count=len(edges),
        )
        
        return TopologyResponse(
            workflow_id=body.workflow_id,
            type=body.type,
            nodes=[node.model_dump() for node in nodes],
            edges=[edge.model_dump() for edge in edges],
            entry_node=body.entry_node,
            max_iterations=body.max_iterations,
            validation={
                "is_valid": validation.is_valid,
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid topology configuration: {str(e)}",
        )
    except Exception as e:
        logger.error(
            "Failed to create topology",
            request_id=request_id,
            workflow_id=body.workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create topology: {str(e)}",
        )


@router.post("/validate", response_model=TopologyValidationResponse)
async def validate_topology(
    request: Request,
    body: TopologyCreateRequest,
) -> TopologyValidationResponse:
    """
    Validate a workflow topology configuration without creating it.
    
    Args:
        request: FastAPI request object
        body: Topology configuration to validate
        
    Returns:
        Validation result
        
    Requirements: 2.5
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Validating topology",
        request_id=request_id,
        workflow_id=body.workflow_id,
        topology_type=body.type,
    )
    
    try:
        # Convert request to topology config
        topology_type = TopologyType(body.type)
        
        nodes = [
            AgentNode(
                id=node.id,
                agent_id=node.agent_id,
                input_transform=node.input_transform,
                output_transform=node.output_transform,
                timeout=node.timeout,
                config_override=node.config_override,
            )
            for node in body.nodes
        ]
        
        edges = [
            AgentEdge(
                from_node=edge.from_node,
                to_node=edge.to_node,
                context_strategy=ContextStrategy(edge.context_strategy),
                fields=edge.fields,
                condition=edge.condition,
            )
            for edge in body.edges
        ]
        
        termination_conditions = []
        if body.max_iterations is not None:
            termination_conditions.append(
                TerminationCondition(
                    type=TerminationConditionType.MAX_ITERATIONS,
                    value=body.max_iterations,
                )
            )
        
        topology_config = TopologyConfig(
            type=topology_type,
            nodes=nodes,
            edges=edges,
            entry_node=body.entry_node,
            termination_conditions=termination_conditions,
        )
        
        # Reachability and edge-count rules assume an explicit edge graph. Most
        # shipped workflows declare no edges at all — selectors route via an LLM
        # at run time, other crews run nodes in declaration order — so applying
        # those rules there reports every non-entry node as unreachable.
        raw_topology = {
            "edges": [edge.model_dump() for edge in body.edges],
            "routing_method": getattr(body, "routing_method", None),
            "domain_agents": getattr(body, "domain_agents", None),
        }
        errors: list[str] = []
        warnings: list[str] = []
        if structural_checks_applicable(raw_topology):
            errors = topology_config.validate_topology()
        else:
            warnings.append(
                "No explicit edges: nodes run in declaration order, or routing is "
                "decided by the selector at run time. Structural checks skipped."
            )

        logger.info(
            "Validated topology",
            request_id=request_id,
            workflow_id=body.workflow_id,
            is_valid=not errors,
            error_count=len(errors),
            warning_count=len(warnings),
        )

        return TopologyValidationResponse(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
        )
        
    except ValueError as e:
        return TopologyValidationResponse(
            is_valid=False,
            errors=[str(e)],
            warnings=[],
        )
    except Exception as e:
        logger.error(
            "Failed to validate topology",
            request_id=request_id,
            workflow_id=body.workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate topology: {str(e)}",
        )


@router.get("/{workflow_id}/status", response_model=WorkflowExecutionStatusResponse)
async def get_workflow_execution_status(
    request: Request,
    workflow_id: str,
) -> WorkflowExecutionStatusResponse:
    """
    Get execution status for a workflow including resource limits.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        
    Returns:
        Workflow execution status
        
    Requirements: 7.1, 7.2
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Getting workflow execution status",
        request_id=request_id,
        workflow_id=workflow_id,
    )
    
    try:
        session_manager = get_session_manager()
        execution_engine = session_manager.execution_engine
        
        # Get current execution count
        active_executions = execution_engine.get_workflow_execution_count(workflow_id)
        
        # Get max concurrent from config
        max_concurrent = execution_engine.config.resource_limits.max_concurrent_executions
        
        # Get pending queue size
        pending_queue = execution_engine._get_pending_queue(workflow_id)
        queued_requests = pending_queue.qsize()
        
        # Check if resource limit is reached
        resource_limit_reached = active_executions >= max_concurrent
        
        logger.info(
            "Retrieved workflow execution status",
            request_id=request_id,
            workflow_id=workflow_id,
            active_executions=active_executions,
            max_concurrent=max_concurrent,
            queued_requests=queued_requests,
        )
        
        return WorkflowExecutionStatusResponse(
            workflow_id=workflow_id,
            active_executions=active_executions,
            max_concurrent=max_concurrent,
            queued_requests=queued_requests,
            resource_limit_reached=resource_limit_reached,
        )
        
    except Exception as e:
        logger.error(
            "Failed to get workflow execution status",
            request_id=request_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow execution status: {str(e)}",
        )
