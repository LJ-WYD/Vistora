---
author: ChatGPT
chapter: 2
chapter_title: Overall Architecture
design_principles:
- AI Native
- Skill First
- Capability Driven
- Knowledge Centric
- Replaceable Provider
last_updated: 2026-06-27
status: Draft
title: Vistora Software Architecture Specification
version: 1.0.0
---

# Chapter 02 - Overall Architecture

> This chapter describes the long-term conceptual architecture. See
> [`/ARCHITECTURE.md`](../ARCHITECTURE.md) for the implemented runtime,
> binding responsibility contracts, compatibility exceptions, and gap
> register.

## Design Goals

This chapter defines the stable architecture of Vistora. The
architecture is designed to remain stable while AI models, providers,
workflows, and infrastructure evolve over time.

### Core Principles

1.  Business logic depends on Skills instead of models.
2.  Skills depend on Capabilities instead of Providers.
3.  Providers abstract local and cloud models.
4.  Knowledge is a first-class system asset.
5.  All major components are replaceable.

------------------------------------------------------------------------

# Layered Architecture

``` text
Application
    │
Agent
    │
Skill Graph
    │
Capability Layer
    │
Kernel
    │
Runtime
    │
Provider
    │
Infrastructure
```

## Responsibilities

  Layer            Responsibility
  ---------------- --------------------------------------------------
  Application      UI and user interaction
  Agent            Goal decomposition and orchestration
  Skill Graph      Business workflows composed from reusable skills
  Capability       Stable AI capability interfaces
  Kernel           Scheduling, memory, context, state
  Runtime          Model routing and execution
  Provider         Local or cloud AI providers
  Infrastructure   Storage, queue, compute, network

------------------------------------------------------------------------

# Mermaid Component Diagram

``` mermaid
graph TD
A[Application]
B[Agent]
C[Skill Graph]
D[Capability]
E[Kernel]
F[Runtime]
G[Provider]
H[Infrastructure]

A-->B
B-->C
C-->D
D-->E
E-->F
F-->G
G-->H
```

------------------------------------------------------------------------

# Architecture Decision Record

## ADR-001

Decision: Use Skill Graph instead of directly orchestrating models.

Reason:

-   Better modularity
-   Better testability
-   Easier provider replacement
-   Long-term maintainability

Consequence:

Business logic never depends on a specific AI model.

------------------------------------------------------------------------

# Kernel Responsibilities

-   Context Engine
-   Memory Engine
-   Knowledge Engine
-   Workflow Engine
-   Task Scheduler
-   State Manager
-   Event Bus
-   Provider Manager

------------------------------------------------------------------------

# Provider Strategy

Supported providers include:

-   Local Runtime
-   Ollama
-   LM Studio
-   vLLM
-   OpenAI-compatible APIs
-   Future providers

Providers implement capability contracts rather than exposing
model-specific APIs.

------------------------------------------------------------------------

# Future Evolution

Future chapters will specify:

-   Kernel Design
-   Skill Specification
-   Capability API
-   Knowledge Graph
-   Memory System
-   Workflow Engine
-   Provider Runtime
-   Engineering Standards
