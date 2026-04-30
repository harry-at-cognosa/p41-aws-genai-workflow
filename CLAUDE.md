# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

This repository is **greenfield** — no source code, build files, or tests exist yet. The only substantive content is the spec at `docs/AI-powered-document-summarization-workflow_on_AWS.md`.

## Intended scope (from the spec)

A small AWS proof-of-concept for AI-powered document summarization:

- User uploads a text document
- Document is stored in **S3**
- An **AWS Lambda** function processes it
- Lambda generates a short **AI summary** (model/provider not yet chosen)
- Summary is saved or returned to the caller

Required qualities called out in the spec: simple upload flow, basic error handling, short setup docs, and clean enough to extend later. Treat it as a PoC, not production — but build it so the seams (storage, processing, summarization) can be swapped without a rewrite.

## Decisions still open

These are not specified anywhere yet — confirm with the user before locking them in:

- **IaC tool** (CDK / SAM / Terraform / plain CloudFormation) — none chosen
- **Lambda runtime** (Python vs Node.js) — none chosen
- **LLM provider** for summarization (Bedrock vs Anthropic API vs other) — none chosen
- **Trigger model** (S3 event → Lambda vs API Gateway → Lambda) — spec says "upload flow" but doesn't specify
- **Output sink** (write summary back to S3, DynamoDB, return in HTTP response) — spec says "save or return"

When the user asks to start building, surface these choices first rather than guessing.
