#!/usr/bin/env node
/**
 * MCP Server entry point
 *
 * Run with: npx ts-node src/mcp/index.ts
 * Or after build: node dist/mcp/index.js
 */

import { runMcpServer } from './slack-mcp-server.js';

runMcpServer().catch((error) => {
  console.error('Failed to start MCP server:', error);
  process.exit(1);
});
