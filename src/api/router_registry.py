"""Router registration for the public API surface."""

from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    """Register API routers in a predictable order."""
    from src.api.routers import (
        agents,
        api_providers,
        audit,
        auth,
        builder,
        chat_stream,
        configs,
        crewai_config,
        deployments,
        files,
        functions,
        health,
        integrations,
        library,
        prompts,
        rag,
        sessions,
        studio,
        tools,
        topologies,
        triggers,
        vector_dbs,
        voice,
        workflows,
    )

    app.include_router(auth.router)
    app.include_router(sessions.router)
    app.include_router(chat_stream.router)
    app.include_router(voice.router)
    app.include_router(studio.router)
    app.include_router(agents.router)
    app.include_router(tools.router)
    app.include_router(integrations.router)
    app.include_router(workflows.router)
    app.include_router(topologies.router)
    app.include_router(prompts.router)
    app.include_router(api_providers.router)
    app.include_router(configs.router)
    app.include_router(crewai_config.router)
    app.include_router(vector_dbs.router)
    app.include_router(library.router)
    app.include_router(builder.router)
    app.include_router(functions.router)
    app.include_router(triggers.router)
    app.include_router(triggers.webhook_router)
    app.include_router(deployments.router)
    app.include_router(deployments.pages_router)
    app.include_router(files.router)
    app.include_router(rag.router)
    app.include_router(audit.router)
    app.include_router(health.router)
