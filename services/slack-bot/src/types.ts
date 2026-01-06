/**
 * Type definitions for Claude Factory Slack Bot
 */

// Agent types matching existing infrastructure
export type AgentType = 'triage' | 'code' | 'qa' | 'devops' | 'release' | 'principal-engineer';

export type AgentStatus = 'started' | 'progress' | 'completed' | 'failed';

// Slack session tracking
export interface SlackSession {
  channelId: string;
  threadTs: string;
  workingDirectory: string;
  claudeSessionId?: string;
  linkedIssue?: number;
  linkedPR?: number;
  activeAgent?: AgentType;
  status: 'active' | 'waiting' | 'completed';
  createdAt: string;
  updatedAt: string;
  userId: string;
  conversationHistory: ConversationMessage[];
}

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  slackTs?: string;
}

// Agent status webhook payload
export interface AgentStatusPayload {
  agent: AgentType;
  status: AgentStatus;
  issueNumber?: number;
  prNumber?: number;
  slackThreadTs?: string;
  slackChannelId?: string;
  message?: string;
  links?: {
    pr?: string;
    issue?: string;
    run?: string;
    deployment?: string;
  };
  details?: Record<string, unknown>;
}

// Intent detection for message routing
export type IntentType =
  | 'conversation'
  | 'dispatch'
  | 'status'
  | 'help'
  | 'factory-status'
  | 'factory-analyze'
  | 'factory-failures'
  | 'factory-agents'
  | 'factory-workflows';

export interface MessageIntent {
  type: IntentType;
  agent?: AgentType;
  confidence: number;
  extractedTask?: string;
  suggestedAgent?: AgentType;
}

export interface ParsedMessage {
  intent: MessageIntent;
  content: string;
  targetAgent?: AgentType;
  issueNumber?: number;
  command?: string;
  args?: string[];
}

// Channel configuration
export interface ChannelConfig {
  channelId: string;
  defaultRepo?: string;
  workingDirectory?: string;
  enabledAgents: AgentType[];
  autoDispatch: boolean;
  notifyOnAgentComplete: boolean;
}

// State management
export interface BotState {
  sessions: Record<string, SlackSession>;
  channelConfigs: Record<string, ChannelConfig>;
}

// Slack Block Kit types for interactive messages
export interface ActionButton {
  type: 'button';
  text: { type: 'plain_text'; text: string };
  action_id: string;
  style?: 'primary' | 'danger';
  value?: string;
  url?: string;
}

export interface ActionBlock {
  type: 'actions';
  elements: ActionButton[];
}

export interface SectionBlock {
  type: 'section';
  text: {
    type: 'mrkdwn' | 'plain_text';
    text: string;
  };
  accessory?: ActionButton;
}

export interface DividerBlock {
  type: 'divider';
}

export interface ContextBlock {
  type: 'context';
  elements: Array<{
    type: 'mrkdwn' | 'plain_text';
    text: string;
  }>;
}

export type SlackBlock = SectionBlock | ActionBlock | DividerBlock | ContextBlock;
