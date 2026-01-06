/**
 * Structured logging for the Slack bot
 */

import winston from 'winston';

const { combine, timestamp, printf, colorize, errors } = winston.format;

const logFormat = printf(({ level, message, timestamp, ...metadata }) => {
  let meta = '';
  if (Object.keys(metadata).length > 0) {
    meta = ` ${JSON.stringify(metadata)}`;
  }
  return `${timestamp} [${level}]: ${message}${meta}`;
});

export const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: combine(
    errors({ stack: true }),
    timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
    logFormat
  ),
  transports: [
    new winston.transports.Console({
      format: combine(colorize(), logFormat),
    }),
  ],
});

// Add file transport in production
if (process.env.NODE_ENV === 'production') {
  logger.add(
    new winston.transports.File({
      filename: '/var/log/slack-bot/error.log',
      level: 'error',
    })
  );
  logger.add(
    new winston.transports.File({
      filename: '/var/log/slack-bot/combined.log',
    })
  );
}

export default logger;
