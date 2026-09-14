declare module "cloudflare:workers" {
  export const env: {
    DB?: D1Database;
    JOB_FEEDS?: R2Bucket;
    JOB_FEED_SYNC_SECRET?: string;
    AGENT_SEARCH_URL?: string;
    AGENT_SEARCH_TOKEN?: string;
    AGENT_KNOWLEDGE_URL?: string;
    AGENT_KNOWLEDGE_TOKEN?: string;
    AGENT_CAREER_URL?: string;
    AGENT_CAREER_TOKEN?: string;
    AGENT_PRODUCT_TOKEN?: string;
    AGENT_ASSISTANT_URL?: string;
    AGENT_ASSISTANT_TOKEN?: string;
  };
}
