"""Model Context Protocol server exposing the analyzer to Claude Desktop.

A thin front end like the GUI: it calls the analyzer API and the assistant core,
reads project files and the user's analyzer state, and talks to the client over
stdio only (standard library, no network). See docs/AI_ASSISTANT_DESIGN.md.
"""
