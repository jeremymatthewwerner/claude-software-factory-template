/**
 * Railway API integration for deployment management
 *
 * Provides full Railway capabilities:
 * - View deployment logs
 * - Check deployment status
 * - Rollback to previous deployment
 * - Trigger redeploy
 * - List deployments
 */

import { config } from '../config.js';
import logger from '../utils/logger.js';

// Railway API endpoint
const RAILWAY_API = 'https://backboard.railway.com/graphql/v2';

// Service and environment IDs (from Railway dashboard)
// These should be set as environment variables
const SERVICE_ID = process.env.RAILWAY_SERVICE_ID || '';
const ENVIRONMENT_ID = process.env.RAILWAY_ENVIRONMENT_ID || '';

interface RailwayDeployment {
  id: string;
  status: string;
  createdAt: string;
  staticUrl?: string;
  meta?: {
    commitHash?: string;
    commitMessage?: string;
    branch?: string;
  };
}

interface RailwayLogEntry {
  timestamp: string;
  message: string;
  severity?: string;
}

/**
 * Execute a GraphQL query against Railway API
 */
async function railwayQuery<T>(
  query: string,
  variables: Record<string, unknown> = {}
): Promise<T> {
  const token = config.railway?.token || process.env.RAILWAY_TOKEN;

  if (!token) {
    throw new Error('RAILWAY_TOKEN not configured. Add it to environment variables.');
  }

  const response = await fetch(RAILWAY_API, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query, variables }),
  });

  if (!response.ok) {
    throw new Error(`Railway API error: ${response.status} ${response.statusText}`);
  }

  const result = await response.json() as { data?: T; errors?: Array<{ message: string }> };

  if (result.errors && result.errors.length > 0) {
    throw new Error(`Railway GraphQL error: ${result.errors[0].message}`);
  }

  return result.data as T;
}

/**
 * Get current deployment status
 */
export async function getDeploymentStatus(): Promise<{
  status: string;
  deployment?: RailwayDeployment;
  error?: string;
}> {
  try {
    const query = `
      query GetDeployments($serviceId: String!, $environmentId: String!) {
        deployments(
          first: 1
          input: { serviceId: $serviceId, environmentId: $environmentId }
        ) {
          edges {
            node {
              id
              status
              createdAt
              staticUrl
              meta {
                commitHash
                commitMessage
                branch
              }
            }
          }
        }
      }
    `;

    const data = await railwayQuery<{
      deployments: {
        edges: Array<{ node: RailwayDeployment }>;
      };
    }>(query, {
      serviceId: SERVICE_ID,
      environmentId: ENVIRONMENT_ID,
    });

    const deployment = data.deployments.edges[0]?.node;

    if (!deployment) {
      return { status: 'unknown', error: 'No deployments found' };
    }

    return {
      status: deployment.status,
      deployment,
    };
  } catch (error) {
    logger.error('Failed to get deployment status', { error });
    return {
      status: 'error',
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * List recent deployments
 */
export async function listDeployments(
  limit: number = 10
): Promise<{
  deployments: RailwayDeployment[];
  error?: string;
}> {
  try {
    const query = `
      query GetDeployments($serviceId: String!, $environmentId: String!, $first: Int!) {
        deployments(
          first: $first
          input: { serviceId: $serviceId, environmentId: $environmentId }
        ) {
          edges {
            node {
              id
              status
              createdAt
              staticUrl
              meta {
                commitHash
                commitMessage
                branch
              }
            }
          }
        }
      }
    `;

    const data = await railwayQuery<{
      deployments: {
        edges: Array<{ node: RailwayDeployment }>;
      };
    }>(query, {
      serviceId: SERVICE_ID,
      environmentId: ENVIRONMENT_ID,
      first: limit,
    });

    return {
      deployments: data.deployments.edges.map((e) => e.node),
    };
  } catch (error) {
    logger.error('Failed to list deployments', { error });
    return {
      deployments: [],
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Get deployment logs
 */
export async function getDeploymentLogs(
  deploymentId?: string,
  limit: number = 100
): Promise<{
  logs: RailwayLogEntry[];
  error?: string;
}> {
  try {
    // If no deployment ID, get the latest
    let targetDeploymentId = deploymentId;
    if (!targetDeploymentId) {
      const status = await getDeploymentStatus();
      targetDeploymentId = status.deployment?.id;
    }

    if (!targetDeploymentId) {
      return { logs: [], error: 'No deployment found' };
    }

    const query = `
      query GetDeploymentLogs($deploymentId: String!, $limit: Int!) {
        deploymentLogs(deploymentId: $deploymentId, limit: $limit) {
          timestamp
          message
          severity
        }
      }
    `;

    const data = await railwayQuery<{
      deploymentLogs: RailwayLogEntry[];
    }>(query, {
      deploymentId: targetDeploymentId,
      limit,
    });

    return { logs: data.deploymentLogs || [] };
  } catch (error) {
    logger.error('Failed to get deployment logs', { error });
    return {
      logs: [],
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Trigger a redeploy of the current service
 */
export async function triggerRedeploy(): Promise<{
  success: boolean;
  deploymentId?: string;
  error?: string;
}> {
  try {
    const query = `
      mutation RedeployService($serviceId: String!, $environmentId: String!) {
        serviceInstanceRedeploy(
          serviceId: $serviceId
          environmentId: $environmentId
        ) {
          id
        }
      }
    `;

    const data = await railwayQuery<{
      serviceInstanceRedeploy: { id: string };
    }>(query, {
      serviceId: SERVICE_ID,
      environmentId: ENVIRONMENT_ID,
    });

    logger.info('Triggered redeploy', { deploymentId: data.serviceInstanceRedeploy.id });

    return {
      success: true,
      deploymentId: data.serviceInstanceRedeploy.id,
    };
  } catch (error) {
    logger.error('Failed to trigger redeploy', { error });
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Rollback to a specific deployment
 */
export async function rollbackToDeployment(
  deploymentId: string
): Promise<{
  success: boolean;
  newDeploymentId?: string;
  error?: string;
}> {
  try {
    const query = `
      mutation RollbackDeployment($deploymentId: String!) {
        deploymentRollback(id: $deploymentId) {
          id
        }
      }
    `;

    const data = await railwayQuery<{
      deploymentRollback: { id: string };
    }>(query, {
      deploymentId,
    });

    logger.info('Rolled back deployment', {
      targetDeploymentId: deploymentId,
      newDeploymentId: data.deploymentRollback.id,
    });

    return {
      success: true,
      newDeploymentId: data.deploymentRollback.id,
    };
  } catch (error) {
    logger.error('Failed to rollback deployment', { error });
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Get service information
 */
export async function getServiceInfo(): Promise<{
  name?: string;
  status?: string;
  domains?: string[];
  error?: string;
}> {
  try {
    const query = `
      query GetService($serviceId: String!) {
        service(id: $serviceId) {
          name
          deployments(first: 1) {
            edges {
              node {
                status
                staticUrl
              }
            }
          }
        }
      }
    `;

    const data = await railwayQuery<{
      service: {
        name: string;
        deployments: {
          edges: Array<{ node: { status: string; staticUrl?: string } }>;
        };
      };
    }>(query, {
      serviceId: SERVICE_ID,
    });

    const deployment = data.service.deployments.edges[0]?.node;

    return {
      name: data.service.name,
      status: deployment?.status,
      domains: deployment?.staticUrl ? [deployment.staticUrl] : [],
    };
  } catch (error) {
    logger.error('Failed to get service info', { error });
    return {
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Check if Railway integration is configured
 */
export function isRailwayConfigured(): boolean {
  const token = config.railway?.token || process.env.RAILWAY_TOKEN;
  return !!(token && SERVICE_ID && ENVIRONMENT_ID);
}

/**
 * Format deployment for display
 */
export function formatDeployment(deployment: RailwayDeployment): string {
  const commit = deployment.meta?.commitHash?.substring(0, 7) || 'unknown';
  const message = deployment.meta?.commitMessage || 'No message';
  const date = new Date(deployment.createdAt).toLocaleString();

  return `• \`${deployment.id.substring(0, 8)}\` - ${deployment.status} - ${commit} - "${message.substring(0, 50)}" (${date})`;
}

export default {
  getDeploymentStatus,
  listDeployments,
  getDeploymentLogs,
  triggerRedeploy,
  rollbackToDeployment,
  getServiceInfo,
  isRailwayConfigured,
  formatDeployment,
};
